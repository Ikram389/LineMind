"""Maintenance actions API. Querysets are tenant-scoped; every rule lives in services/."""

import csv
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Case, Count, IntegerField, Q, QuerySet, Value, When
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.downtime.filters import bool_query_param, choice_query_param
from apps.downtime.models import DowntimeReason
from apps.downtime.views import _Echo, csv_cell
from apps.maintenance.models import OPEN_STATUSES, MaintenanceAction, Priority, Status
from apps.maintenance.serializers import (
    ActionLinkSerializer,
    DiagnosisInputSerializer,
    DiagnosisSerializer,
    EntrySerializer,
    LinkInputSerializer,
    MaintenanceActionSerializer,
    StatusChangeSerializer,
    TransitionSerializer,
    VerifySerializer,
)
from apps.maintenance.services.actions import create_action, update_action
from apps.maintenance.services.diagnosis import preview, record_diagnosis
from apps.maintenance.services.effectiveness import effectiveness
from apps.maintenance.services.links import LinkError, add_links, prefill
from apps.maintenance.services.permissions import is_supervisor, is_worker
from apps.maintenance.services.workflow import NotAllowed, WorkflowError, transition, verify
from apps.notifications.services.recipients import recipients
from apps.organizations.models import Factory, Role
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import TenantScopedViewSetMixin, scope_to_user
from apps.organizations.views import integer_query_param
from apps.production.views import EventPagination, aware_datetime_param

PRIORITY_ORDER = Case(
    When(priority=Priority.URGENT, then=Value(0)),
    When(priority=Priority.HIGH, then=Value(1)),
    When(priority=Priority.MEDIUM, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


def overdue_q(now: datetime) -> Q:
    """Open, and its due day has ended in its factory's timezone (the same rule as the
    maintenance_overdue alert)."""
    q = Q(pk__in=[])
    for factory in Factory.objects.only("pk", "timezone"):
        today = now.astimezone(ZoneInfo(factory.timezone)).date()
        q |= Q(factory_id=factory.pk, due_date__lt=today)
    return Q(status__in=OPEN_STATUSES) & q


def annotate(queryset: QuerySet, now: datetime) -> QuerySet:
    return queryset.annotate(
        link_count=Count("links", distinct=True),
        is_overdue=Case(
            When(overdue_q(now), then=Value(1)), default=Value(0), output_field=IntegerField()
        ),
        priority_order=PRIORITY_ORDER,
    )


def errors(exc: Exception) -> None:
    if isinstance(exc, NotAllowed):
        raise PermissionDenied(str(exc)) from None
    raise ValidationError({"detail": str(exc)}) from None


def filter_actions(queryset: QuerySet, request: Request) -> QuerySet:
    params = request.query_params
    raw_status = params.get("status")
    if raw_status == "open":
        queryset = queryset.filter(status__in=OPEN_STATUSES)
    elif raw_status:
        wanted = {s.strip() for s in raw_status.split(",") if s.strip()}
        unknown = wanted - set(Status.values)
        if unknown:
            raise ValidationError({"status": f"Unknown status(es): {', '.join(sorted(unknown))}."})
        queryset = queryset.filter(status__in=wanted)
    priority = choice_query_param(request, "priority", list(Priority.values))
    if priority:
        queryset = queryset.filter(priority=priority)
    for name in ("machine", "line", "assignee"):
        value = integer_query_param(request, name)
        if value is not None:
            queryset = queryset.filter(**{f"{name}_id": value})
    if bool_query_param(request, "mine"):
        queryset = queryset.filter(assignee=request.user)
    if bool_query_param(request, "overdue"):
        queryset = queryset.filter(is_overdue=1)
    start, end = aware_datetime_param(request, "start"), aware_datetime_param(request, "end")
    if start is not None:
        queryset = queryset.filter(created_at__gte=start)
    if end is not None:
        queryset = queryset.filter(created_at__lt=end)
    return queryset


class MaintenanceActionViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Maintenance actions. Filters: status (comma list or "open"), priority, machine, line,
    assignee, mine=true, overdue=true, start/end (created). Overdue first, then priority."""

    queryset = MaintenanceAction.objects.select_related(
        "factory", "line", "machine", "reporter", "assignee", "verified_by"
    )
    serializer_class = MaintenanceActionSerializer
    permission_classes = [IsAuthenticated, HasMembership]
    factory_path = "factory"
    pagination_class = EventPagination
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self) -> QuerySet:
        queryset = annotate(super().get_queryset(), timezone.now())
        if self.action == "list":
            queryset = filter_actions(queryset, self.request).order_by(
                "-is_overdue", "priority_order", "due_date", "-created_at"
            )
        return queryset

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        links = [dict(link) for link in data.pop("links", [])]
        machine = data.pop("machine")
        try:
            action = create_action(request.user, machine, data, links)
        except (NotAllowed, WorkflowError, LinkError) as exc:
            errors(exc)
        output = self.get_serializer(self.get_queryset().get(pk=action.pk))
        return Response(output.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        action = self.get_object()
        serializer = self.get_serializer(action, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = {
            k: v for k, v in serializer.validated_data.items() if k not in ("links", "machine")
        }
        if "machine" in serializer.validated_data:
            raise ValidationError({"machine": "An action cannot move to another machine."})
        try:
            update_action(action, request.user, changes)
        except (NotAllowed, WorkflowError) as exc:
            errors(exc)
        return Response(self.get_serializer(self.get_queryset().get(pk=action.pk)).data)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: str | None = None) -> Response:
        action = self.get_object()
        data = TransitionSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        try:
            transition(
                action,
                data.validated_data["to"],
                request.user,
                data.validated_data["note"],
                assignee=data.validated_data.get("assignee"),
                fixed_at=data.validated_data.get("fixed_at"),
            )
        except (NotAllowed, WorkflowError) as exc:
            errors(exc)
        return Response(self.get_serializer(self.get_queryset().get(pk=action.pk)).data)

    @action(detail=True, methods=["post"])
    def verify(self, request: Request, pk: str | None = None) -> Response:
        action = self.get_object()
        data = VerifySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            verify(action, data.validated_data["result"], data.validated_data["note"], request.user)
        except (NotAllowed, WorkflowError) as exc:
            errors(exc)
        return Response(self.get_serializer(self.get_queryset().get(pk=action.pk)).data)

    @action(detail=True, methods=["get", "post"])
    def entries(self, request: Request, pk: str | None = None) -> Response:
        action = self.get_object()
        if request.method == "GET":
            return Response(
                EntrySerializer(action.entries.select_related("author"), many=True).data
            )
        if not is_worker(request.user, action):
            raise PermissionDenied("Only the assignee or a maintenance technician can log work.")
        if action.status not in (Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING, Status.DONE):
            raise ValidationError({"detail": f"Work cannot be logged on a {action.status} action."})
        serializer = EntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(action=action, author=request.user)
        return Response(EntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def links(self, request: Request, pk: str | None = None) -> Response:
        action = self.get_object()
        if request.method == "GET":
            links = action.links.select_related(
                "downtime_event__machine",
                "downtime_event__current_classification__reason",
                "incident__first_machine",
                "alert",
                "inspection_result__machine",
                "signature_machine",
                "signature_reason",
            )
            return Response(ActionLinkSerializer(links, many=True).data)
        if action.status in (Status.CANCELLED, Status.VERIFIED):
            raise ValidationError(
                {"detail": f"Evidence cannot be added to a {action.status} action."}
            )
        items = LinkInputSerializer(
            data=request.data if isinstance(request.data, list) else [request.data], many=True
        )
        items.is_valid(raise_exception=True)
        try:
            created = add_links(action, [dict(i) for i in items.validated_data], request.user)
        except LinkError as exc:
            errors(exc)
        return Response(
            ActionLinkSerializer(created, many=True).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"])
    def history(self, request: Request, pk: str | None = None) -> Response:
        action = self.get_object()
        return Response(
            {
                "status_changes": StatusChangeSerializer(
                    action.status_changes.select_related("changed_by"), many=True
                ).data,
                "diagnoses": DiagnosisSerializer(
                    action.diagnoses.select_related("reason", "created_by"), many=True
                ).data,
            }
        )

    @action(detail=True, methods=["get", "post"])
    def diagnosis(self, request: Request, pk: str | None = None) -> Response:
        """GET ?reason=<id>: preview what applying would change. POST: record (and apply)."""
        action = self.get_object()
        if request.method == "GET":
            reason = get_object_or_404(
                DowntimeReason, pk=integer_query_param(request, "reason"), factory=action.factory
            )
            return Response(preview(action, reason))
        data = DiagnosisInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        reason = data.validated_data["reason"]
        if reason.factory_id != action.factory_id:
            raise ValidationError({"reason": "Choose a reason of this factory."})
        try:
            diagnosis = record_diagnosis(
                action,
                reason,
                data.validated_data["text"],
                request.user,
                apply_to_stops=data.validated_data["apply_to_linked_stops"],
                replace_other_reasons=data.validated_data["replace_other_reasons"],
            )
        except (NotAllowed, WorkflowError) as exc:
            errors(exc)
        return Response(DiagnosisSerializer(diagnosis).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="effectiveness")
    def effectiveness_view(self, request: Request, pk: str | None = None) -> Response:
        return Response(effectiveness(self.get_object()))

    @action(detail=True, methods=["get"])
    def assignees(self, request: Request, pk: str | None = None) -> Response:
        """Who can be assigned: active users with access to the action's factory
        (technicians first). For supervisors and managers, who assign."""
        action = self.get_object()
        if not is_supervisor(request.user):
            raise PermissionDenied("Only supervisors and managers assign actions.")
        users = recipients(action.factory, [role.value for role in Role]).select_related(
            "membership"
        )
        rows = [{"id": u.pk, "email": u.email, "role": u.membership.role} for u in users]
        rows.sort(key=lambda r: (r["role"] != Role.MAINTENANCE_TECHNICIAN, r["email"]))
        return Response(rows)

    @action(detail=False, methods=["get"])
    def prefill(self, request: Request) -> Response:
        """The form for "create action from" a source: ?source=incident|alert|recurring|
        inspection_result|machine with id (or machine, reason/alarm, start, end)."""
        params = {k: v for k, v in request.query_params.items()}
        try:
            return Response(prefill(params.pop("source", ""), params, request.user))
        except LinkError as exc:
            errors(exc)
        except ObjectDoesNotExist:
            raise NotFound("No such source in your factories.") from None
        except (KeyError, ValueError):
            raise ValidationError({"detail": "Missing or invalid source parameters."}) from None
        return Response(status=status.HTTP_400_BAD_REQUEST)  # pragma: no cover

    @action(detail=False, methods=["get"], url_path="mine/count")
    def mine_count(self, request: Request) -> Response:
        count = (
            super()
            .get_queryset()
            .filter(
                assignee=request.user,
                status__in=(Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING),
            )
            .count()
        )
        return Response({"count": count})


# --- CSV -------------------------------------------------------------------------------

CSV_HEADER = [
    "id",
    "title",
    "line",
    "machine",
    "type",
    "priority",
    "status",
    "reporter",
    "assignee",
    "due date",
    "created (factory)",
    "started (factory)",
    "completed (factory)",
    "fixed (factory)",
    "timezone",
    "verification",
    "links",
    "problem",
]


class MaintenanceExportView(APIView):
    """GET /api/v1/maintenance-actions/export.csv — the list as CSV, same filters."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request) -> StreamingHttpResponse:
        actions = annotate(
            scope_to_user(
                MaintenanceAction.objects.select_related(
                    "factory", "line", "machine", "reporter", "assignee"
                ),
                request.user,
                "factory",
            ),
            timezone.now(),
        )
        actions = filter_actions(actions, request).order_by("created_at", "id")
        limit = settings.MAINTENANCE_EXPORT_MAX_ROWS
        if actions.count() > limit:
            raise ValidationError(
                {"detail": f"More than {limit:,} rows. Narrow the filters (e.g. a shorter range)."}
            )
        writer = csv.writer(_Echo())

        def local(value: datetime | None, zone: ZoneInfo) -> str:
            return value.astimezone(zone).isoformat(timespec="seconds") if value else ""

        def rows() -> Iterator[str]:
            yield "﻿" + writer.writerow(CSV_HEADER)  # BOM: Excel opens it as UTF-8
            for a in actions.iterator(chunk_size=2000):
                zone = ZoneInfo(a.factory.timezone)
                row = [
                    a.pk,
                    a.title,
                    a.line.name,
                    a.machine.name,
                    a.action_type,
                    a.priority,
                    a.status,
                    a.reporter.email,
                    a.assignee.email if a.assignee else "",
                    a.due_date.isoformat() if a.due_date else "",
                    local(a.created_at, zone),
                    local(a.started_at, zone),
                    local(a.completed_at, zone),
                    local(a.fixed_at, zone),
                    a.factory.timezone,
                    a.verification_result,
                    a.link_count,
                    a.problem,
                ]
                yield writer.writerow([csv_cell(v) for v in row])

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="maintenance-actions.csv"'
        return response
