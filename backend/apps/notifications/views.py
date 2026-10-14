"""Alert rules, alerts, notifications and preferences. Every queryset is tenant-scoped."""

from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.mixins import AuditedModelViewSetMixin
from apps.downtime.filters import choice_query_param
from apps.notifications.evaluators import describe_types
from apps.notifications.models import (
    Alert,
    AlertRule,
    AlertStatus,
    Channel,
    Notification,
    NotificationPreference,
    RuleType,
    Severity,
)
from apps.notifications.serializers import (
    AlertRuleSerializer,
    AlertSerializer,
    NoteSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
)
from apps.notifications.services.actions import (
    AlertActionError,
    acknowledge,
    can_acknowledge,
    can_resolve,
    resolve_manually,
)
from apps.notifications.services.live import queue_unread_count, unread_count
from apps.notifications.services.notify import preference
from apps.organizations.permissions import HasMembership, IsConfigurationManagerOrReadOnly
from apps.organizations.tenancy import TenantScopedViewSetMixin
from apps.organizations.views import integer_query_param
from apps.production.views import EventPagination, aware_datetime_param

STATUS_ORDER = Case(
    When(status=AlertStatus.OPEN, then=Value(0)),
    When(status=AlertStatus.ACKNOWLEDGED, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


class AlertRuleViewSet(AuditedModelViewSetMixin, TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """Alert rules (?factory=, ?line=). Factory managers and platform admins write; audited."""

    queryset = AlertRule.objects.select_related("factory", "line", "machine")
    serializer_class = AlertRuleSerializer
    permission_classes = [IsAuthenticated, HasMembership, IsConfigurationManagerOrReadOnly]
    factory_path = "factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        for param in ("factory", "line"):
            value = integer_query_param(self.request, param)
            if value is not None:
                queryset = queryset.filter(**{f"{param}_id": value})
        return queryset

    @action(detail=False, methods=["get"])
    def types(self, request: Request) -> Response:
        """Each rule type's parameters and defaults (drives the rule form)."""
        return Response(describe_types())


class AlertViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Alerts, open first then newest. Filters: status, severity, type, line, machine,
    start/end (opened in that range)."""

    queryset = Alert.objects.select_related(
        "rule", "factory", "line", "machine", "acknowledged_by", "resolved_by"
    )
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated, HasMembership]
    factory_path = "factory"
    pagination_class = EventPagination

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset
        params = self.request
        status_value = choice_query_param(params, "status", [*AlertStatus.values, "unresolved"])
        if status_value == "unresolved":
            queryset = queryset.exclude(status=AlertStatus.RESOLVED)
        elif status_value:
            queryset = queryset.filter(status=status_value)
        severity = choice_query_param(params, "severity", list(Severity.values))
        if severity:
            queryset = queryset.filter(severity=severity)
        rule_type = choice_query_param(params, "type", list(RuleType.values))
        if rule_type:
            queryset = queryset.filter(rule__rule_type=rule_type)
        for param in ("line", "machine"):
            value = integer_query_param(params, param)
            if value is not None:
                queryset = queryset.filter(**{f"{param}_id": value})
        start, end = aware_datetime_param(params, "start"), aware_datetime_param(params, "end")
        if start is not None:
            queryset = queryset.filter(opened_at__gte=start)
        if end is not None:
            queryset = queryset.filter(opened_at__lt=end)
        return queryset.annotate(status_order=STATUS_ORDER).order_by(
            "status_order", "-opened_at", "-id"
        )

    def _note(self, request: Request) -> str:
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return data.validated_data["note"]

    @action(detail=True, methods=["post"])
    def acknowledge(self, request: Request, pk: str | None = None) -> Response:
        alert = self.get_object()
        if not can_acknowledge(request.user, alert):
            raise PermissionDenied("Your role cannot acknowledge this alert.")
        try:
            alert = acknowledge(alert, request.user, self._note(request))
        except AlertActionError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response(AlertSerializer(alert, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, pk: str | None = None) -> Response:
        alert = self.get_object()
        if not can_resolve(request.user):
            raise PermissionDenied("Only supervisors and managers can resolve alerts.")
        try:
            alert = resolve_manually(alert, request.user, self._note(request))
        except AlertActionError as exc:
            raise ValidationError({"note": str(exc)}) from None
        return Response(AlertSerializer(alert, context={"request": request}).data)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The current user's in-app notifications (?unread=true), newest first."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = EventPagination

    def get_queryset(self) -> QuerySet:
        queryset = Notification.objects.filter(
            user=self.request.user, channel=Channel.IN_APP
        ).select_related(
            "alert__rule",
            "alert__factory",
            "alert__line",
            "alert__machine",
            "alert__acknowledged_by",
            "alert__resolved_by",
        )
        if self.request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset.order_by("-created_at", "-id")

    @action(detail=True, methods=["post"])
    def read(self, request: Request, pk: str | None = None) -> Response:
        notification = self.get_queryset().filter(pk=pk).first()
        if notification is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
            queue_unread_count({request.user.pk})
        return Response({"unread_count": unread_count(request.user.pk)})

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request: Request) -> Response:
        changed = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        if changed:
            queue_unread_count({request.user.pk})
        return Response({"unread_count": 0})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request: Request) -> Response:
        return Response({"unread_count": unread_count(request.user.pk)})


class NotificationPreferenceView(APIView):
    """GET/PATCH /api/v1/me/notification-preferences/"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(NotificationPreferenceSerializer(preference(request.user)).data)

    def patch(self, request: Request) -> Response:
        instance, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
