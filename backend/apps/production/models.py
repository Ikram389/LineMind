"""Line API keys, raw machine observations, shifts, products and production orders.

IngestedEvent, MachineStateEvent and ProductionEvent are observations
(CLAUDE.md rule 2): application code never edits or deletes them.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.organizations.models import Factory, Machine, Organization, ProductionLine
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


# --- Shifts ----------------------------------------------------------------------------


def all_days() -> list[int]:
    return [0, 1, 2, 3, 4, 5, 6]


def validate_days_of_week(value: Any) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(type(day) is not int or not 0 <= day <= 6 for day in value)
        or len(set(value)) != len(value)
    ):
        raise ValidationError("Must be a non-empty list of distinct weekdays 0-6 (Monday = 0).")


class Shift(models.Model):
    """A recurring shift in the factory's local time. Occurrences are computed, not stored.

    end_time <= start_time means the shift crosses midnight (e.g. 22:00-06:00).
    A shift belongs to the weekday on which it starts.
    """

    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="shifts", db_index=True
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField(help_text="Local time in the factory timezone.")
    end_time = models.TimeField(help_text="Local time; earlier than start = next day.")
    days_of_week = models.JSONField(
        default=all_days,
        validators=[validate_days_of_week],
        help_text="Weekdays the shift starts on, Monday = 0 ... Sunday = 6.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["factory__id", "start_time", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["factory", "name"], name="unique_shift_name_per_factory"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"


class ShiftBreak(models.Model):
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="breaks", db_index=True)
    name = models.CharField(max_length=100, default="Break")
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shift__id", "start_time"]

    def __str__(self) -> str:
        return f"{self.name} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


# --- Products and orders ---------------------------------------------------------------

CYCLE_TIME_VALIDATORS = [MinValueValidator(Decimal("0.001"))]


class Product(models.Model):
    """A product of the organization (shared by all its factories)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="products", db_index=True
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64)
    ideal_cycle_time_seconds = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=CYCLE_TIME_VALIDATORS,
        help_text="Fastest possible time to produce one unit, in seconds.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku"], name="unique_sku_per_organization"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"


class ProductLineCycleTime(models.Model):
    """A line-specific ideal cycle time that overrides the product's default."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="line_cycle_times", db_index=True
    )
    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.CASCADE,
        related_name="product_cycle_times",
        db_index=True,
    )
    ideal_cycle_time_seconds = models.DecimalField(
        max_digits=10, decimal_places=3, validators=CYCLE_TIME_VALIDATORS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["line__id", "product__id"]
        constraints = [
            models.UniqueConstraint(fields=["product", "line"], name="unique_cycle_time_per_line")
        ]

    def __str__(self) -> str:
        return f"{self.product} on {self.line}: {self.ideal_cycle_time_seconds}s"


class OrderStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class ProductionOrder(models.Model):
    """Which product a line makes, and when.

    The order covers [actual_start or scheduled_start, actual_end or scheduled_end).
    Cancelled orders never count. Orders on one line may not overlap.
    """

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="production_orders", db_index=True
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="production_orders", db_index=True
    )
    planned_quantity = models.PositiveIntegerField()
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.PLANNED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["line__id", "scheduled_start"]
        indexes = [
            models.Index(fields=["line", "scheduled_start"], name="order_line_start_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scheduled_end__gt=models.F("scheduled_start")),
                name="order_scheduled_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} on {self.line} from {self.scheduled_start:%Y-%m-%d %H:%M}"

    @property
    def effective_start(self) -> Any:
        return self.actual_start or self.scheduled_start

    @property
    def effective_end(self) -> Any:
        return self.actual_end or self.scheduled_end
