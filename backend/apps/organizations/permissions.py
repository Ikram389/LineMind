"""Reusable DRF permission classes based on the user's Membership.

These decide *what a user may do*. *Which rows they may see* is decided by
`tenancy.py`; always use both.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.organizations.models import Role
from apps.organizations.tenancy import get_membership

# Roles allowed to change configuration (factories, lines, machines).
CONFIGURATION_WRITE_ROLES: frozenset[str] = frozenset({Role.PLATFORM_ADMIN, Role.FACTORY_MANAGER})


class HasMembership(BasePermission):
    """The user belongs to an organization."""

    message = "Your account is not a member of any organization."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return get_membership(request.user) is not None


class IsConfigurationManagerOrReadOnly(BasePermission):
    """Any member may read; only platform admins and factory managers may write."""

    message = "Only factory managers and platform admins can change this."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return True
        membership = get_membership(request.user)
        return membership is not None and membership.role in CONFIGURATION_WRITE_ROLES


class CanCreateFactory(BasePermission):
    """Creating a factory requires access to all factories of the organization."""

    message = "Only users with access to all factories can create a factory."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) != "create":
            return True
        membership = get_membership(request.user)
        return membership is not None and membership.all_factories


class AllFactoriesRequiredForWrites(BasePermission):
    """Organization-wide data (e.g. products) affects every factory: writing it requires
    access to all factories."""

    message = "Only users with access to all factories can change organization-wide data."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return True
        membership = get_membership(request.user)
        return membership is not None and membership.all_factories
