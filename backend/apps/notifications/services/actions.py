"""People acting on alerts: acknowledge and resolve manually. Both are audited."""

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.notifications.models import Alert, AlertStatus, Resolution
from apps.notifications.services.live import queue_alert_message
from apps.organizations.models import Role
from apps.organizations.tenancy import get_membership

SUPERVISORS_AND_ABOVE = frozenset(
    {Role.PRODUCTION_SUPERVISOR, Role.FACTORY_MANAGER, Role.PLATFORM_ADMIN}
)


class AlertActionError(ValueError):
    pass


def can_acknowledge(user: User, alert: Alert) -> bool:
    membership = get_membership(user)
    if membership is None:
        return False
    allowed = (
        SUPERVISORS_AND_ABOVE | set(alert.rule.recipient_roles) | set(alert.rule.escalation_roles)
    )
    return membership.role in allowed


def can_resolve(user: User) -> bool:
    membership = get_membership(user)
    return membership is not None and membership.role in SUPERVISORS_AND_ABOVE


def _snapshot(alert: Alert) -> dict[str, Any]:
    return {
        "status": alert.status,
        "acknowledged_by": alert.acknowledged_by.email if alert.acknowledged_by else None,
        "acknowledge_note": alert.acknowledge_note,
        "resolution": alert.resolution,
        "resolution_note": alert.resolution_note,
    }


def acknowledge(alert: Alert, user: User, note: str = "") -> Alert:
    with transaction.atomic():
        alert = Alert.objects.select_for_update().get(pk=alert.pk)
        if alert.status != AlertStatus.OPEN:
            raise AlertActionError(f"This alert is already {alert.status}.")
        before = _snapshot(alert)
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = user
        alert.acknowledged_at = timezone.now()
        alert.acknowledge_note = note
        alert.save(
            update_fields=["status", "acknowledged_by", "acknowledged_at", "acknowledge_note"]
        )
        record_audit(
            user=user,
            action="alert.acknowledged",
            entity=alert,
            organization=alert.factory.organization,
            before=before,
            after=_snapshot(alert),
        )
        queue_alert_message("alert_updated", alert)
    return alert


def resolve_manually(alert: Alert, user: User, note: str) -> Alert:
    if not note.strip():
        raise AlertActionError("Say why the alert is resolved.")
    with transaction.atomic():
        alert = Alert.objects.select_for_update().get(pk=alert.pk)
        if alert.status == AlertStatus.RESOLVED:
            raise AlertActionError("This alert is already resolved.")
        before = _snapshot(alert)
        alert.status = AlertStatus.RESOLVED
        alert.resolution = Resolution.MANUAL
        alert.resolved_at = timezone.now()
        alert.resolved_by = user
        alert.resolution_note = note.strip()
        alert.save(
            update_fields=["status", "resolution", "resolved_at", "resolved_by", "resolution_note"]
        )
        record_audit(
            user=user,
            action="alert.resolved",
            entity=alert,
            organization=alert.factory.organization,
            before=before,
            after=_snapshot(alert),
        )
        queue_alert_message("alert_resolved", alert)
    return alert
