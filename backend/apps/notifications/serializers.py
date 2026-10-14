from typing import Any

from rest_framework import serializers

from apps.notifications.evaluators import EVALUATORS
from apps.notifications.models import (
    Alert,
    AlertRule,
    MinimumSeverity,
    Notification,
    NotificationPreference,
    Severity,
)
from apps.notifications.services.actions import can_acknowledge
from apps.organizations.models import Factory, Machine, ProductionLine, Role
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField


class AlertRuleSerializer(serializers.ModelSerializer):
    factory = ScopedPrimaryKeyRelatedField(queryset=Factory.objects.all(), factory_path="pk")
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.all(),
        factory_path="factory",
        required=False,
        allow_null=True,
    )
    machine = ScopedPrimaryKeyRelatedField(
        queryset=Machine.objects.all(),
        factory_path="line__factory",
        required=False,
        allow_null=True,
    )
    recipient_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=Role.choices), allow_empty=False
    )
    escalation_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=Role.choices), required=False
    )

    class Meta:
        model = AlertRule
        fields = [
            "id",
            "factory",
            "line",
            "machine",
            "name",
            "rule_type",
            "parameters",
            "severity",
            "is_enabled",
            "recipient_roles",
            "cooldown_minutes",
            "escalate_after_minutes",
            "escalation_roles",
            "active_outside_shifts",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance
        get = lambda name: attrs.get(name, getattr(instance, name, None))  # noqa: E731
        factory, line, machine = get("factory"), get("line"), get("machine")
        rule_type = get("rule_type")
        if instance is not None and "factory" in attrs and attrs["factory"] != instance.factory:
            raise serializers.ValidationError({"factory": "A rule cannot move to another factory."})
        if line is not None and line.factory_id != factory.pk:
            raise serializers.ValidationError({"line": "The line must belong to this factory."})
        if machine is not None:
            if machine.line.factory_id != factory.pk or (
                line is not None and machine.line_id != line.pk
            ):
                raise serializers.ValidationError(
                    {"machine": "The machine must be on this line/factory."}
                )
            if not EVALUATORS[rule_type].machine_scoped:
                raise serializers.ValidationError(
                    {"machine": "This rule type watches a whole line, not one machine."}
                )
        params = EVALUATORS[rule_type].parameters(
            data=attrs.get("parameters", getattr(instance, "parameters", {}) or {}),
            context={"factory": factory},
        )
        if not params.is_valid():
            raise serializers.ValidationError({"parameters": params.errors})
        unknown = set(attrs.get("parameters") or {}) - set(params.fields)
        if unknown:
            raise serializers.ValidationError(
                {"parameters": {name: ["Unknown parameter."] for name in sorted(unknown)}}
            )
        severity = get("severity")
        if (
            get("escalate_after_minutes") is not None
            and severity != Severity.INFO
            and not get("escalation_roles")
        ):
            raise serializers.ValidationError(
                {"escalation_roles": "Choose who to tell when the alert is not acknowledged."}
            )
        return attrs


class _Named(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class AlertSerializer(serializers.ModelSerializer):
    rule = serializers.SerializerMethodField()
    line = serializers.SerializerMethodField()
    machine = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    acknowledged_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    resolved_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    factory_timezone = serializers.CharField(source="factory.timezone", read_only=True)
    can_acknowledge = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            "id",
            "rule",
            "factory",
            "factory_timezone",
            "line",
            "machine",
            "subject",
            "severity",
            "status",
            "opened_at",
            "condition_since",
            "message_key",
            "message_values",
            "acknowledged_by",
            "acknowledged_at",
            "acknowledge_note",
            "resolved_at",
            "resolution",
            "resolved_by",
            "resolution_note",
            "escalated_at",
            "last_evaluated_at",
            "can_acknowledge",
        ]

    def get_can_acknowledge(self, obj: Alert) -> bool:
        request = self.context.get("request")
        return request is not None and can_acknowledge(request.user, obj)

    def get_rule(self, obj: Alert) -> dict[str, Any]:
        return {"id": obj.rule_id, "rule_type": obj.rule.rule_type, "name": obj.rule.name}

    def get_line(self, obj: Alert) -> dict[str, Any] | None:
        return {"id": obj.line_id, "name": obj.line.name} if obj.line else None

    def get_machine(self, obj: Alert) -> dict[str, Any] | None:
        return {"id": obj.machine_id, "name": obj.machine.name} if obj.machine else None

    def get_subject(self, obj: Alert) -> dict[str, Any]:
        return {"type": obj.subject_type, "id": obj.subject_id, "key": obj.subject_key}


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class NotificationSerializer(serializers.ModelSerializer):
    alert = AlertSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "alert", "channel", "reason", "status", "read_at", "created_at"]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    in_app_min_severity = serializers.ChoiceField(choices=Severity.choices)
    email_min_severity = serializers.ChoiceField(choices=MinimumSeverity.choices)

    class Meta:
        model = NotificationPreference
        fields = ["in_app_min_severity", "email_min_severity"]
