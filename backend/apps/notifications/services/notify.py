"""Turn an alert into notifications: in-app rows, email jobs and the live unread count.

Each user's preferences decide the channels: in-app from `in_app_min_severity` (never
off), email from `email_min_severity` (or never). A user is notified at most once per
alert, channel and reason (a database constraint), so nothing is sent twice.
"""

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import (
    Alert,
    Channel,
    DeliveryStatus,
    Notification,
    NotificationPreference,
    NotificationReason,
    at_least,
)
from apps.notifications.services.live import queue_unread_count
from apps.notifications.services.recipients import recipients


def preference(user: User) -> NotificationPreference:
    found = NotificationPreference.objects.filter(user=user).first()
    return found or NotificationPreference(user=user)  # defaults, not saved until changed


def notify(alert: Alert, users: Iterable[User], reason: str) -> list[Notification]:
    created: list[Notification] = []
    now = timezone.now()
    for user in users:
        prefs = preference(user)
        channels = []
        if at_least(alert.severity, prefs.in_app_min_severity):
            channels.append(Channel.IN_APP)
        if at_least(alert.severity, prefs.email_min_severity) and user.email:
            channels.append(Channel.EMAIL)
        for channel in channels:
            notification, is_new = Notification.objects.get_or_create(
                alert=alert,
                user=user,
                channel=channel,
                reason=reason,
                defaults={
                    "status": DeliveryStatus.SENT
                    if channel == Channel.IN_APP
                    else DeliveryStatus.PENDING,
                    "sent_at": now if channel == Channel.IN_APP else None,
                },
            )
            if is_new:
                created.append(notification)

    emails = [n.pk for n in created if n.channel == Channel.EMAIL]
    if emails:
        from apps.notifications.tasks import send_alert_email

        transaction.on_commit(lambda: [send_alert_email.delay(pk) for pk in emails])
    queue_unread_count({n.user_id for n in created if n.channel == Channel.IN_APP})
    return created


def notify_alert_opened(alert: Alert) -> list[Notification]:
    users = recipients(alert.factory, alert.rule.recipient_roles)
    return notify(alert, users, NotificationReason.OPENED)


def notify_escalation(alert: Alert) -> list[Notification]:
    """The escalation roles, except people already told about this alert."""
    already = Notification.objects.filter(alert=alert).values_list("user_id", flat=True)
    users = recipients(alert.factory, alert.rule.escalation_roles).exclude(pk__in=already)
    return notify(alert, users, NotificationReason.ESCALATED)
