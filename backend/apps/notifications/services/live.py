"""Live messages for alerts (line group) and notifications (the user's own group).

Always queued for after the commit: a rolled-back alert is never announced.
"""

from typing import Any

from apps.live.broadcast import after_commit, message, send_now, user_group
from apps.notifications.models import Alert, Channel, Notification


def alert_data(alert: Alert) -> dict[str, Any]:
    return {
        "alert_id": alert.pk,
        "rule_type": alert.rule.rule_type,
        "severity": alert.severity,
        "status": alert.status,
        "line_id": alert.line_id,
        "machine_id": alert.machine_id,
        "subject_type": alert.subject_type,
        "subject_id": alert.subject_id,
        "opened_at": alert.opened_at,
        "condition_since": alert.condition_since,
        "message_key": alert.message_key,
        "message_values": alert.message_values,
        "acknowledged_at": alert.acknowledged_at,
        "resolved_at": alert.resolved_at,
        "resolution": alert.resolution,
    }


def queue_alert_message(message_type: str, alert: Alert) -> None:
    """alert_opened / alert_updated / alert_resolved to the alert's line, after commit."""
    if alert.line_id is None:
        return
    payload = message(message_type, alert.line_id, alert_data(alert))
    after_commit(lambda: send_now(alert.line_id, payload))


def unread_count(user_id: int) -> int:
    return Notification.objects.filter(
        user_id=user_id, channel=Channel.IN_APP, read_at__isnull=True
    ).count()


def queue_unread_count(user_ids: set[int]) -> None:
    """notification_created (or _read) with the new unread count, to each user's group."""

    def publish() -> None:
        for user_id in user_ids:
            payload = message("notifications_changed", 0, {"unread_count": unread_count(user_id)})
            send_now(0, payload, group=user_group(user_id))

    if user_ids:
        after_commit(publish)
