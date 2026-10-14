import csv
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Model, Prefetch, QuerySet
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.mixins import AuditedModelViewSetMixin, snapshot
from apps.audit.services import record_audit
from apps.downtime.filters import (
    analysis_scope,
    bool_query_param,
    choice_query_param,
    filter_downtime_events,
    filter_incidents,
    range_from,
)
from apps.downtime.models import DowntimeEvent, DowntimeReason, LineStopIncident
from apps.downtime.serializers import (
    BulkClassificationInputSerializer,
    ClassificationInputSerializer,
    ClassificationSerializer,
    DowntimeEventSerializer,
    DowntimeReasonSerializer,
    IncidentDetailSerializer,
    IncidentSerializer,
    role_in_incident,
)
from apps.downtime.services.analysis import GROUP_BY, pareto, recurring, select_entries, summary
from apps.downtime.services.classification import (
    BULK_CLASSIFYING_ROLES,
    CLASSIFYING_ROLES,
    ClassificationError,
    bulk_classify,
    classify_downtime,
    suggested_reasons,
)
from apps.downtime.services.durations import duration_seconds
from apps.organizations.permissions import HasMembership, IsConfigurationManagerOrReadOnly
from apps.organizations.tenancy import TenantScopedViewSetMixin, get_membership, scope_to_user
from apps.organizations.views import Conflict, integer_query_param
from apps.production.views import EventPagination

EVENT_SELECT = (
    "machine",
    "line__factory",
    "current_classification__reason",
    "current_classification__created_by",
)


class CanClassifyDowntime(BasePermission):
    """Only operators, supervisors, factory managers and platform admins may classify."""

    message = "Your role cannot classify downtime."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method != "POST":
            return True
        membership = get_membership(request.user)
        if getattr(view, "action", None) == "bulk_classify":
            return membership is not None and membership.role in BULK_CLASSIFYING_ROLES
        return membership is not None and membership.role in CLASSIFYING_ROLES


class RequestTimeMixin:
    """All durations in one response are measured against the same `now`."""

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()  # type: ignore[misc]
        context["now"] = timezone.now()
        context["range"] = range_from(self.request)  # type: ignore[attr-defined]
        return context


def _reason_for(request: Request, reason_id: int) -> DowntimeReason:
    reasons = scope_to_user(DowntimeReason.objects.all(), request.user, "factory")
    reason = reasons.filter(pk=reason_id).first()
    if reason is None:
        raise ValidationError({"reason": "Unknown reason."})
    return reason


class DowntimeEventViewSet(
    RequestTimeMixin, TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    """Derived downtime events.

    Filters: line, machine, factory, incident, category (comma list), reason (code or
    "unclassified"), classified, is_first_stop, min_duration/max_duration (s),
    start/end or shift/date (overlap), view=line (one row per line-view entry),
    needs_reason=true (the classification queue), ordering.
    """

    queryset = DowntimeEvent.objects.filter(is_obsolete=False).select_related(*EVENT_SELECT)
    serializer_class = DowntimeEventSerializer
    factory_path = "line__factory"
    permission_classes = [IsAuthenticated, HasMembership, CanClassifyDowntime]
    pagination_class = EventPagination

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            return filter_downtime_events(queryset, self.request)
        return queryset.order_by("started_at", "machine__position", "id")

    @action(detail=True, methods=["get", "post"], url_path="classifications")
    def classifications(self, request: Request, pk: str | None = None) -> Response:
        event = self.get_object()  # 404 outside the user's factories
        if request.method == "GET":
            history = event.classifications.select_related("reason", "created_by")
            return Response(ClassificationSerializer(history, many=True).data)

        payload = ClassificationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        reason = _reason_for(request, payload.validated_data["reason"])
        try:
            classification = classify_downtime(
                event, reason, payload.validated_data["comment"], request.user
            )
        except ClassificationError as exc:
            raise ValidationError({"reason": str(exc)}) from None
        return Response(
            ClassificationSerializer(classification).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="bulk-classify")
    def bulk_classify(self, request: Request) -> Response:
        """One reason for several stops; all or nothing (supervisors and managers)."""
        payload = BulkClassificationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ids = list(dict.fromkeys(payload.validated_data["event_ids"]))
        events = {e.pk: e for e in super().get_queryset().filter(pk__in=ids)}
        missing = [i for i in ids if i not in events]
        if missing:
            raise ValidationError({"event_ids": f"Unknown or not accessible: {missing}."})
        reason = _reason_for(request, payload.validated_data["reason"])
        try:
            done = bulk_classify(
                [events[i] for i in ids], reason, payload.validated_data["comment"], request.user
            )
        except ClassificationError as exc:
            raise ValidationError({"reason": str(exc)}) from None
        return Response({"classified": len(done)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="suggested-reasons")
    def suggested_reasons(self, request: Request, pk: str | None = None) -> Response:
        reasons = suggested_reasons(self.get_object())
        return Response(
            DowntimeReasonSerializer(reasons, many=True, context={"request": request}).data
        )


class IncidentViewSet(RequestTimeMixin, TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Line stop incidents. Filters: line, origin, start/end (overlap)."""

    queryset = LineStopIncident.objects.select_related(
        "line__factory", "first_machine"
    ).prefetch_related(
        Prefetch("events", queryset=DowntimeEvent.objects.select_related(*EVENT_SELECT))
    )
    factory_path = "line__factory"
    permission_classes = [IsAuthenticated, HasMembership]
    pagination_class = EventPagination

    def get_serializer_class(self) -> type:
        return IncidentDetailSerializer if self.action == "retrieve" else IncidentSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = filter_incidents(queryset, self.request)
        return queryset.order_by("-started_at", "-id")


class DowntimeReasonViewSet(
    AuditedModelViewSetMixin, TenantScopedViewSetMixin, viewsets.ModelViewSet
):
    """The reason catalogue. Everyone reads active reasons (?factory=, ?include_archived=true);
    factory managers and platform admins create, edit, archive and restore. A reason that
    was ever used cannot be deleted: archive it instead (it stays in history)."""

    queryset = DowntimeReason.objects.all()
    serializer_class = DowntimeReasonSerializer
    factory_path = "factory"
    permission_classes = [IsAuthenticated, HasMembership, IsConfigurationManagerOrReadOnly]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            if not bool_query_param(self.request, "include_archived"):
                queryset = queryset.filter(is_active=True)
            factory = integer_query_param(self.request, "factory")
            if factory is not None:
                queryset = queryset.filter(factory_id=factory)
        return queryset.order_by("factory_id", "category", "code")

    def perform_destroy(self, instance: Model) -> None:
        if instance.classifications.exists():  # type: ignore[attr-defined]
            raise Conflict("This reason has been used. Archive it instead of deleting it.")
        super().perform_destroy(instance)

    def _set_active(self, request: Request, active: bool) -> Response:
        reason = self.get_object()
        with transaction.atomic():
            before = snapshot(reason)
            reason.is_active = active
            reason.save(update_fields=["is_active"])
            membership = get_membership(request.user)
            record_audit(
                user=request.user,
                action=f"downtimereason.{'restored' if active else 'archived'}",
                entity=reason,
                organization=membership.organization if membership else None,
                before=before,
                after=snapshot(reason),
            )
        return Response(self.get_serializer(reason).data)

    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: str | None = None) -> Response:
        return self._set_active(request, False)

    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: str | None = None) -> Response:
        return self._set_active(request, True)


# --- Analysis --------------------------------------------------------------------------


class AnalysisView(APIView):
    permission_classes = [IsAuthenticated, HasMembership]


class ParetoView(AnalysisView):
    """GET /api/v1/downtime/pareto/?view=line|machine&group_by=reason|machine|category|alarm_code"""

    def get(self, request: Request) -> Response:
        lines, filters = analysis_scope(request)
        group_by = choice_query_param(request, "group_by", list(GROUP_BY)) or "reason"
        body = pareto(select_entries(lines, filters), group_by, filters.view)
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


class SummaryView(AnalysisView):
    """GET /api/v1/downtime/summary/ — total, stops, unclassified, secondary breakdowns, longest."""

    def get(self, request: Request) -> Response:
        lines, filters = analysis_scope(request)
        body = summary(select_entries(lines, filters), filters.view)
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


class RecurringView(AnalysisView):
    """GET /api/v1/downtime/recurring/ — breakdowns repeating on a machine."""

    def get(self, request: Request) -> Response:
        lines, filters = analysis_scope(request)
        body = recurring(lines, filters)
        body["range"] = {"start": filters.start, "end": filters.end}
        return Response(body)


# --- CSV export ------------------------------------------------------------------------

CSV_HEADER = [
    "id",
    "line",
    "machine_id",
    "machine",
    "category",
    "role_in_incident",
    "start",
    "end",
    "timezone",
    "duration_seconds",
    "alarm_code",
    "first_observed_stop",
    "incident",
    "reason_code",
    "reason",
    "classified_by",
    "classified_at",
    "comment",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formulas: text starting with = + - @ tab or CR gets a quote."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


class _Echo:
    def write(self, value: str) -> str:
        return value


class DowntimeExportView(APIView):
    """GET /api/v1/downtime-events/export.csv — the events list as CSV, same filters."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request) -> StreamingHttpResponse:
        events = scope_to_user(
            DowntimeEvent.objects.filter(is_obsolete=False).select_related(*EVENT_SELECT, "line"),
            request.user,
            "line__factory",
        )
        events = filter_downtime_events(events, request)
        limit = settings.DOWNTIME_EXPORT_MAX_ROWS
        if events.count() > limit:
            raise ValidationError(
                {"detail": f"More than {limit:,} rows. Narrow the filters (e.g. a shorter range)."}
            )
        now = timezone.now()
        writer = csv.writer(_Echo())

        def rows() -> Iterator[str]:
            yield "﻿" + writer.writerow(CSV_HEADER)  # BOM: Excel opens it as UTF-8
            for event in events.iterator(chunk_size=2000):
                yield writer.writerow([csv_cell(v) for v in self._row(event, now)])

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="downtime.csv"'
        return response

    @staticmethod
    def _row(event: DowntimeEvent, now: Any) -> list[Any]:
        zone = ZoneInfo(event.line.factory.timezone)
        classification = event.current_classification
        reason = classification.reason if classification else None
        return [
            event.pk,
            event.line.name,
            event.machine.external_id,
            event.machine.name,
            event.category,
            role_in_incident(event) or "",
            event.started_at.astimezone(zone).isoformat(timespec="milliseconds"),
            event.ended_at.astimezone(zone).isoformat(timespec="milliseconds")
            if event.ended_at
            else "",
            event.line.factory.timezone,
            round(duration_seconds(event.started_at, event.ended_at, now), 3),
            event.alarm_code or "",
            "yes" if event.is_first_stop else "no",
            event.incident_id or "",
            reason.code if reason else "",
            reason.name if reason else "",
            classification.created_by.email if classification and classification.created_by else "",
            classification.created_at.astimezone(zone).isoformat(timespec="seconds")
            if classification
            else "",
            classification.comment if classification else "",
        ]
