"""The confirmed diagnosis of an action, and applying it to the linked stops.

Applying never overwrites silently. A preview first counts the linked stops that are
unclassified, already have this reason, have another reason of the same category, or
have a reason of a different category (operators may have chosen those on purpose).
By default only unclassified and same-category stops are changed; different-category
reasons are replaced only when the technician asks for it.
Each change is a new "technician" classification: the operator's stays in the history,
raw observations are never touched, and the Pareto follows the newest classification.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.downtime.models import DowntimeEvent, DowntimeReason
from apps.downtime.services.classification import record_confirmed_diagnosis
from apps.maintenance.models import MaintenanceAction, MaintenanceDiagnosis, Status
from apps.maintenance.services.links import linked_stops
from apps.maintenance.services.permissions import is_worker
from apps.maintenance.services.workflow import NotAllowed, WorkflowError, announce

DIAGNOSABLE = (Status.IN_PROGRESS, Status.WAITING, Status.DONE)

UNCLASSIFIED, SAME_REASON, SAME_CATEGORY, OTHER = (
    "unclassified",
    "same_reason",
    "same_category",
    "other_reason",
)


def _group(event: DowntimeEvent, reason: DowntimeReason) -> str:
    current = event.current_classification.reason if event.current_classification else None
    if current is None:
        return UNCLASSIFIED
    if current.pk == reason.pk:
        return SAME_REASON
    if current.category == reason.category:
        return SAME_CATEGORY
    return OTHER


def preview(action: MaintenanceAction, reason: DowntimeReason) -> dict[str, Any]:
    stops = linked_stops(action)
    groups = Counter(_group(e, reason) for e in stops)
    others = Counter(
        (e.current_classification.reason.code, e.current_classification.reason.name)
        for e in stops
        if _group(e, reason) == OTHER
    )
    return {
        "linked_stops": len(stops),
        "unclassified": groups[UNCLASSIFIED],
        "same_reason": groups[SAME_REASON],
        "same_category": groups[SAME_CATEGORY],
        "other_reasons": [
            {"code": code, "name": name, "count": count}
            for (code, name), count in sorted(others.items(), key=lambda i: (-i[1], i[0]))
        ],
        "would_apply": groups[UNCLASSIFIED] + groups[SAME_CATEGORY],
        "would_apply_with_replace": groups[UNCLASSIFIED] + groups[SAME_CATEGORY] + groups[OTHER],
    }


def record_diagnosis(
    action: MaintenanceAction,
    reason: DowntimeReason,
    text: str,
    user: User,
    apply_to_stops: bool = False,
    replace_other_reasons: bool = False,
) -> MaintenanceDiagnosis:
    if not is_worker(user, action):
        raise NotAllowed("Only the assignee or a maintenance technician can record a diagnosis.")
    if action.status not in DIAGNOSABLE:
        raise WorkflowError(
            f"A diagnosis is recorded while working on or completing an action, "
            f"not when it is {action.status}."
        )
    if reason.factory_id != action.factory_id or not reason.is_active:
        raise WorkflowError("The reason must be an active downtime reason of this factory.")

    with transaction.atomic():
        applied = skipped = 0
        if apply_to_stops:
            for event in linked_stops(action):
                group = _group(event, reason)
                if group == SAME_REASON or (group == OTHER and not replace_other_reasons):
                    skipped += 1
                    continue
                record_confirmed_diagnosis(event, reason, text or f"Maintenance #{action.pk}", user)
                applied += 1
        diagnosis = MaintenanceDiagnosis.objects.create(
            action=action,
            reason=reason,
            text=text,
            applied_to_stops=apply_to_stops,
            replace_other_reasons=replace_other_reasons,
            applied_count=applied,
            skipped_count=skipped,
            created_by=user,
        )
        record_audit(
            user=user,
            action="maintenance.diagnosed",
            entity=action,
            organization=action.factory.organization,
            before=None,
            after={
                "reason": reason.code,
                "text": text,
                "applied": applied,
                "skipped": skipped,
                "replace_other_reasons": replace_other_reasons,
            },
        )
        announce(action)
    return diagnosis
