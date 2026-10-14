"""Lightweight maintenance: actions, their work log, links to evidence, confirmed diagnoses.

Observations (stops, incidents, alarms, defects) are only *linked to*, never changed.
What people conclude is stored here, separately: the work log, and the confirmed
diagnosis (which may also be applied to the linked stops as new classifications).
Not a CMMS: no spare-parts inventory, purchasing or preventive schedules.
"""

from typing import Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.downtime.models import DowntimeEvent, DowntimeReason, LineStopIncident
from apps.notifications.models import Alert
from apps.organizations.models import Factory, Machine, ProductionLine
from apps.quality.models import InspectionResult


class ActionType(models.TextChoices):
    CORRECTIVE = "corrective", "Corrective"
    INSPECTION = "inspection", "Inspection"
    IMPROVEMENT = "improvement", "Improvement"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Status(models.TextChoices):
    REQUESTED = "requested", "Requested"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    WAITING = "waiting", "Waiting"
    DONE = "done", "Done"
    VERIFIED = "verified", "Verified"
    CANCELLED = "cancelled", "Cancelled"


OPEN_STATUSES = (Status.REQUESTED, Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING)


class VerificationResult(models.TextChoices):
    EFFECTIVE = "effective", "Effective"
    NOT_EFFECTIVE = "not_effective", "Not effective"


class ImmutableHistoryError(Exception):
    pass


class _AppendOnly(models.Model):
    """History rows: created once, never edited or deleted."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ImmutableHistoryError("History rows cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ImmutableHistoryError("History rows cannot be deleted.")


class MaintenanceAction(models.Model):
    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="maintenance_actions", db_index=True
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="maintenance_actions", db_index=True
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="maintenance_actions", db_index=True
    )
    title = models.CharField(max_length=200)
    problem = models.TextField(blank=True, help_text="The problem as reported.")
    action_type = models.CharField(
        max_length=20, choices=ActionType.choices, default=ActionType.CORRECTIVE
    )
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_actions"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_actions",
    )
    due_date = models.DateField(
        null=True, blank=True, help_text="Overdue after the end of this day (factory time)."
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    fixed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the repair took effect (default: completion). Anchors the before/after "
        "comparison.",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_actions",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_result = models.CharField(
        max_length=20, choices=VerificationResult.choices, blank=True
    )
    verification_note = models.TextField(blank=True)
    effectiveness_window_days = models.PositiveIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(90)]
    )
    min_after_run_hours = models.PositiveIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(2000)]
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "due_date"], name="action_status_due_idx")]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"


class MaintenanceStatusChange(_AppendOnly):
    action = models.ForeignKey(
        MaintenanceAction, on_delete=models.CASCADE, related_name="status_changes"
    )
    from_status = models.CharField(max_length=20, choices=Status.choices)
    to_status = models.CharField(max_length=20, choices=Status.choices)
    event = models.CharField(max_length=20, help_text="assign, start, reopen, verify…")
    note = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return f"#{self.action_id} {self.from_status} -> {self.to_status}"


class EntryKind(models.TextChoices):
    COMMENT = "comment", "Comment"
    DIAGNOSIS = "diagnosis", "Diagnosis"
    REPAIR = "repair", "Repair done"


class MaintenanceEntry(_AppendOnly):
    """The work log: what was found and done. Parts are free text (no inventory)."""

    action = models.ForeignKey(MaintenanceAction, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=20, choices=EntryKind.choices, default=EntryKind.COMMENT)
    text = models.TextField()
    time_spent_minutes = models.PositiveIntegerField(default=0)
    parts = models.JSONField(default=list, blank=True, help_text='[{"name": "...", "quantity": 1}]')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.kind} on #{self.action_id}"


class LinkKind(models.TextChoices):
    DOWNTIME_EVENT = "downtime_event", "Stop"
    INCIDENT = "incident", "Line stop incident"
    ALERT = "alert", "Alert"
    INSPECTION_RESULT = "inspection_result", "Defect"
    SIGNATURE = "signature", "Problem signature"


class ActionLink(models.Model):
    """Evidence for an action. Exactly one target per row, depending on its kind.

    A "signature" is a recurring problem: machine + downtime reason, or machine + alarm
    code (as in step 8's recurring stops). The before/after comparison uses it.
    """

    action = models.ForeignKey(MaintenanceAction, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=30, choices=LinkKind.choices)
    downtime_event = models.ForeignKey(
        DowntimeEvent, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    incident = models.ForeignKey(
        LineStopIncident, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    alert = models.ForeignKey(
        Alert, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    inspection_result = models.ForeignKey(
        InspectionResult, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    signature_machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    signature_reason = models.ForeignKey(
        DowntimeReason, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    signature_alarm_code = models.CharField(max_length=50, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                name="link_has_exactly_its_target",
                condition=(
                    models.Q(
                        kind="downtime_event",
                        downtime_event__isnull=False,
                        incident__isnull=True,
                        alert__isnull=True,
                        inspection_result__isnull=True,
                        signature_machine__isnull=True,
                    )
                    | models.Q(
                        kind="incident",
                        incident__isnull=False,
                        downtime_event__isnull=True,
                        alert__isnull=True,
                        inspection_result__isnull=True,
                        signature_machine__isnull=True,
                    )
                    | models.Q(
                        kind="alert",
                        alert__isnull=False,
                        downtime_event__isnull=True,
                        incident__isnull=True,
                        inspection_result__isnull=True,
                        signature_machine__isnull=True,
                    )
                    | models.Q(
                        kind="inspection_result",
                        inspection_result__isnull=False,
                        downtime_event__isnull=True,
                        incident__isnull=True,
                        alert__isnull=True,
                        signature_machine__isnull=True,
                    )
                    | (
                        models.Q(
                            kind="signature",
                            signature_machine__isnull=False,
                            downtime_event__isnull=True,
                            incident__isnull=True,
                            alert__isnull=True,
                            inspection_result__isnull=True,
                        )
                        & (
                            models.Q(signature_reason__isnull=False, signature_alarm_code="")
                            | (
                                models.Q(signature_reason__isnull=True)
                                & ~models.Q(signature_alarm_code="")
                            )
                        )
                    )
                ),
            ),
            models.UniqueConstraint(
                fields=["action"],
                condition=models.Q(kind="signature"),
                name="one_signature_per_action",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} for #{self.action_id}"


class MaintenanceDiagnosis(_AppendOnly):
    """The confirmed diagnosis (a conclusion). The newest one is current."""

    action = models.ForeignKey(
        MaintenanceAction, on_delete=models.CASCADE, related_name="diagnoses"
    )
    reason = models.ForeignKey(DowntimeReason, on_delete=models.PROTECT, related_name="+")
    text = models.TextField(blank=True)
    applied_to_stops = models.BooleanField(default=False)
    replace_other_reasons = models.BooleanField(default=False)
    applied_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.reason_id} for #{self.action_id}"
