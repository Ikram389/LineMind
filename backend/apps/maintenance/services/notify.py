"""Tell people about maintenance actions (reusing the alert notifications of step 10a):
the assignee when an action is assigned to them, the reporter when it is done."""

from apps.accounts.models import User
from apps.maintenance.models import MaintenanceAction, Priority
from apps.notifications.models import NotificationReason, Severity
from apps.notifications.services.notify import notify_users

# How serious an assignment is, so preferences ("email from warning") apply naturally.
PRIORITY_SEVERITY = {
    Priority.URGENT: Severity.CRITICAL,
    Priority.HIGH: Severity.WARNING,
    Priority.MEDIUM: Severity.INFO,
    Priority.LOW: Severity.INFO,
}


def _values(action: MaintenanceAction) -> dict[str, object]:
    return {
        "action_id": action.pk,
        "title": action.title,
        "machine": action.machine.name,
        "line": action.line.name,
        "priority": action.priority,
        "due_date": action.due_date.isoformat() if action.due_date else "",
    }


def notify_assigned(action: MaintenanceAction) -> None:
    if action.assignee is None:
        return
    notify_users(
        [action.assignee],
        severity=PRIORITY_SEVERITY[Priority(action.priority)],
        reason=NotificationReason.ASSIGNED,
        message_key="maintenance.assigned",
        message_values=_values(action),
        link=f"/maintenance/{action.pk}",
    )


def notify_completed(action: MaintenanceAction, by: User) -> None:
    if action.reporter_id == by.pk:
        return  # no need to tell people what they just did themselves
    notify_users(
        [action.reporter],
        severity=Severity.INFO,
        reason=NotificationReason.COMPLETED,
        message_key="maintenance.completed",
        message_values={**_values(action), "by": by.email},
        link=f"/maintenance/{action.pk}",
    )
