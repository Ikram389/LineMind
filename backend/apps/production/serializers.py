from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from apps.organizations.models import Machine
from apps.production.event_types import EventType
from apps.production.models import MachineStateEvent, ProductionEvent


class AwareDateTimeField(serializers.Field):
    """ISO 8601 date-time that must include a timezone; returned in UTC.

    DRF's DateTimeField silently assumes a timezone for naive values; for machine
    events that would hide clock problems, so naive values are rejected.
    """

    default_error_messages = {
        "invalid": "Must be an ISO 8601 date-time, e.g. '2026-10-12T10:05:00Z'.",
        "naive": "Must include a timezone (e.g. 'Z' or '+01:00').",
    }

    def to_internal_value(self, data: Any) -> datetime:
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            value = parse_datetime(data)
        except ValueError:
            value = None
        if value is None:
            self.fail("invalid")
        if value.tzinfo is None or value.utcoffset() is None:
            self.fail("naive")
        return value.astimezone(UTC)

    def to_representation(self, value: datetime) -> str:
        return value.isoformat()


class NonNegativeIntegerField(serializers.Field):
    """A JSON integer >= 0. Strings, floats and booleans are rejected."""

    default_error_messages = {
        "invalid": "Must be an integer.",
        "negative": "Must be zero or greater.",
    }

    def to_internal_value(self, data: Any) -> int:
        if type(data) is not int:  # bool is a subclass of int, so check the exact type
            self.fail("invalid")
        if data < 0:
            self.fail("negative")
        return data

    def to_representation(self, value: int) -> int:
        return value


class IncomingEventSerializer(serializers.Serializer):
    """Validates one incoming event. Needs `line` and `now` in the context."""

    event_id = serializers.UUIDField()
    machine_external_id = serializers.CharField(max_length=64)
    event_type = serializers.ChoiceField(choices=EventType.choices)
    timestamp = AwareDateTimeField()
    alarm_code = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    count = NonNegativeIntegerField(required=False, allow_null=True)
    rejected = NonNegativeIntegerField(required=False, allow_null=True)
    payload = serializers.JSONField(required=False)

    def validate_machine_external_id(self, value: str) -> Machine:
        machine = Machine.objects.filter(line=self.context["line"], external_id=value).first()
        if machine is None:
            # Same message whether the machine doesn't exist or is on another line.
            raise serializers.ValidationError(f"No machine '{value}' on this API key's line.")
        return machine

    def validate_timestamp(self, value: datetime) -> datetime:
        latest_allowed = self.context["now"] + timedelta(seconds=settings.EVENT_MAX_FUTURE_SECONDS)
        if value > latest_allowed:
            raise serializers.ValidationError(
                f"Is more than {settings.EVENT_MAX_FUTURE_SECONDS} seconds in the future. "
                "Check the sender's clock."
            )
        return value

    def validate_payload(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["event_type"] == EventType.PRODUCTION_COUNT_UPDATED and attrs.get("count") is None:
            raise serializers.ValidationError(
                {"count": "Is required for production_count_updated."}
            )
        if attrs.get("alarm_code") == "":
            attrs["alarm_code"] = None
        # validate_machine_external_id turned the external id into a Machine.
        attrs["machine"] = attrs.pop("machine_external_id")
        return attrs


class MachineStateEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineStateEvent
        fields = [
            "id",
            "event_id",
            "machine",
            "state",
            "timestamp",
            "alarm_code",
            "source",
            "received_at",
        ]
        read_only_fields = fields


class ProductionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionEvent
        fields = ["id", "event_id", "machine", "timestamp", "count", "rejected", "received_at"]
        read_only_fields = fields
