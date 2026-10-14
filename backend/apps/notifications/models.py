"""Alert rules, alerts, notifications, preferences and the alert engine's heartbeat.

- An `AlertRule` says what to watch (its type and parameters), how serious it is and
  who to tell. Rule types live in evaluators/; each turns live data into "findings".
- An `Alert` is one problem about one subject (an incident, a machine, a shift…).
  At most one unresolved alert exists per rule + subject (a database constraint).
- A `Notification` is one delivery of an alert to one user on one channel.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.organizations.models import Factory, Machine, ProductionLine, Role


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


SEVERITY_RANK = {Severity.INFO: 1, Severity.WARNING: 2, Severity.CRITICAL: 3}


def at_least(severity: str, minimum: str) -> bool:
    """True if `severity` is `minimum` or more serious ("off" is never reached)."""
    if minimum == "off":
        return False
    return SEVERITY_RANK[Severity(severity)] >= SEVERITY_RANK[Severity(minimum)]


class RuleType(models.TextChoices):
    LONG_STOP = "long_stop", "Long stop"
    RECURRING_STOP = "recurring_stop", "Recurring stop"
    MACHINE_OFFLINE = "machine_offline", "Machine offline"
    LOW_OEE = "low_oee", "Low OEE"
    HIGH_DEFECT_RATE = "high_defect_rate", "High defect rate"
    UNCLASSIFIED_STOPS = "unclassified_stops", "Unclassified stops"


class AlertRule(models.Model):
    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="alert_rules", db_index=True
    )
    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alert_rules",
        help_text="Empty: every line of the factory.",
    )
    machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alert_rules",
        help_text="Empty: every machine (for machine rules).",
    )
    name = models.CharField(max_length=200, blank=True)
    rule_type = models.CharField(max_length=40, choices=RuleType.choices)
    parameters = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.WARNING)
    is_enabled = models.BooleanField(default=True)
    recipient_roles = ArrayField(
        models.CharField(max_length=40, choices=Role.choices), default=list
    )
    cooldown_minutes = models.PositiveIntegerField(
        default=30, help_text="After an alert is resolved, the same problem cannot reopen sooner."
    )
    escalate_after_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=15,
        help_text="Tell the escalation roles if not acknowledged by then. Empty: never.",
    )
    escalation_roles = ArrayField(
        models.CharField(max_length=40, choices=Role.choices), default=list, blank=True
    )
    active_outside_shifts = models.BooleanField(
        default=False, help_text="Also open alerts outside shifts, breaks and planned stops."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["factory_id", "rule_type", "id"]

    def __str__(self) -> str:
        return self.name or self.get_rule_type_display()


class AlertStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"


class Resolution(models.TextChoices):
    AUTO = "auto", "Automatically (the condition cleared)"
    MANUAL = "manual", "Manually"


class Alert(models.Model):
    rule = models.ForeignKey(AlertRule, on_delete=models.PROTECT, related_name="alerts")
    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="alerts", db_index=True
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts"
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts"
    )
    # What the alert is about, e.g. ("incident", 14, "incident:14") or ("machine", 5, "machine:5").
    subject_type = models.CharField(max_length=40)
    subject_id = models.BigIntegerField(null=True, blank=True)
    subject_key = models.CharField(max_length=200)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    status = models.CharField(
        max_length=20, choices=AlertStatus.choices, default=AlertStatus.OPEN, db_index=True
    )
    opened_at = models.DateTimeField(db_index=True)
    condition_since = models.DateTimeField(help_text="When the problem itself began.")
    # Translated by the UI (and the email catalogue): never stored as an English sentence.
    message_key = models.CharField(max_length=100)
    message_values = models.JSONField(default=dict, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acknowledged_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledge_note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolution = models.CharField(max_length=20, choices=Resolution.choices, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_alerts",
    )
    resolution_note = models.TextField(blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField()

    class Meta:
        ordering = ["-opened_at", "-id"]
        constraints = [
            # Deduplication: never two unresolved alerts for the same rule and subject,
            # even if two workers evaluate at the same moment.
            models.UniqueConstraint(
                fields=["rule", "subject_key"],
                condition=~models.Q(status="resolved"),
                name="one_unresolved_alert_per_rule_subject",
            )
        ]
        indexes = [
            models.Index(fields=["rule", "subject_key", "resolved_at"], name="alert_cooldown_idx"),
            models.Index(fields=["line", "opened_at"], name="alert_line_opened_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.message_key} {self.subject_key} ({self.status})"


class Channel(models.TextChoices):
    IN_APP = "in_app", "In the app"
    EMAIL = "email", "Email"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class NotificationReason(models.TextChoices):
    OPENED = "opened", "The alert opened"
    ESCALATED = "escalated", "Not acknowledged in time"


class Notification(models.Model):
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="notifications")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    reason = models.CharField(
        max_length=20, choices=NotificationReason.choices, default=NotificationReason.OPENED
    )
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["alert", "user", "channel", "reason"], name="one_notification_per_delivery"
            )
        ]
        indexes = [
            models.Index(fields=["user", "channel", "read_at"], name="notification_unread_idx")
        ]

    def __str__(self) -> str:
        return f"{self.channel} to user {self.user_id} for alert {self.alert_id}"


class MinimumSeverity(models.TextChoices):
    OFF = "off", "Off"
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class NotificationPreference(models.Model):
    """Per user: from which severity each channel is used. In-app can never be off."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference"
    )
    in_app_min_severity = models.CharField(
        max_length=20,
        choices=[c for c in MinimumSeverity.choices if c[0] != "off"],
        default=Severity.INFO,
    )
    email_min_severity = models.CharField(
        max_length=20, choices=MinimumSeverity.choices, default=Severity.WARNING
    )

    def __str__(self) -> str:
        return f"Preferences of user {self.user_id}"


class Heartbeat(models.Model):
    """When a part of the alert engine last ran ("periodic" evaluation, "worker" task)."""

    name = models.CharField(max_length=40, primary_key=True)
    at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.name} at {self.at:%Y-%m-%d %H:%M:%S}"
