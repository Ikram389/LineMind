"""The status workflow of maintenance actions: only the allowed steps, each one recorded.

    requested -> assigned -> in_progress <-> waiting
                                in_progress -> done -> verified
    requested / assigned / in_progress / waiting -> cancelled   (note required)
    done / verified -> in_progress  ("reopen", note required)

Every step writes a MaintenanceStatusChange and an AuditLog entry in the same
transaction, then tells the line (maintenance_updated) and re-checks the
maintenance_overdue alert rule after the commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.live.broadcast import after_commit, message, send_now
from apps.maintenance.models import (
    MaintenanceAction,
    MaintenanceStatusChange,
    Status,
    VerificationResult,
)
from apps.maintenance.services.notify import notify_assigned, notify_completed
from apps.maintenance.services.permissions import has_factory_access, is_supervisor, is_worker
from apps.notifications.tasks import queue_evaluation


class WorkflowError(ValueError):
    """The step is not allowed from this status, or something it needs is missing (400)."""


class NotAllowed(PermissionError):
    """The user's role may not take this step (403)."""


@dataclass(frozen=True)
class Step:
    event: str
    who: str  # "supervisor", "worker", "supervisor_or_worker", "supervisor_or_reporter"
    note_required: bool = False


S = Status
STEPS: dict[tuple[str, str], Step] = {
    (S.REQUESTED, S.ASSIGNED): Step("assign", "supervisor"),
    (S.ASSIGNED, S.IN_PROGRESS): Step("start", "worker"),
    (S.IN_PROGRESS, S.WAITING): Step("wait", "worker", note_required=True),
    (S.WAITING, S.IN_PROGRESS): Step("resume", "worker"),
    (S.IN_PROGRESS, S.DONE): Step("complete", "worker"),
    (S.REQUESTED, S.CANCELLED): Step("cancel", "supervisor_or_reporter", note_required=True),
    (S.ASSIGNED, S.CANCELLED): Step("cancel", "supervisor", note_required=True),
    (S.IN_PROGRESS, S.CANCELLED): Step("cancel", "supervisor", note_required=True),
    (S.WAITING, S.CANCELLED): Step("cancel", "supervisor", note_required=True),
    (S.DONE, S.IN_PROGRESS): Step("reopen", "supervisor_or_worker", note_required=True),
    (S.VERIFIED, S.IN_PROGRESS): Step("reopen", "supervisor_or_worker", note_required=True),
}
# done -> verified exists too, but only through verify() (it needs a result).


def _may(step_who: str, user: User, action: MaintenanceAction) -> bool:
    if step_who == "supervisor":
        return is_supervisor(user)
    if step_who == "worker":
        return is_worker(user, action)
    if step_who == "supervisor_or_worker":
        return is_supervisor(user) or is_worker(user, action)
    return is_supervisor(user) or action.reporter_id == user.pk


def allowed_steps(action: MaintenanceAction, user: User) -> list[dict[str, str]]:
    """The next steps this user may take now (the UI shows only these)."""
    steps = [
        {"to": to, "event": step.event, "note_required": step.note_required}
        for (src, to), step in STEPS.items()
        if src == action.status and _may(step.who, user, action)
    ]
    if action.status == S.DONE and is_supervisor(user):
        steps.append({"to": S.VERIFIED, "event": "verify", "note_required": False})
    return steps


def snapshot(action: MaintenanceAction) -> dict[str, Any]:
    return {
        "status": action.status,
        "assignee": action.assignee.email if action.assignee else None,
        "priority": action.priority,
        "due_date": action.due_date.isoformat() if action.due_date else None,
        "started_at": action.started_at.isoformat() if action.started_at else None,
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
        "fixed_at": action.fixed_at.isoformat() if action.fixed_at else None,
        "verification_result": action.verification_result,
    }


def announce(action: MaintenanceAction) -> None:
    """maintenance_updated to the line, and the overdue rule re-checked, after commit."""
    payload = message(
        "maintenance_updated",
        action.line_id,
        {
            "action_id": action.pk,
            "status": action.status,
            "title": action.title,
            "machine_id": action.machine_id,
            "assignee_id": action.assignee_id,
            "priority": action.priority,
        },
    )
    after_commit(lambda: send_now(action.line_id, payload))
    queue_evaluation([action.line_id], ["maintenance"])


def _record(
    action: MaintenanceAction, before: dict[str, Any], src: str, event: str, note: str, user: User
) -> None:
    MaintenanceStatusChange.objects.create(
        action=action,
        from_status=src,
        to_status=action.status,
        event=event,
        note=note,
        changed_by=user,
    )
    record_audit(
        user=user,
        action=f"maintenance.{event}",
        entity=action,
        organization=action.factory.organization,
        before=before,
        after={**snapshot(action), "note": note},
    )
    announce(action)


def transition(
    action: MaintenanceAction,
    to: str,
    user: User,
    note: str = "",
    assignee: User | None = None,
    fixed_at: datetime | None = None,
) -> MaintenanceAction:
    with transaction.atomic():
        action = MaintenanceAction.objects.select_for_update().get(pk=action.pk)
        src = action.status
        if (src, to) == (S.DONE, S.VERIFIED):
            raise WorkflowError("Verify a done action with its result (the verify step).")
        step = STEPS.get((src, to))
        if step is None:
            raise WorkflowError(f"Cannot go from {src} to {to}.")
        if not _may(step.who, user, action):
            raise NotAllowed(f"Your role cannot {step.event} this action.")
        note = (note or "").strip()
        if step.note_required and not note:
            raise WorkflowError(f"A note is required to {step.event}.")

        before = snapshot(action)
        now = timezone.now()
        if step.event == "assign":
            assignee = assignee or action.assignee
            if assignee is None:
                raise WorkflowError("Choose who does the work.")
            if not has_factory_access(assignee, action.factory):
                raise WorkflowError("The assignee must have access to this factory.")
            action.assignee = assignee
        elif step.event == "start" and action.started_at is None:
            action.started_at = now
        elif step.event == "complete":
            fixed_at = fixed_at or now
            if fixed_at > now:
                raise WorkflowError("The fix date cannot be in the future.")
            action.completed_at, action.fixed_at = now, fixed_at
        elif step.event == "reopen":
            action.completed_at = action.fixed_at = None
            action.verified_by = action.verified_at = None
            action.verification_result = action.verification_note = ""
        action.status = to
        action.save()
        _record(action, before, src, step.event, note, user)
        if step.event == "assign":
            notify_assigned(action)
        elif step.event == "complete":
            notify_completed(action, user)
    return action


def verify(action: MaintenanceAction, result: str, note: str, user: User) -> MaintenanceAction:
    if result not in VerificationResult.values:
        raise WorkflowError("The result must be effective or not_effective.")
    with transaction.atomic():
        action = MaintenanceAction.objects.select_for_update().get(pk=action.pk)
        if action.status != S.DONE:
            raise WorkflowError(
                f"Only a done action can be verified (this one is {action.status})."
            )
        if not is_supervisor(user):
            raise NotAllowed("Only supervisors and managers can verify.")
        before = snapshot(action)
        action.status = S.VERIFIED
        action.verified_by, action.verified_at = user, timezone.now()
        action.verification_result, action.verification_note = result, (note or "").strip()
        action.save()
        _record(action, before, S.DONE, "verify", action.verification_note, user)
    return action
