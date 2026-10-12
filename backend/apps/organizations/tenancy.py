"""Tenant isolation: the single place that decides which data a user may see.

Every query that returns organization data must go through these helpers
(see "How to apply tenant isolation" in CLAUDE.md):

- Viewsets: inherit `TenantScopedViewSetMixin` and set `factory_path`.
- Other code (services, serializer fields, jobs): call `scope_to_user()`.

Objects outside the user's scope are filtered out of the queryset, so they
simply do not exist for that user: lists omit them and direct IDs give 404.
"""

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from rest_framework.generics import GenericAPIView

from apps.accounts.models import User
from apps.organizations.models import Factory, Membership


def get_membership(user: User | AnonymousUser) -> Membership | None:
    """Return the user's membership, or None (anonymous or not in any organization)."""
    if not user.is_authenticated:
        return None
    try:
        return user.membership
    except Membership.DoesNotExist:
        return None


def permitted_factories(user: User | AnonymousUser) -> QuerySet[Factory]:
    """Factories the user may access.

    Always limited to the user's own organization, even if a listed factory
    somehow belongs to another one.
    """
    membership = get_membership(user)
    if membership is None:
        return Factory.objects.none()
    factories = Factory.objects.filter(organization_id=membership.organization_id)
    if membership.all_factories:
        return factories
    return factories.filter(memberships=membership)


def scope_to_user[M: Model](
    queryset: QuerySet[M], user: User | AnonymousUser, factory_path: str
) -> QuerySet[M]:
    """Keep only rows that belong to a factory the user may access.

    `factory_path` is the ORM path from the queryset's model to its Factory:
    "pk" for Factory itself, "factory" for ProductionLine, "line__factory" for
    Machine, "machine__line__factory" for something attached to a machine, ...
    """
    return queryset.filter(**{f"{factory_path}__in": permitted_factories(user)})


class TenantScopedViewSetMixin(GenericAPIView):
    """Filters a viewset's queryset to the requesting user's permitted factories.

    Subclasses must set `factory_path` (see `scope_to_user`).
    """

    factory_path: str = ""

    def get_queryset(self) -> QuerySet:
        if not self.factory_path:
            raise ImproperlyConfigured(f"{type(self).__name__} must set `factory_path`.")
        return scope_to_user(super().get_queryset(), self.request.user, self.factory_path)
