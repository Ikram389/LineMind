"""Downtime: derived stop records, line stop incidents, and their classification.

DowntimeEvent and LineStopIncident are *conclusions* derived from the raw
MachineStateEvent / IngestedEvent observations (services/derivation.py). They
can be recomputed at any time. Classifications are separate, append-only rows
written by people (and later AI), so recomputing never loses them.
"""

from typing import Any

from django.conf import settings
from django.db import models

from apps.organizations.models import Factory, Machine, ProductionLine


class DowntimeCategory(models.TextChoices):
    BREAKDOWN = "breakdown", "Breakdown"  # machine state "stopped"
    BLOCKED = "blocked", "Blocked"
    STARVED = "starved", "Starved"
    PLANNED = "planned", "Planned stop"
    NO_DATA = "no_data", "No data"  # "unknown" state or telemetry gap


# Categories that can be part of a line stop incident (a cascade).
INCIDENT_CATEGORIES = frozenset(
    {DowntimeCategory.BREAKDOWN, DowntimeCategory.BLOCKED, DowntimeCategory.STARVED}
)


class StartKind(models.TextChoices):
    """What kind of raw event starts a downtime interval (part of its stable identity)."""

    TRANSITION = "transition", "State transition"  # the state event itself
    GAP = "gap", "Telemetry gap"  # the last event before a silence
    RESUME = "resume", "Resume after gap"  # the first event after a silence


class IncidentOrigin(models.TextChoices):
    MACHINE_STOP = "machine_stop", "Machine stop"
    UNKNOWN = "unknown", "Unknown"


class LineStopIncident(models.Model):
    """A cascade of stops on one line, with its first observed stop (a clue, not proof)."""

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="stop_incidents", db_index=True
    )
    key = models.CharField(
        max_length=80, unique=True, help_text="Identity of the earliest member downtime event."
    )
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=20, choices=IncidentOrigin.choices)
    first_machine = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="first_stop_incidents",
    )
    has_simultaneous_first_stops = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [models.Index(fields=["line", "started_at"], name="incident_line_start_idx")]

    def __str__(self) -> str:
        return f"Incident on {self.line} at {self.started_at:%Y-%m-%d %H:%M:%S}"


class DowntimeEvent(models.Model):
    """One non-running interval of one machine, derived from state transitions or gaps."""

    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="downtime_events", db_index=True
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="downtime_events", db_index=True
    )
    start_kind = models.CharField(max_length=20, choices=StartKind.choices)
    start_event_id = models.UUIDField(help_text="Raw event whose timestamp starts this interval.")
    state = models.CharField(max_length=20, help_text="Raw machine state during the interval.")
    category = models.CharField(max_length=20, choices=DowntimeCategory.choices)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Empty while ongoing.")
    alarm_code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    incident = models.ForeignKey(
        LineStopIncident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    is_first_stop = models.BooleanField(
        default=False, help_text="First observed stop of its incident (a clue, not proof)."
    )
    is_obsolete = models.BooleanField(
        default=False,
        help_text="No longer produced by the derivation but kept because it was classified.",
    )
    current_classification = models.ForeignKey(
        "DowntimeClassification",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["started_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["start_kind", "start_event_id"], name="unique_downtime_identity"
            ),
        ]
        indexes = [
            models.Index(fields=["machine", "started_at"], name="downtime_machine_start_idx"),
            models.Index(fields=["line", "started_at"], name="downtime_line_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.machine.external_id} {self.category} @ {self.started_at:%Y-%m-%d %H:%M:%S}"

    @property
    def identity(self) -> str:
        return f"{self.start_kind}:{self.start_event_id}"


class ReasonCategory(models.TextChoices):
    MECHANICAL = "mechanical", "Mechanical"
    ELECTRICAL = "electrical", "Electrical"
    MATERIAL = "material", "Material"
    QUALITY = "quality", "Quality"
    ORGANIZATIONAL = "organizational", "Organizational"
    PLANNED = "planned", "Planned"


class DowntimeReason(models.Model):
    """A factory's catalogue of downtime reasons."""

    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="downtime_reasons", db_index=True
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=ReasonCategory.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["factory", "code"], name="unique_reason_code_per_factory"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class ClassificationSource(models.TextChoices):
    OPERATOR = "operator", "Operator"
    SUPERVISOR = "supervisor", "Supervisor"
    AI = "ai", "AI suggestion"


class ClassificationImmutableError(Exception):
    pass


class DowntimeClassification(models.Model):
    """A reason given to a downtime event. Every change is a new row; the latest is current."""

    downtime_event = models.ForeignKey(
        DowntimeEvent, on_delete=models.PROTECT, related_name="classifications", db_index=True
    )
    reason = models.ForeignKey(
        DowntimeReason, on_delete=models.PROTECT, related_name="classifications"
    )
    comment = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=ClassificationSource.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="downtime_classifications",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.reason.code} for downtime #{self.downtime_event_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ClassificationImmutableError("Classifications are history and cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ClassificationImmutableError("Classifications are history and cannot be deleted.")
