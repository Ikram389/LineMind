"""Who is told about an alert: active users of the alert's organization, with access to
its factory, whose role is in the given roles. Tenant rules always apply."""

from collections.abc import Iterable

from django.db.models import Q, QuerySet

from apps.accounts.models import User
from apps.organizations.models import Factory


def recipients(factory: Factory, roles: Iterable[str]) -> QuerySet[User]:
    roles = list(roles)
    if not roles:
        return User.objects.none()
    return (
        User.objects.filter(
            is_active=True,
            membership__organization_id=factory.organization_id,
            membership__role__in=roles,
        )
        .filter(Q(membership__all_factories=True) | Q(membership__factories=factory))
        .distinct()
        .order_by("pk")
    )
