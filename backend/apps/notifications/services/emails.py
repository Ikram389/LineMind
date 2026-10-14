"""Alert emails: plain text + simple HTML, sent by the send_alert_email task (with retries)."""

from html import escape
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.notifications.models import DeliveryStatus, Notification, NotificationReason
from apps.notifications.services.messages import SEVERITY_LABELS, render_message


def alert_link(alert_id: int) -> str:
    return f"{settings.FRONTEND_URL}/alerts?alert={alert_id}"


def build_email(notification: Notification) -> EmailMultiAlternatives:
    alert = notification.alert
    zone = ZoneInfo(alert.factory.timezone)
    what = render_message(alert.message_key, alert.message_values)
    severity = SEVERITY_LABELS.get(alert.severity, alert.severity)
    escalated = notification.reason == NotificationReason.ESCALATED
    prefix = "Not acknowledged: " if escalated else ""
    subject = f"[LineMind] {prefix}{severity}: {what}"[:200]
    since = alert.condition_since.astimezone(zone).strftime("%Y-%m-%d %H:%M")
    rows = [
        ("Factory", alert.factory.name),
        ("Line", alert.line.name if alert.line else "–"),
        ("Machine", alert.machine.name if alert.machine else "–"),
        ("What happened", what),
        ("Since", f"{since} ({alert.factory.timezone})"),
        ("Severity", severity),
    ]
    link = alert_link(alert.pk)
    intro = (
        "This alert has not been acknowledged in time."
        if escalated
        else "A new alert needs attention."
    )
    text = "\n".join(
        [intro, "", *(f"{k}: {v}" for k, v in rows), "", f"Open it in LineMind: {link}"]
    )
    html = (
        f"<p>{escape(intro)}</p><table>"
        + "".join(
            f"<tr><th align='left'>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows
        )
        + f"</table><p><a href='{escape(link)}'>Open the alert in LineMind</a></p>"
    )
    email = EmailMultiAlternatives(
        subject, text, settings.DEFAULT_FROM_EMAIL, [notification.user.email]
    )
    email.attach_alternative(html, "text/html")
    return email


def deliver(notification: Notification) -> bool:
    """One attempt. Records the attempt, the error or the sending time; True if sent."""
    notification.attempts += 1
    try:
        build_email(notification).send(fail_silently=False)
    except Exception as exc:  # any mail server problem: recorded, then retried by the task
        notification.error = f"{type(exc).__name__}: {exc}"[:2000]
        notification.save(update_fields=["attempts", "error"])
        return False
    notification.status = DeliveryStatus.SENT
    notification.sent_at = timezone.now()
    notification.error = ""
    notification.save(update_fields=["attempts", "status", "sent_at", "error"])
    return True
