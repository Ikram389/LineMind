"""Classifying downtime events. Each change is a new row; raw observations are never touched."""

from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.downtime.models import (
    ClassificationSource,
    DowntimeClassification,
    DowntimeEvent,
    DowntimeReason,
)
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
        record_audit(
            user=user,
            action="downtime.classified",
            entity=event,
            organization=membership.organization,
            before=before,
            after=snapshot(classification),
        )
    return classification
