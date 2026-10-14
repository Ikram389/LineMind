"""Background jobs (Celery). Beat runs evaluate_periodic every 30 s (settings.CELERY_BEAT_SCHEDULE);
the other tasks are queued after a commit. Without a broker they run immediately."""

import logging
from collections.abc import Iterable

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import DeliveryStatus, Notification
from apps.notifications.services.emails import deliver
from apps.notifications.services.engine import enabled_rules, evaluate_rules, rules_for_lines
from apps.notifications.services.escalation import escalate_due
from apps.notifications.services.heartbeat import PERIODIC, beat

logger = logging.getLogger(__name__)

EMAIL_MAX_RETRIES = 3
EMAIL_RETRY_BASE_SECONDS = 30  # 30 s, 2 min, 8 min


@shared_task(name="notifications.evaluate_periodic")
def evaluate_periodic() -> dict[str, int]:
    """Every enabled rule (conditions that become true as time passes, and resolutions of
    sliding windows), then escalations. Records the engine's heartbeat first."""
    now = timezone.now()
    beat(PERIODIC, now)
    result = evaluate_rules(enabled_rules(), now)
    escalated = escalate_due(now)
    return {
        "opened": len(result.opened),
        "resolved": len(result.resolved),
        "escalated": len(escalated),
    }


@shared_task(name="notifications.evaluate_for_lines")
def evaluate_for_lines(line_ids: list[int], triggers: list[str]) -> dict[str, int]:
    """Event-driven: only the rules new data on these lines can affect."""
    result = evaluate_rules(rules_for_lines(line_ids, triggers), timezone.now())
    return {"opened": len(result.opened), "resolved": len(result.resolved)}


def queue_evaluation(line_ids: Iterable[int], triggers: Iterable[str]) -> None:
    """Call inside the transaction that stored the data: runs after it commits."""
    line_ids, triggers = sorted(set(line_ids)), sorted(set(triggers))
    if line_ids and triggers:
        transaction.on_commit(lambda: evaluate_for_lines.delay(line_ids, triggers))


def after_failed_attempt(notification: Notification, retries_done: int) -> str:
    """What to do after a failed attempt: "retry", or "failed" once retries are used up."""
    if retries_done >= EMAIL_MAX_RETRIES:
        notification.status = DeliveryStatus.FAILED
        notification.save(update_fields=["status"])
        logger.error(
            "Alert email %s failed after %s attempts.", notification.pk, notification.attempts
        )
        return "failed"
    return "retry"


@shared_task(bind=True, name="notifications.send_alert_email", max_retries=EMAIL_MAX_RETRIES)
def send_alert_email(self, notification_id: int) -> str:  # type: ignore[no-untyped-def]
    """Send one alert email; retried with backoff (30 s, 2 min, 8 min), then marked failed."""
    notification = (
        Notification.objects.select_related(
            "alert__factory", "alert__line", "alert__machine", "user"
        )
        .filter(pk=notification_id)
        .first()
    )
    if notification is None or notification.status == DeliveryStatus.SENT:
        return "skipped"
    if self.request.is_eager:
        # No broker (tests, a plain dev server): retry right away instead of later.
        for retries_done in range(EMAIL_MAX_RETRIES + 1):
            if deliver(notification):
                return "sent"
            if after_failed_attempt(notification, retries_done) == "failed":
                return "failed"
        return "failed"
    if deliver(notification):
        return "sent"
    if after_failed_attempt(notification, self.request.retries) == "failed":
        return "failed"
    raise self.retry(countdown=EMAIL_RETRY_BASE_SECONDS * 4**self.request.retries)
