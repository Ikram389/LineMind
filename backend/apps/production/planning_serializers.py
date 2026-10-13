"""Serializers for shifts, breaks, products, cycle-time overrides and production orders."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers

from apps.organizations.models import Factory, ProductionLine
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField
from apps.organizations.tenancy import get_membership, scope_to_organization
from apps.production.models import (
    OrderStatus,
    Product,
    ProductionOrder,
    ProductLineCycleTime,
    Shift,
    ShiftBreak,
)
from apps.production.services.orders import overlapping_orders
from apps.production.services.shifts import break_fits_in_shift


class OrganizationScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Only accepts objects of the requesting user's organization."""

    def get_queryset(self) -> QuerySet:
        request = self.context.get("request")
        if request is None:
            return super().get_queryset().none()
        return scope_to_organization(super().get_queryset(), request.user)


class ShiftBreakSerializer(serializers.ModelSerializer):
    shift = ScopedPrimaryKeyRelatedField(queryset=Shift.objects.all(), factory_path="factory")

    class Meta:
        model = ShiftBreak
        fields = ["id", "shift", "name", "start_time", "end_time", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        shift = attrs.get("shift") or self.instance.shift
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start == end:
            raise serializers.ValidationError({"end_time": "A break cannot have zero length."})
        if not break_fits_in_shift(shift.start_time, shift.end_time, start, end):
            raise serializers.ValidationError("The break must lie inside its shift.")
        return attrs


class BreakSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftBreak
        fields = ["id", "name", "start_time", "end_time"]
        read_only_fields = fields


class ShiftSerializer(serializers.ModelSerializer):
    factory = ScopedPrimaryKeyRelatedField(queryset=Factory.objects.all(), factory_path="pk")
    breaks = BreakSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Shift
        fields = [
            "id",
            "factory",
            "name",
            "start_time",
            "end_time",
            "days_of_week",
            "is_active",
            "breaks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start == end:
            raise serializers.ValidationError({"end_time": "A shift cannot have zero length."})
        if self.instance is not None:
            for shift_break in self.instance.breaks.all():
                if not break_fits_in_shift(
                    start, end, shift_break.start_time, shift_break.end_time
                ):
                    raise serializers.ValidationError(
                        f"Break '{shift_break.name}' would no longer fit in the shift."
                    )
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "organization",
            "name",
            "sku",
            "ideal_cycle_time_seconds",
            "created_at",
            "updated_at",
        ]
        # The organization always comes from the user's membership.
        read_only_fields = ["organization", "created_at", "updated_at"]

    def validate_sku(self, value: str) -> str:
        membership = get_membership(self.context["request"].user)
        duplicates = Product.objects.filter(organization=membership.organization, sku=value)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value


class ProductCycleTimeSerializer(serializers.ModelSerializer):
    product = OrganizationScopedPrimaryKeyRelatedField(queryset=Product.objects.all())
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.all(), factory_path="factory"
    )

    class Meta:
        model = ProductLineCycleTime
        fields = ["id", "product", "line", "ideal_cycle_time_seconds", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class ProductionOrderSerializer(serializers.ModelSerializer):
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.select_related("factory"), factory_path="factory"
    )
    product = OrganizationScopedPrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = ProductionOrder
        fields = [
            "id",
            "line",
            "product",
            "planned_quantity",
            "scheduled_start",
            "scheduled_end",
            "actual_start",
            "actual_end",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        def value(name: str) -> Any:
            return attrs.get(name, getattr(self.instance, name, None))

        line, product = value("line"), value("product")
        if product.organization_id != line.factory.organization_id:
            raise serializers.ValidationError(
                {"product": "Must belong to the line's organization."}
            )
        if value("scheduled_end") <= value("scheduled_start"):
            raise serializers.ValidationError({"scheduled_end": "Must be after scheduled_start."})
        actual_start, actual_end = value("actual_start"), value("actual_end")
        if actual_start and actual_end and actual_end <= actual_start:
            raise serializers.ValidationError({"actual_end": "Must be after actual_start."})

        if value("status") != OrderStatus.CANCELLED:
            start = actual_start or value("scheduled_start")
            end = actual_end or value("scheduled_end")
            clash = overlapping_orders(
                line, start, end, exclude_pk=self.instance.pk if self.instance else None
            ).first()
            if clash is not None:
                raise serializers.ValidationError(
                    f"Overlaps production order #{clash.pk} on this line "
                    f"({clash.effective_from:%Y-%m-%d %H:%M} - "
                    f"{clash.effective_to:%Y-%m-%d %H:%M})."
                )
        return attrs
