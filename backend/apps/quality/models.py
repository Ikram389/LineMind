"""Quality: the defect catalogue, inspection stations, inspection results and their reviews.

- `InspectionResult` is derived from a raw `quality_defect_detected` event (one row per
  defect, keyed by its event_id) and can always be rebuilt from it. Good bottles are
  never stored one by one: inspected volume comes from the station machine's counters.
- `QualityReview` is a human conclusion about a result, stored separately and never
  edited: every change is a new row, and the newest one is the result's current review.
"""

from typing import Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.organizations.models import Machine, Organization, ProductionLine
from apps.production.models import IngestedEvent


class Severity(models.TextChoices):
    MINOR = "minor", "Minor"
    MAJOR = "major", "Major"
    CRITICAL = "critical", "Critical"


class DefectType(models.Model):
    """The organization's defect catalogue (Q01-Q06 in docs/PRODUCT.md §6)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="defect_types", db_index=True
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="unique_defect_code_per_organization"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class StationSource(models.TextChoices):
    SIMULATOR = "simulator", "Simulator"
    VISION = "vision", "Vision system"


class InspectionStation(models.Model):
    """Where defects are detected: one machine of a line, checking some defect types."""

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="inspection_stations", db_index=True
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="inspection_stations", db_index=True
    )
    name = models.CharField(max_length=200)
    defect_types = models.ManyToManyField(DefectType, related_name="stations", blank=True)
    source = models.CharField(
        max_length=20, choices=StationSource.choices, default=StationSource.SIMULATOR
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["line_id", "machine__position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine"],
                condition=models.Q(is_active=True),
                name="one_active_station_per_machine",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Outcome(models.TextChoices):
    REJECTED = "rejected", "Rejected"


class InspectionResult(models.Model):
    """One detected defect, derived from its raw event. Rebuilt in place, never deleted."""

    event_id = models.UUIDField(unique=True)
    raw_event = models.OneToOneField(
        IngestedEvent, on_delete=models.PROTECT, related_name="inspection_result"
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="inspection_results", db_index=True
    )
    machine = models.ForeignKey(
        Machine, on_delete=models.PROTECT, related_name="inspection_results", db_index=True
    )
    station = models.ForeignKey(
        InspectionStation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="results",
        db_index=True,
        help_text="Empty when no active station is configured on the machine (see warnings).",
    )
    timestamp = models.DateTimeField(db_index=True)
    reported_code = models.CharField(
        max_length=50, blank=True, help_text="The defect code exactly as sent by the source."
    )
    defect_type = models.ForeignKey(
        DefectType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="results",
        db_index=True,
        help_text="Empty when the reported code is not in the catalogue (see warnings).",
    )
    confidence = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    source = models.CharField(max_length=20, default="event_api")
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.REJECTED)
    warnings = models.JSONField(default=list, blank=True)
    current_review = models.ForeignKey(
        "QualityReview",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="The newest review; empty while unreviewed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["timestamp", "id"]
        indexes = [
            models.Index(fields=["line", "timestamp"], name="result_line_time_idx"),
            models.Index(fields=["machine", "timestamp"], name="result_machine_time_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.reported_code or '?'} at {self.machine_id} {self.timestamp:%Y-%m-%d %H:%M:%S}"
        )


class Verdict(models.TextChoices):
    CONFIRMED = "confirmed", "Confirmed"
    FALSE_REJECT = "false_reject", "False reject"
    RECLASSIFIED = "reclassified", "Reclassified"


class ReviewImmutableError(Exception):
    pass


class QualityReview(models.Model):
    """A person's verdict on an inspection result. Never edited: a change is a new row."""

    result = models.ForeignKey(
        InspectionResult, on_delete=models.PROTECT, related_name="reviews", db_index=True
    )
    verdict = models.CharField(max_length=20, choices=Verdict.choices)
    corrected_defect_type = models.ForeignKey(
        DefectType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
        help_text="Set only when the verdict is 'reclassified'.",
    )
    comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quality_reviews"
    )
    reviewed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-reviewed_at", "-id"]

    def __str__(self) -> str:
        return f"{self.verdict} for result #{self.result_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ReviewImmutableError("Reviews are history and cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ReviewImmutableError("Reviews are history and cannot be deleted.")
