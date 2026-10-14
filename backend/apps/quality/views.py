"""Quality endpoints. Every queryset is tenant-scoped; every number comes from services/."""

import csv
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Model, QuerySet
from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services.buckets import day_buckets, hour_buckets, shift_buckets
from apps.audit.mixins import AuditedModelViewSetMixin, snapshot
from apps.audit.services import record_audit
from apps.downtime.filters import bool_query_param, choice_query_param
from apps.downtime.views import _Echo, csv_cell
from apps.organizations.permissions import (
    AllFactoriesRequiredForWrites,
    HasMembership,
    IsConfigurationManagerOrReadOnly,
)
from apps.organizations.tenancy import (
    OrganizationScopedViewSetMixin,
    TenantScopedViewSetMixin,
    get_membership,
    scope_to_user,
)
from apps.organizations.views import Conflict, integer_query_param
from apps.production.services.shifts import shift_periods
from apps.production.views import EventPagination
from apps.quality.filters import ordering_param, quality_scope
from apps.quality.models import DefectType, InspectionResult, InspectionStation
from apps.quality.serializers import (
    DefectTypeSerializer,
    InspectionResultSerializer,
    InspectionStationSerializer,
    QualityReviewSerializer,
    ReviewInputSerializer,
)
from apps.quality.services.context import contexts_for
from apps.quality.services.live import queue_quality_updates
from apps.quality.services.metrics import GROUP_BY, pareto, select_results, summary, trend
from apps.quality.services.processing import reprocess_code, reprocess_machines
from apps.quality.services.reviews import ReviewError, can_review, review_result

CONFIG_PERMISSIONS = [IsAuthenticated, HasMembership, IsConfigurationManagerOrReadOnly]
RESULT_SELECT = (
    "machine",
    "station",
    "defect_type",
    "current_review__corrected_defect_type",
    "current_review__reviewed_by",
)


class ArchiveMixin:
    """archive/restore actions instead of deleting configuration that history refers to."""

    audit_name = ""

    def after_active_change(self, instance: Any) -> None:
        pass

    def _set_active(self, request: Request, active: bool) -> Response:
        instance = self.get_object()  # type: ignore[attr-defined]
        with transaction.atomic():
            before = snapshot(instance)
            instance.is_active = active
            instance.save(update_fields=["is_active"])
            membership = get_membership(request.user)
            record_audit(
                user=request.user,
                action=f"{self.audit_name}.{'restored' if active else 'archived'}",
                entity=instance,
                organization=membership.organization if membership else None,
                before=before,
                after=snapshot(instance),
            )
            self.after_active_change(instance)
        return Response(self.get_serializer(instance).data)  # type: ignore[attr-defined]

    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: str | None = None) -> Response:
        return self._set_active(request, False)

    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: str | None = None) -> Response:
        return self._set_active(request, True)


class DefectTypeViewSet(
    AuditedModelViewSetMixin, ArchiveMixin, OrganizationScopedViewSetMixin, viewsets.ModelViewSet
):
    """The organization's defect catalogue. Everyone reads active types
    (?include_archived=true for all); factory managers with access to all factories and
    platform admins write. A type that was ever used cannot be deleted: archive it."""

    queryset = DefectType.objects.all()
    serializer_class = DefectTypeSerializer
    permission_classes = [*CONFIG_PERMISSIONS, AllFactoriesRequiredForWrites]
    audit_name = "defecttype"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list" and not bool_query_param(self.request, "include_archived"):
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("code")

    def create_kwargs(self) -> dict[str, Any]:
        membership = get_membership(self.request.user)
        assert membership is not None  # guaranteed by HasMembership
        return {"organization": membership.organization}

    def perform_create(self, serializer: Any) -> None:
        with transaction.atomic():
            super().perform_create(serializer)
            # Results that reported this code before it existed now get the type.
            reprocess_code(serializer.instance.organization_id, serializer.instance.code)

    def perform_destroy(self, instance: Model) -> None:
        if DefectTypeSerializer().get_in_use(instance):  # type: ignore[arg-type]
            raise Conflict("This defect type has been used. Archive it instead of deleting it.")
        super().perform_destroy(instance)


class InspectionStationViewSet(
    AuditedModelViewSetMixin, ArchiveMixin, TenantScopedViewSetMixin, viewsets.ModelViewSet
):
    """Inspection stations (?line=, ?include_archived=true). One active station per machine.
    Changing a station re-maps the results of its machine (station and warnings)."""

    queryset = InspectionStation.objects.select_related("machine").prefetch_related("defect_types")
    serializer_class = InspectionStationSerializer
    permission_classes = CONFIG_PERMISSIONS
    factory_path = "line__factory"
    audit_name = "inspectionstation"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            if not bool_query_param(self.request, "include_archived"):
                queryset = queryset.filter(is_active=True)
            line = integer_query_param(self.request, "line")
            if line is not None:
                queryset = queryset.filter(line_id=line)
        return queryset

    def perform_create(self, serializer: Any) -> None:
        with transaction.atomic():
            super().perform_create(serializer)
            reprocess_machines([serializer.instance.machine_id])

    def perform_update(self, serializer: Any) -> None:
        with transaction.atomic():
            old_machine = serializer.instance.machine_id
            super().perform_update(serializer)
            reprocess_machines({old_machine, serializer.instance.machine_id})

    def after_active_change(self, instance: Any) -> None:
        # Archiving keeps the station on its past results; restoring makes it the
        # machine's active station again, so its results are re-mapped.
        if not instance.is_active:
            return
        if (
            InspectionStation.objects.filter(machine=instance.machine, is_active=True)
            .exclude(pk=instance.pk)
            .exists()
        ):
            raise Conflict("This machine already has an active inspection station.")
        reprocess_machines([instance.machine_id])

    def perform_destroy(self, instance: Model) -> None:
        if instance.results.exists():  # type: ignore[attr-defined]
            raise Conflict("This station has results. Archive it instead of deleting it.")
        super().perform_destroy(instance)


class InspectionResultViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/inspection-results/?line=&start=&end= (or shift=&date=) with filters
    station, machine, defect_type (code or "unknown"), severity, product, reviewed,
    verdict, ordering. Each row carries its production context."""

    queryset = InspectionResult.objects.select_related(*RESULT_SELECT)
    serializer_class = InspectionResultSerializer
    permission_classes = [IsAuthenticated, HasMembership]
    factory_path = "line__factory"
    pagination_class = EventPagination

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset
        lines, filters = quality_scope(self.request)
        ids = select_results(lines, filters).values("pk")
        return queryset.filter(pk__in=ids).order_by(*ordering_param(self.request))

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        assert page is not None  # pagination is always on
        serializer = self.get_serializer(
            page,
            many=True,
            context={**self.get_serializer_context(), "contexts": contexts_for(page)},
        )
        return self.get_paginated_response(serializer.data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        result = self.get_object()
        context = {**self.get_serializer_context(), "contexts": contexts_for([result])}
        return Response(self.get_serializer(result, context=context).data)

    @action(detail=True, methods=["get", "post"])
    def reviews(self, request: Request, pk: str | None = None) -> Response:
        result = self.get_object()
        if request.method == "GET":
            return Response(QualityReviewSerializer(result.reviews.all(), many=True).data)
        if not can_review(request.user):
            raise PermissionDenied("Your role cannot review inspection results.")
        data = ReviewInputSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        try:
            review = review_result(
                result,
                data.validated_data["verdict"],
                data.validated_data.get("corrected_defect_type"),
                data.validated_data["comment"],
                request.user,
            )
        except ReviewError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        queue_quality_updates([result.line_id])
        return Response(QualityReviewSerializer(review).data, status=status.HTTP_201_CREATED)


# --- Metrics --------------------------------------------------------------------------


class QualityView(APIView):
    permission_classes = [IsAuthenticated, HasMembership]


class QualitySummaryView(QualityView):
    """GET /api/v1/quality/summary/?line=&start=&end="""

    def get(self, request: Request) -> Response:
        lines, filters = quality_scope(request)
        body = summary(lines, filters)
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


class QualityParetoView(QualityView):
    """GET /api/v1/quality/pareto/?group_by=defect_type|station|machine|product"""

    def get(self, request: Request) -> Response:
        lines, filters = quality_scope(request)
        group_by = choice_query_param(request, "group_by", list(GROUP_BY)) or "defect_type"
        body = pareto(lines, filters, group_by)
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


class QualityTrendView(QualityView):
    """GET /api/v1/quality/trend/?line=&start=&end=&group_by=hour|shift|day (line required:
    buckets follow its factory's timezone and shifts)."""

    def get(self, request: Request) -> Response:
        lines, filters = quality_scope(request, require_line=True)
        group_by = choice_query_param(request, "group_by", ["hour", "shift", "day"]) or "hour"
        factory = lines[0].factory
        zone = ZoneInfo(factory.timezone)
        if group_by == "hour":
            buckets = hour_buckets(filters.start, filters.end, zone)
        elif group_by == "day":
            buckets = day_buckets(filters.start, filters.end, zone)
        else:
            periods = shift_periods(factory, filters.start, filters.end)
            buckets = shift_buckets(filters.start, filters.end, periods)
        body = trend(lines, filters, buckets)
        body["group_by"] = group_by
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


# --- CSV ------------------------------------------------------------------------------

CSV_HEADER = [
    "id",
    "line",
    "time (factory)",
    "timezone",
    "machine",
    "station",
    "reported code",
    "defect type",
    "severity",
    "effective defect type",
    "confidence",
    "review",
    "reviewed by",
    "review comment",
    "product",
    "machine state",
    "last alarm",
    "after incident",
    "warnings",
]


class InspectionResultExportView(APIView):
    """GET /api/v1/inspection-results/export.csv — the results list as CSV, same filters."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request) -> StreamingHttpResponse:
        lines, filters = quality_scope(request)
        ids = select_results(lines, filters).values("pk")
        results = (
            scope_to_user(
                InspectionResult.objects.select_related(*RESULT_SELECT, "line__factory"),
                request.user,
                "line__factory",
            )
            .filter(pk__in=ids)
            .order_by("timestamp", "id")
        )
        limit = settings.QUALITY_EXPORT_MAX_ROWS
        if results.count() > limit:
            raise ValidationError(
                {"detail": f"More than {limit:,} rows. Narrow the filters (e.g. a shorter range)."}
            )
        writer = csv.writer(_Echo())
        serializer = InspectionResultSerializer()

        def rows() -> Iterator[str]:
            yield "﻿" + writer.writerow(CSV_HEADER)  # BOM: Excel opens it as UTF-8
            chunk: list[InspectionResult] = []
            for result in results.iterator(chunk_size=2000):
                chunk.append(result)
                if len(chunk) == 2000:
                    yield from self._rows(chunk, writer, serializer)
                    chunk = []
            yield from self._rows(chunk, writer, serializer)

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="inspection-results.csv"'
        return response

    @staticmethod
    def _rows(
        chunk: list[InspectionResult], writer: Any, serializer: InspectionResultSerializer
    ) -> Iterator[str]:
        contexts = contexts_for(chunk)
        for result in chunk:
            yield writer.writerow([csv_cell(v) for v in _csv_row(result, contexts, serializer)])


def _csv_row(
    result: InspectionResult, contexts: dict[int, dict[str, Any]], serializer: Any
) -> list[Any]:
    zone_name = result.line.factory.timezone
    zone = ZoneInfo(zone_name)
    review = result.current_review
    effective = serializer.get_effective_defect_type(result)
    context = contexts.get(result.pk, {})
    product = context.get("product")
    incident = context.get("incident")
    return [
        result.pk,
        result.line.name,
        result.timestamp.astimezone(zone).isoformat(timespec="milliseconds"),
        zone_name,
        result.machine.name,
        result.station.name if result.station else "",
        result.reported_code,
        result.defect_type.code if result.defect_type else "",
        result.defect_type.severity if result.defect_type else "",
        effective["code"] if effective else "",
        "" if result.confidence is None else result.confidence,
        review.verdict if review else "unreviewed",
        review.reviewed_by.email if review else "",
        review.comment if review else "",
        product["sku"] if product else "",
        context.get("machine_state", ""),
        context.get("last_alarm_code") or "",
        incident["text"] if incident else "",
        " | ".join(result.warnings),
    ]
