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
from apps.downtime.services.durations import duration_seconds, exceeds_threshold
from apps.downtime.services.losses import incident_loss, machine_loss
from apps.organizations.models import Machine

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
    class Meta:
        model = DowntimeReason
        fields = ["id", "factory", "code", "name", "category", "is_active"]
        read_only_fields = fields


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


class DowntimeEventSerializer(ContextMixin, serializers.ModelSerializer):
    machine = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    is_ongoing = serializers.SerializerMethodField()
    exceeds_escalation_threshold = serializers.SerializerMethodField()
    estimated_loss = serializers.SerializerMethodField()
    classification = serializers.SerializerMethodField()

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
        ]
        read_only_fields = fields

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
        return DowntimeEventSerializer(self.members(obj), many=True, context=self.context).data
