from typing import Any

from django.db.models import Prefetch, QuerySet
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.downtime.filters import filter_downtime_events, filter_incidents
from apps.downtime.models import DowntimeEvent, DowntimeReason, LineStopIncident
from apps.downtime.serializers import (
    ClassificationInputSerializer,
    ClassificationSerializer,
    DowntimeEventSerializer,
    DowntimeReasonSerializer,
    IncidentDetailSerializer,
    IncidentSerializer,
)
from apps.downtime.services.classification import (
    CLASSIFYING_ROLES,
    ClassificationError,
    classify_downtime,
)
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import TenantScopedViewSetMixin, get_membership, scope_to_user
from apps.organizations.views import integer_query_param
from apps.production.views import EventPagination


class CanClassifyDowntime(BasePermission):
    """Only operators, supervisors, factory managers and platform admins may classify."""

    message = "Your role cannot classify downtime."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method != "POST":
            return True
        membership = get_membership(request.user)
        return membership is not None and membership.role in CLASSIFYING_ROLES


class RequestTimeMixin:
    """All durations in one response are measured against the same `now`."""

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()  # type: ignore[misc]
        context["now"] = timezone.now()
        return context


class DowntimeEventViewSet(
    RequestTimeMixin, TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    """Derived downtime events. Filters: line, machine, factory, incident, category,
    reason (code), classified, is_first_stop, start/end (overlap)."""

    queryset = DowntimeEvent.objects.filter(is_obsolete=False).select_related(
        "machine",
        "line__factory",
        "current_classification__reason",
        "current_classification__created_by",
    )
    serializer_class = DowntimeEventSerializer
    factory_path = "line__factory"
    permission_classes = [IsAuthenticated, HasMembership, CanClassifyDowntime]
    pagination_class = EventPagination

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = filter_downtime_events(queryset, self.request)
        return queryset.order_by("started_at", "machine__position", "id")

    @action(detail=True, methods=["get", "post"], url_path="classifications")
    def classifications(self, request: Request, pk: str | None = None) -> Response:
        event = self.get_object()  # 404 outside the user's factories
        if request.method == "GET":
            history = event.classifications.select_related("reason", "created_by")
            return Response(ClassificationSerializer(history, many=True).data)

        payload = ClassificationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        reasons = scope_to_user(DowntimeReason.objects.all(), request.user, "factory")
        reason = reasons.filter(pk=payload.validated_data["reason"]).first()
        if reason is None:
            raise ValidationError({"reason": "Unknown reason."})
        try:
            classification = classify_downtime(
                event, reason, payload.validated_data["comment"], request.user
            )
        except ClassificationError as exc:
            raise ValidationError({"reason": str(exc)}) from None
        return Response(
            ClassificationSerializer(classification).data, status=status.HTTP_201_CREATED
        )


class IncidentViewSet(RequestTimeMixin, TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Line stop incidents. Filters: line, origin, start/end (overlap)."""

    queryset = LineStopIncident.objects.select_related(
        "line__factory", "first_machine"
    ).prefetch_related(
        Prefetch(
            "events",
            queryset=DowntimeEvent.objects.select_related(
                "machine",
                "line__factory",
                "current_classification__reason",
                "current_classification__created_by",
            ),
        )
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


class DowntimeReasonViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """The reason catalogue of the factories you can access. Filter: ?factory=<id>."""

    queryset = DowntimeReason.objects.filter(is_active=True)
    serializer_class = DowntimeReasonSerializer
    factory_path = "factory"
    permission_classes = [IsAuthenticated, HasMembership]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        factory = integer_query_param(self.request, "factory")
        if factory is not None:
            queryset = queryset.filter(factory_id=factory)
        return queryset.order_by("factory_id", "category", "code")
