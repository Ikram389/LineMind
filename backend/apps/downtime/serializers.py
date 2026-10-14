"""Read serializers for downtime. Durations, losses and escalation come from services only.

The view passes `now` (one moment per request) and a cache of line speeds in the context.
"""

from datetime import datetime
from typing import Any

from django.db.models import Min
from rest_framework import serializers

from apps.downtime.models import (
    DowntimeClassification,
    DowntimeEvent,
    DowntimeReason,
    LineStopIncident,
)
from apps.downtime.services.analysis import clipped_micros, is_secondary_breakdown
from apps.downtime.services.durations import duration_seconds, exceeds_threshold
from apps.downtime.services.losses import incident_loss, machine_loss
from apps.organizations.models import Factory, Machine
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField

BULK_CLASSIFY_MAX = 200

FIRST_STOP_NOTE = (
    "The first observed stop is the earliest recorded breakdown in this cascade. "
    "It shows where the stop was first seen; it does not establish why it happened."
)


def machine_summary(machine: Machine | None) -> dict[str, Any] | None:
    if machine is None:
        return None
    return {
        "id": machine.id,
        "external_id": machine.external_id,
        "name": machine.name,
        "position": machine.position,
    }


class ContextMixin:
    context: dict[str, Any]

    @property
    def now(self) -> datetime:
        return self.context["now"]

    def line_speed(self, line_id: int) -> int:
        """Line nominal speed = slowest machine on the line (cached per request)."""
        cache: dict[int, int] = self.context.setdefault("line_speeds", {})
        if line_id not in cache:
            cache[line_id] = (
                Machine.objects.filter(line_id=line_id).aggregate(
                    speed=Min("nominal_speed_per_hour")
                )["speed"]
                or 0
            )
        return cache[line_id]


class DowntimeReasonSerializer(serializers.ModelSerializer):
    """Read and (for factory managers) write. `is_active=False` means archived."""

    factory = ScopedPrimaryKeyRelatedField(queryset=Factory.objects.all(), factory_path="pk")
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = DowntimeReason
        fields = [
            "id",
            "factory",
            "code",
            "name",
            "category",
            "is_active",
            "is_changeover",
            "in_use",
        ]
        read_only_fields = ["id", "in_use"]

    def get_in_use(self, obj: DowntimeReason) -> bool:
        return obj.classifications.exists()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if (
            self.instance is not None
            and "factory" in attrs
            and attrs["factory"] != self.instance.factory
        ):
            raise serializers.ValidationError(
                {"factory": "A reason cannot move to another factory."}
            )
        return attrs


class ClassificationSerializer(serializers.ModelSerializer):
    reason = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = DowntimeClassification
        fields = ["id", "reason", "comment", "source", "created_by", "created_at"]
        read_only_fields = fields

    def get_reason(self, obj: DowntimeClassification) -> dict[str, Any]:
        reason = obj.reason
        return {
            "id": reason.id,
            "code": reason.code,
            "name": reason.name,
            "category": reason.category,
        }

    def get_created_by(self, obj: DowntimeClassification) -> str | None:
        return obj.created_by.email if obj.created_by else None


class ClassificationInputSerializer(serializers.Serializer):
    reason = serializers.IntegerField()
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class BulkClassificationInputSerializer(ClassificationInputSerializer):
    event_ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=1, max_length=BULK_CLASSIFY_MAX
    )


def role_in_incident(event: DowntimeEvent) -> str | None:
    """first_observed_stop, secondary_breakdown (needs its own reason) or consequence."""
    if event.incident_id is None:
        return None
    if event.is_first_stop:
        return "first_observed_stop"
    if is_secondary_breakdown(event):
        return "secondary_breakdown"
    return "consequence"


class DowntimeEventSerializer(ContextMixin, serializers.ModelSerializer):
    machine = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    is_ongoing = serializers.SerializerMethodField()
    exceeds_escalation_threshold = serializers.SerializerMethodField()
    estimated_loss = serializers.SerializerMethodField()
    classification = serializers.SerializerMethodField()
    role_in_incident = serializers.SerializerMethodField()
    clipped_duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = DowntimeEvent
        fields = [
            "id",
            "machine",
            "line",
            "category",
            "state",
            "started_at",
            "ended_at",
            "duration_seconds",
            "is_ongoing",
            "alarm_code",
            "is_first_stop",
            "incident",
            "exceeds_escalation_threshold",
            "estimated_loss",
            "classification",
            "role_in_incident",
            "clipped_duration_seconds",
        ]
        read_only_fields = fields

    def get_role_in_incident(self, obj: DowntimeEvent) -> str | None:
        return role_in_incident(obj)

    def get_clipped_duration_seconds(self, obj: DowntimeEvent) -> float | None:
        """Duration inside the requested ?start=&end= range (null without a range)."""
        start, end = self.context.get("range", (None, None))
        if start is None or end is None:
            return None
        return round(
            clipped_micros(obj.started_at, obj.ended_at, start, min(end, self.now)) / 1e6, 3
        )

    def get_machine(self, obj: DowntimeEvent) -> dict[str, Any] | None:
        return machine_summary(obj.machine)

    def get_duration_seconds(self, obj: DowntimeEvent) -> float:
        return round(duration_seconds(obj.started_at, obj.ended_at, self.now), 3)

    def get_is_ongoing(self, obj: DowntimeEvent) -> bool:
        return obj.ended_at is None

    def get_exceeds_escalation_threshold(self, obj: DowntimeEvent) -> bool:
        threshold = obj.line.factory.escalation_after_seconds
        return exceeds_threshold(obj.started_at, obj.ended_at, threshold, self.now)

    def get_estimated_loss(self, obj: DowntimeEvent) -> dict[str, Any]:
        return machine_loss(
            obj.started_at, obj.ended_at, obj.machine.nominal_speed_per_hour, self.now
        )

    def get_classification(self, obj: DowntimeEvent) -> dict[str, Any] | None:
        if obj.current_classification is None:
            return None
        return ClassificationSerializer(obj.current_classification).data


class IncidentSerializer(ContextMixin, serializers.ModelSerializer):
    line = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    is_ongoing = serializers.SerializerMethodField()
    first_observed_stop = serializers.SerializerMethodField()
    exceeds_escalation_threshold = serializers.SerializerMethodField()
    estimated_loss = serializers.SerializerMethodField()
    event_count = serializers.SerializerMethodField()

    class Meta:
        model = LineStopIncident
        fields = [
            "id",
            "line",
            "started_at",
            "ended_at",
            "duration_seconds",
            "is_ongoing",
            "origin",
            "first_observed_stop",
            "exceeds_escalation_threshold",
            "estimated_loss",
            "event_count",
        ]
        read_only_fields = fields

    def members(self, obj: LineStopIncident) -> list[DowntimeEvent]:
        return sorted(obj.events.all(), key=lambda e: (e.started_at, e.machine.position, e.pk))

    def get_line(self, obj: LineStopIncident) -> dict[str, Any]:
        return {"id": obj.line_id, "name": obj.line.name}

    def get_duration_seconds(self, obj: LineStopIncident) -> float:
        return round(duration_seconds(obj.started_at, obj.ended_at, self.now), 3)

    def get_is_ongoing(self, obj: LineStopIncident) -> bool:
        return obj.ended_at is None

    def get_first_observed_stop(self, obj: LineStopIncident) -> dict[str, Any]:
        firsts = [e for e in self.members(obj) if e.is_first_stop]
        return {
            "machine": machine_summary(obj.first_machine),
            "simultaneous": [machine_summary(e.machine) for e in firsts]
            if obj.has_simultaneous_first_stops
            else [],
            "note": FIRST_STOP_NOTE,
        }

    def get_exceeds_escalation_threshold(self, obj: LineStopIncident) -> bool:
        threshold = obj.line.factory.escalation_after_seconds
        return exceeds_threshold(obj.started_at, obj.ended_at, threshold, self.now)

    def get_estimated_loss(self, obj: LineStopIncident) -> dict[str, Any]:
        return incident_loss(obj.started_at, obj.ended_at, self.line_speed(obj.line_id), self.now)

    def get_event_count(self, obj: LineStopIncident) -> int:
        return len(obj.events.all())


class IncidentDetailSerializer(IncidentSerializer):
    events = serializers.SerializerMethodField()

    class Meta(IncidentSerializer.Meta):
        fields = [*IncidentSerializer.Meta.fields, "events"]
        read_only_fields = fields

    def get_events(self, obj: LineStopIncident) -> list[dict[str, Any]]:
        return IncidentMemberSerializer(
            self.members(obj), many=True, context={**self.context, "incident": obj}
        ).data


class IncidentMemberSerializer(DowntimeEventSerializer):
    """A member of an incident's cascade: its delay after the first stop and its history."""

    delay_seconds = serializers.SerializerMethodField()
    classifications = serializers.SerializerMethodField()

    class Meta(DowntimeEventSerializer.Meta):
        fields = [*DowntimeEventSerializer.Meta.fields, "delay_seconds", "classifications"]
        read_only_fields = fields

    def get_delay_seconds(self, obj: DowntimeEvent) -> float:
        incident: LineStopIncident = self.context["incident"]
        return round((obj.started_at - incident.started_at).total_seconds(), 3)

    def get_classifications(self, obj: DowntimeEvent) -> list[dict[str, Any]]:
        history = obj.classifications.select_related("reason", "created_by")
        return ClassificationSerializer(history, many=True).data
