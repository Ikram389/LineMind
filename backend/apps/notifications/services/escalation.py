"""Escalation: a warning or critical alert still not acknowledged after the rule's
`escalate_after_minutes` is sent once to the rule's escalation roles."""

from datetime import datetime, timedelta

from django.db import transaction

from apps.notifications.models import Alert, AlertStatus, Severity
from apps.notifications.services.live import queue_alert_message
from apps.notifications.services.notify import notify_escalation


def escalate_due(now: datetime) -> list[Alert]:
    escalated = []
    candidates = Alert.objects.filter(
        status=AlertStatus.OPEN,
        escalated_at__isnull=True,
        severity__in=[Severity.WARNING, Severity.CRITICAL],
        rule__escalate_after_minutes__isnull=False,
    ).select_related("rule", "factory")
    for alert in candidates:
        if alert.opened_at + timedelta(minutes=alert.rule.escalate_after_minutes) > now:
            continue
        with transaction.atomic():
            # Claim it: only one worker can set escalated_at, so it happens once.
            claimed = Alert.objects.filter(
                pk=alert.pk, status=AlertStatus.OPEN, escalated_at__isnull=True
            ).update(escalated_at=now)
            if not claimed:
                continue
            alert.escalated_at = now
            notify_escalation(alert)
            queue_alert_message("alert_updated", alert)
        escalated.append(alert)
    return escalated
