"""CRUD for shifts, breaks, products, cycle-time overrides and production orders.

Reads: any member (within their factories / organization).
Writes: factory managers and platform admins; every change is audited.
"""

from typing import Any

from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.audit.mixins import AuditedModelViewSetMixin
from apps.organizations.permissions import (
    AllFactoriesRequiredForWrites,
    HasMembership,
    IsConfigurationManagerOrReadOnly,
)
from apps.organizations.tenancy import (
    OrganizationScopedViewSetMixin,
    TenantScopedViewSetMixin,
    get_membership,
)
from apps.organizations.views import ProtectedDeleteMixin, integer_query_param
from apps.production.models import (
    OrderStatus,
    Product,
    ProductionOrder,
    ProductLineCycleTime,
    Shift,
    ShiftBreak,
)
from apps.production.planning_serializers import (
    ProductCycleTimeSerializer,
    ProductionOrderSerializer,
    ProductSerializer,
    ShiftBreakSerializer,
    ShiftSerializer,
)
from apps.production.views import aware_datetime_param

CONFIG_PERMISSIONS = [IsAuthenticated, HasMembership, IsConfigurationManagerOrReadOnly]


class ConfigurationViewSet(AuditedModelViewSetMixin, ProtectedDeleteMixin, viewsets.ModelViewSet):
    permission_classes = CONFIG_PERMISSIONS


class ShiftViewSet(TenantScopedViewSetMixin, ConfigurationViewSet):
    """Shifts; filter with ?factory=<id>."""

    queryset = Shift.objects.prefetch_related("breaks")
    serializer_class = ShiftSerializer
    factory_path = "factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        factory = integer_query_param(self.request, "factory")
        return queryset if factory is None else queryset.filter(factory_id=factory)


class ShiftBreakViewSet(TenantScopedViewSetMixin, ConfigurationViewSet):
    """Shift breaks; filter with ?shift=<id>."""

    queryset = ShiftBreak.objects.select_related("shift")
    serializer_class = ShiftBreakSerializer
    factory_path = "shift__factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        shift = integer_query_param(self.request, "shift")
        return queryset if shift is None else queryset.filter(shift_id=shift)


class ProductViewSet(OrganizationScopedViewSetMixin, ConfigurationViewSet):
    """Products are shared by the whole organization."""

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [*CONFIG_PERMISSIONS, AllFactoriesRequiredForWrites]

    def create_kwargs(self) -> dict[str, Any]:
        membership = get_membership(self.request.user)
        assert membership is not None  # guaranteed by HasMembership
        return {"organization": membership.organization}


class ProductCycleTimeViewSet(TenantScopedViewSetMixin, ConfigurationViewSet):
    """Line-specific ideal cycle times; filter with ?line=<id> or ?product=<id>."""

    queryset = ProductLineCycleTime.objects.select_related("product", "line")
    serializer_class = ProductCycleTimeSerializer
    factory_path = "line__factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        for param in ("line", "product"):
            value = integer_query_param(self.request, param)
            if value is not None:
                queryset = queryset.filter(**{f"{param}_id": value})
        return queryset


class ProductionOrderViewSet(TenantScopedViewSetMixin, ConfigurationViewSet):
    """Production orders; filters: ?line=, ?status=, ?start=&end= (overlap)."""

    queryset = ProductionOrder.objects.select_related("product", "line")
    serializer_class = ProductionOrderSerializer
    factory_path = "line__factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        line = integer_query_param(self.request, "line")
        if line is not None:
            queryset = queryset.filter(line_id=line)
        status = self.request.query_params.get("status")
        if status in OrderStatus.values:
            queryset = queryset.filter(status=status)
        start = aware_datetime_param(self.request, "start")
        end = aware_datetime_param(self.request, "end")
        if start is not None:
            queryset = queryset.filter(scheduled_end__gt=start)
        if end is not None:
            queryset = queryset.filter(scheduled_start__lt=end)
        return queryset.order_by("scheduled_start", "id")
