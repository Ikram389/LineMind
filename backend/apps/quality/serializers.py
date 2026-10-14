from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers

from apps.organizations.models import Machine, ProductionLine
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField
from apps.organizations.tenancy import scope_to_organization
from apps.quality.models import (
    DefectType,
    InspectionResult,
    InspectionStation,
    QualityReview,
    Verdict,
)

REVIEW_COMMENT_MAX = 1000


class OrganizationScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Accepts only objects of the requesting user's organization."""

    def get_queryset(self) -> QuerySet:
        request = self.context.get("request")
        if request is None:
            return super().get_queryset().none()
        return scope_to_organization(super().get_queryset(), request.user)


class DefectTypeSerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = DefectType
        fields = ["id", "code", "name", "description", "severity", "is_active", "in_use"]
        read_only_fields = ["is_active"]

    def get_in_use(self, obj: DefectType) -> bool:
        return obj.results.exists() or obj.corrections.exists()

    def validate_code(self, value: str) -> str:
        value = value.strip()
        instance = self.instance
        if instance is not None and value != instance.code and self.get_in_use(instance):
            raise serializers.ValidationError(
                "The code of a used defect type cannot change: archive it and create a new one."
            )
        request = self.context["request"]
        same = scope_to_organization(DefectType.objects.filter(code=value), request.user)
        if instance is not None:
            same = same.exclude(pk=instance.pk)
        if same.exists():
            raise serializers.ValidationError("A defect type with this code already exists.")
        return value


class DefectTypeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DefectType
        fields = ["id", "code", "name", "severity"]


class InspectionStationSerializer(serializers.ModelSerializer):
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.all(), factory_path="factory"
    )
    machine = ScopedPrimaryKeyRelatedField(
        queryset=Machine.objects.all(), factory_path="line__factory"
    )
    defect_types = OrganizationScopedPrimaryKeyRelatedField(
        queryset=DefectType.objects.all(), many=True, required=False
    )
    machine_name = serializers.CharField(source="machine.name", read_only=True)
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = InspectionStation
        fields = [
            "id",
            "line",
            "machine",
            "machine_name",
            "name",
            "defect_types",
            "source",
            "is_active",
            "in_use",
        ]
        read_only_fields = ["is_active"]

    def get_in_use(self, obj: InspectionStation) -> bool:
        return obj.results.exists()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance
        line = attrs.get("line", instance.line if instance else None)
        machine = attrs.get("machine", instance.machine if instance else None)
        if instance is not None and "line" in attrs and attrs["line"] != instance.line:
            raise serializers.ValidationError({"line": "A station cannot move to another line."})
        if machine is not None and line is not None and machine.line_id != line.pk:
            raise serializers.ValidationError({"machine": "The machine must be on this line."})
        is_active = instance.is_active if instance else True
        if machine is not None and is_active:
            others = InspectionStation.objects.filter(machine=machine, is_active=True)
            if instance is not None:
                others = others.exclude(pk=instance.pk)
            if others.exists():
                raise serializers.ValidationError(
                    {"machine": "This machine already has an active inspection station."}
                )
        return attrs


class StationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionStation
        fields = ["id", "name"]


class QualityReviewSerializer(serializers.ModelSerializer):
    corrected_defect_type = DefectTypeSummarySerializer(read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = QualityReview
        fields = ["id", "verdict", "corrected_defect_type", "comment", "reviewed_by", "reviewed_at"]


class ReviewInputSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=Verdict.choices)
    corrected_defect_type = OrganizationScopedPrimaryKeyRelatedField(
        queryset=DefectType.objects.all(), required=False, allow_null=True
    )
    comment = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=REVIEW_COMMENT_MAX
    )


class InspectionResultSerializer(serializers.ModelSerializer):
    """A result with its production context (passed in the serializer context as
    `contexts`, computed in batch by services/context.py)."""

    station = StationSummarySerializer(read_only=True)
    machine = serializers.SerializerMethodField()
    defect_type = DefectTypeSummarySerializer(read_only=True)
    effective_defect_type = serializers.SerializerMethodField()
    is_defect = serializers.SerializerMethodField()
    review = QualityReviewSerializer(source="current_review", read_only=True)
    context = serializers.SerializerMethodField()

    class Meta:
        model = InspectionResult
        fields = [
            "id",
            "event_id",
            "line",
            "machine",
            "station",
            "timestamp",
            "reported_code",
            "defect_type",
            "effective_defect_type",
            "is_defect",
            "confidence",
            "source",
            "outcome",
            "warnings",
            "review",
            "context",
        ]

    def get_machine(self, obj: InspectionResult) -> dict[str, Any]:
        return {
            "id": obj.machine_id,
            "external_id": obj.machine.external_id,
            "name": obj.machine.name,
        }

    def get_effective_defect_type(self, obj: InspectionResult) -> dict[str, Any] | None:
        review = obj.current_review
        if review is not None and review.verdict == Verdict.RECLASSIFIED:
            return DefectTypeSummarySerializer(review.corrected_defect_type).data
        return DefectTypeSummarySerializer(obj.defect_type).data if obj.defect_type else None

    def get_is_defect(self, obj: InspectionResult) -> bool:
        review = obj.current_review
        return review is None or review.verdict != Verdict.FALSE_REJECT

    def get_context(self, obj: InspectionResult) -> dict[str, Any] | None:
        return self.context.get("contexts", {}).get(obj.pk)
