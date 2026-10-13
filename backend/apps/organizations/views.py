from typing import Any

from django.db.models import Model, ProtectedError, QuerySet
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from apps.audit.mixins import AuditedModelViewSetMixin
from apps.organizations.models import Factory, Machine, ProductionLine
from apps.organizations.permissions import (
    CanCreateFactory,
    HasMembership,
    IsConfigurationManagerOrReadOnly,
)
from apps.organizations.serializers import (
    FactorySerializer,
    MachineSerializer,
    ProductionLineSerializer,
)
from apps.organizations.tenancy import TenantScopedViewSetMixin, get_membership


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This object still has dependent records."
    default_code = "conflict"


def integer_query_param(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({name: "Must be an integer."}) from None


class ProtectedDeleteMixin:
    """Deleting something that still has dependent records answers 409 Conflict."""

    def perform_destroy(self, instance: Model) -> None:
        try:
            instance.delete()
        except ProtectedError:
            name = instance._meta.verbose_name
            raise Conflict(
                f"This {name} still has dependent records. Delete or move them first."
            ) from None


class HierarchyViewSet(
    AuditedModelViewSetMixin,  # first: audits inside the same transaction as the change
    ProtectedDeleteMixin,
    TenantScopedViewSetMixin,
    viewsets.ModelViewSet,
):
    """Shared behaviour for factories, lines and machines (every change is audited)."""

    permission_classes = [IsAuthenticated, HasMembership, IsConfigurationManagerOrReadOnly]


class FactoryViewSet(HierarchyViewSet):
    queryset = Factory.objects.all()
    serializer_class = FactorySerializer
    factory_path = "pk"
    permission_classes = [*HierarchyViewSet.permission_classes, CanCreateFactory]

    def create_kwargs(self) -> dict[str, Any]:
        membership = get_membership(self.request.user)
        assert membership is not None  # guaranteed by HasMembership
        return {"organization": membership.organization}


class ProductionLineViewSet(HierarchyViewSet):
    """Lines; filter with ?factory=<id>."""

    queryset = ProductionLine.objects.all()
    serializer_class = ProductionLineSerializer
    factory_path = "factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        factory_id = integer_query_param(self.request, "factory")
        if factory_id is not None:
            queryset = queryset.filter(factory_id=factory_id)
        return queryset


class MachineViewSet(HierarchyViewSet):
    """Machines, ordered by position; filter with ?line=<id>."""

    queryset = Machine.objects.all()
    serializer_class = MachineSerializer
    factory_path = "line__factory"

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        line_id = integer_query_param(self.request, "line")
        if line_id is not None:
            queryset = queryset.filter(line_id=line_id)
        return queryset
