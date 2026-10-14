from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers

from apps.organizations.models import Factory, Machine, ProductionLine
from apps.organizations.oee_settings import with_defaults
from apps.organizations.tenancy import get_membership, scope_to_user


class ScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A foreign-key field that only accepts objects the requesting user may access.

    An ID from another organization (or a non-permitted factory) is rejected
    with the normal "does not exist" error.
    """

    def __init__(self, *, factory_path: str, **kwargs: Any) -> None:
        self.factory_path = factory_path
        super().__init__(**kwargs)

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        request = self.context.get("request")
        if request is None:
            return queryset.none()
        return scope_to_user(queryset, request.user, self.factory_path)


class FactorySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Factory
        fields = ["id", "name", "timezone"]


class FactorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Factory
        fields = [
            "id",
            "organization",
            "name",
            "timezone",
            "oee_settings",
            "stale_after_seconds",
            "escalation_after_seconds",
            "recurring_stop_threshold",
            "quality_incident_window_minutes",
            "created_at",
            "updated_at",
        ]
        # The organization always comes from the user's membership, never from the request.
        read_only_fields = ["organization", "created_at", "updated_at"]

    def validate_oee_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        return with_defaults(value)

    def validate_name(self, value: str) -> str:
        if self.instance is not None:
            organization_id = self.instance.organization_id
        else:
            membership = get_membership(self.context["request"].user)
            organization_id = membership.organization_id if membership else None
        duplicates = Factory.objects.filter(organization_id=organization_id, name=value)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                "A factory with this name already exists in your organization."
            )
        return value


class ProductionLineSerializer(serializers.ModelSerializer):
    factory = ScopedPrimaryKeyRelatedField(queryset=Factory.objects.all(), factory_path="pk")
    counting_machine = ScopedPrimaryKeyRelatedField(
        queryset=Machine.objects.all(),
        factory_path="line__factory",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ProductionLine
        fields = ["id", "factory", "name", "counting_machine", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        machine = attrs.get("counting_machine")
        if machine is not None and (self.instance is None or machine.line_id != self.instance.pk):
            raise serializers.ValidationError(
                {"counting_machine": "Must be a machine of this line."}
            )
        return attrs


class MachineSerializer(serializers.ModelSerializer):
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.all(), factory_path="factory"
    )

    class Meta:
        model = Machine
        fields = [
            "id",
            "line",
            "external_id",
            "name",
            "machine_type",
            "position",
            "nominal_speed_per_hour",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
