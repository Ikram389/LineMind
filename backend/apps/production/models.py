"""Line API keys and raw machine observations.

IngestedEvent, MachineStateEvent and ProductionEvent are observations
(CLAUDE.md rule 2): application code never edits or deletes them.
"""

from typing import Any

from django.core.validators import MinValueValidator
from django.db import models

from apps.organizations.models import Machine, ProductionLine
from apps.production.event_types import EventType, MachineState


class ImmutableObservationError(Exception):
    """Raised when code tries to change or delete a stored observation."""


class ImmutableModel(models.Model):
    """Rows can be inserted once and never updated or deleted through the ORM instance."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ImmutableObservationError(
                f"{type(self).__name__} is an immutable observation and cannot be changed."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ImmutableObservationError(
            f"{type(self).__name__} is an immutable observation and cannot be deleted."
        )


class LineApiKey(models.Model):
    """Lets a machine/simulator send events for one production line.

    Only a SHA-256 hash of the key is stored. See services/api_keys.py.
    """

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="api_keys", db_index=True
    )
    name = models.CharField(max_length=100, help_text="What uses this key, e.g. 'Simulator'.")
    prefix = models.CharField(max_length=16, unique=True, help_text="Public part used for lookup.")
    key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["line__id", "name"]
        verbose_name = "line API key"

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…) for {self.line}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class IngestedEvent(ImmutableModel):
    """Every accepted event, exactly as received."""

    event_id = models.UUIDField(unique=True)
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="ingested_events", db_index=True
    )
    api_key = models.ForeignKey(
        LineApiKey, on_delete=models.PROTECT, related_name="ingested_events", db_index=True
    )
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    timestamp = models.DateTimeField(help_text="When it happened at the machine (UTC).")
    received_at = models.DateTimeField(help_text="When the backend received it (UTC).")
    alarm_code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    count = models.BigIntegerField(null=True, blank=True)
    rejected = models.BigIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["timestamp", "id"]
        indexes = [
            models.Index(fields=["machine", "timestamp"], name="ingested_machine_ts_idx"),
            models.Index(fields=["received_at"], name="ingested_received_at_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.machine.external_id} @ {self.timestamp.isoformat()}"


class MachineStateEvent(ImmutableModel):
    """A state transition at a point in time. Durations are derived later (build step 5)."""

    SOURCE_EVENT_API = "event_api"

    event_id = models.UUIDField(unique=True)
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="state_events", db_index=True
    )
    state = models.CharField(max_length=20, choices=MachineState.choices)
    timestamp = models.DateTimeField()
    alarm_code = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    source = models.CharField(max_length=30, default=SOURCE_EVENT_API)
    received_at = models.DateTimeField()

    class Meta:
        ordering = ["timestamp", "id"]
        indexes = [
            models.Index(fields=["machine", "timestamp"], name="state_machine_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.machine.external_id} → {self.state} @ {self.timestamp.isoformat()}"


class ProductionEvent(ImmutableModel):
    """A production counter reading, stored exactly as reported."""

    event_id = models.UUIDField(unique=True)
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="production_events", db_index=True
    )
    timestamp = models.DateTimeField()
    count = models.BigIntegerField(validators=[MinValueValidator(0)])
    rejected = models.BigIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Empty means the machine did not report rejects (not zero).",
    )
    received_at = models.DateTimeField()

    class Meta:
        ordering = ["timestamp", "id"]
        indexes = [
            models.Index(fields=["machine", "timestamp"], name="production_machine_ts_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(count__gte=0), name="production_count_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(rejected__isnull=True) | models.Q(rejected__gte=0),
                name="production_rejected_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.machine.external_id} count={self.count} @ {self.timestamp.isoformat()}"
