"""Creating and editing maintenance actions (the workflow itself is in workflow.py)."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.maintenance.models import OPEN_STATUSES, MaintenanceAction, Status
from apps.maintenance.services.links import add_links
from apps.maintenance.services.notify import notify_assigned
from apps.maintenance.services.permissions import can_request, has_factory_access, is_supervisor
from apps.maintenance.services.workflow import NotAllowed, WorkflowError, announce, snapshot
from apps.organizations.models import Machine

EDITABLE_BY_REPORTER = {"title", "problem", "action_type"}
EDITABLE_BY_SUPERVISOR = EDITABLE_BY_REPORTER | {
    "priority",
    "due_date",
    "assignee",
    "effectiveness_window_days",
    "min_after_run_hours",
}


def create_action(
    user: User, machine: Machine, fields: dict[str, Any], links: list[dict[str, Any]]
) -> MaintenanceAction:
    if not can_request(user):
        raise NotAllowed("Your role cannot request maintenance.")
    planning = {
        k: fields[k] for k in ("priority", "due_date", "assignee") if fields.get(k) is not None
    }
    if planning and not is_supervisor(user):
        raise NotAllowed("Only supervisors and managers set the assignee, priority and due date.")
    if fields.get("assignee") is not None and not has_factory_access(
        fields["assignee"], machine.line.factory
    ):
        raise WorkflowError("The assignee must have access to this factory.")
    with transaction.atomic():
        action = MaintenanceAction.objects.create(
            factory=machine.line.factory,
            line=machine.line,
            machine=machine,
            reporter=user,
            status=Status.REQUESTED,
            **{k: v for k, v in fields.items() if v is not None},
        )
        add_links(action, links, user)
        record_audit(
            user=user,
            action="maintenance.requested",
            entity=action,
            organization=action.factory.organization,
            before=None,
            after={**snapshot(action), "title": action.title, "links": len(links)},
        )
        announce(action)
    return action


def update_action(
    action: MaintenanceAction, user: User, changes: dict[str, Any]
) -> MaintenanceAction:
    if action.status not in OPEN_STATUSES and set(changes) - {
        "effectiveness_window_days",
        "min_after_run_hours",
    }:
        raise WorkflowError(f"A {action.status} action can no longer be edited.")
    allowed = (
        EDITABLE_BY_SUPERVISOR
        if is_supervisor(user)
        else (EDITABLE_BY_REPORTER if action.reporter_id == user.pk else set())
    )
    refused = set(changes) - allowed
    if refused:
        raise NotAllowed(f"You cannot change: {', '.join(sorted(refused))}.")
    new_assignee = changes.get("assignee")
    if new_assignee is not None and not has_factory_access(new_assignee, action.factory):
        raise WorkflowError("The assignee must have access to this factory.")
    with transaction.atomic():
        action = MaintenanceAction.objects.select_for_update().get(pk=action.pk)
        before = snapshot(action)
        reassigned = "assignee" in changes and changes["assignee"] != action.assignee
        for name, value in changes.items():
            setattr(action, name, value)
        action.save()
        record_audit(
            user=user,
            action="maintenance.updated",
            entity=action,
            organization=action.factory.organization,
            before=before,
            after={
                **snapshot(action),
                **{k: str(v) for k, v in changes.items() if isinstance(v, date)},
            },
        )
        if reassigned and action.status != Status.REQUESTED:
            notify_assigned(action)
        announce(action)
    return action
