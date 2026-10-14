"""Classifying downtime events. Each change is a new row; raw observations are never touched."""

from typing import Any

from django.db import transaction
from django.db.models import Count

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.downtime.models import (
    ClassificationSource,
    DowntimeClassification,
    DowntimeEvent,
    DowntimeReason,
)
from apps.notifications.tasks import queue_evaluation
from apps.organizations.models import Role
from apps.organizations.tenancy import get_membership

# Roles allowed to classify stops, and the source recorded for each.
CLASSIFYING_ROLES: dict[str, str] = {
    Role.MACHINE_OPERATOR: ClassificationSource.OPERATOR,
    Role.PRODUCTION_SUPERVISOR: ClassificationSource.SUPERVISOR,
    Role.FACTORY_MANAGER: ClassificationSource.SUPERVISOR,
    Role.PLATFORM_ADMIN: ClassificationSource.SUPERVISOR,
}


class ClassificationError(ValueError):
    pass


def snapshot(classification: DowntimeClassification | None) -> dict[str, Any] | None:
    if classification is None:
        return None
    return {
        "classification_id": classification.pk,
        "reason": classification.reason.code,
        "comment": classification.comment,
        "source": classification.source,
        "created_by": classification.created_by.email if classification.created_by else None,
    }


def classify_downtime(
    event: DowntimeEvent, reason: DowntimeReason, comment: str, user: User
) -> DowntimeClassification:
    membership = get_membership(user)
    if membership is None or membership.role not in CLASSIFYING_ROLES:
        raise ClassificationError("Your role cannot classify downtime.")
    if event.is_obsolete:
        raise ClassificationError("This downtime event no longer exists in the derived data.")
    if reason.factory_id != event.line.factory_id or not reason.is_active:
        raise ClassificationError("The reason must be an active reason of this factory.")

    with transaction.atomic():
        event = DowntimeEvent.objects.select_for_update().get(pk=event.pk)
        before = snapshot(event.current_classification)
        classification = DowntimeClassification.objects.create(
            downtime_event=event,
            reason=reason,
            comment=comment,
            source=CLASSIFYING_ROLES[membership.role],
            created_by=user,
        )
        event.current_classification = classification
        event.save(update_fields=["current_classification", "updated_at"])
        queue_evaluation([event.line_id], ["classification"])
        record_audit(
            user=user,
            action="downtime.classified",
            entity=event,
            organization=membership.organization,
            before=before,
            after=snapshot(classification),
        )
    return classification


# Roles that may classify several stops at once (operators classify one by one).
BULK_CLASSIFYING_ROLES = frozenset(
    {Role.PRODUCTION_SUPERVISOR, Role.FACTORY_MANAGER, Role.PLATFORM_ADMIN}
)


def bulk_classify(
    events: list[DowntimeEvent], reason: DowntimeReason, comment: str, user: User
) -> list[DowntimeClassification]:
    """One reason for several events, each as its own classification (and audit entry).

    All or nothing: if any event cannot be classified, nothing is saved.
    """
    membership = get_membership(user)
    if membership is None or membership.role not in BULK_CLASSIFYING_ROLES:
        raise ClassificationError("Your role cannot classify several stops at once.")
    with transaction.atomic():
        return [classify_downtime(event, reason, comment, user) for event in events]


# Reason categories that usually explain each kind of stop.
LIKELY_REASON_CATEGORIES: dict[str, tuple[str, ...]] = {
    "breakdown": ("mechanical", "electrical"),
    "blocked": ("material", "organizational"),
    "starved": ("material", "organizational"),
    "planned": ("planned",),
    "no_data": ("electrical",),
}


def suggested_reasons(event: DowntimeEvent, limit: int = 6) -> list[DowntimeReason]:
    """Most likely reasons, by how often they were used before (no AI):
    1. for the same machine and alarm code, 2. for the same machine,
    3. reasons whose category usually explains this kind of stop."""
    active = DowntimeReason.objects.filter(factory=event.line.factory_id, is_active=True)
    history = DowntimeClassification.objects.filter(
        downtime_event__machine=event.machine_id, reason__in=active
    ).exclude(downtime_event=event)

    ranked: list[int] = []

    def add(reason_ids: list[int]) -> None:
        for reason_id in reason_ids:
            if reason_id not in ranked:
                ranked.append(reason_id)

    def by_frequency(queryset: Any) -> list[int]:
        return list(
            queryset.values("reason")
            .annotate(uses=Count("id"))
            .order_by("-uses", "reason")
            .values_list("reason", flat=True)
        )

    if event.alarm_code:
        add(by_frequency(history.filter(downtime_event__alarm_code=event.alarm_code)))
    add(by_frequency(history))
    likely = LIKELY_REASON_CATEGORIES.get(event.category, ())
    add(
        list(
            active.filter(category__in=likely)
            .order_by("category", "code")
            .values_list("pk", flat=True)
        )
    )
    reasons = {r.pk: r for r in active.filter(pk__in=ranked[:limit])}
    return [reasons[pk] for pk in ranked[:limit] if pk in reasons]
