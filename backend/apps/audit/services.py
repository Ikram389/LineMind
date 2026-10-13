from typing import Any

from django.db.models import Model

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations.models import Organization


def record_audit(
    *,
    user: User | None,
    action: str,
    entity: Model,
    organization: Organization | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> AuditLog:
    """Write one audit entry. Call it in the same transaction as the change it describes."""
    return AuditLog.objects.create(
        organization=organization,
        user=user,
        action=action,
        entity_type=type(entity).__name__,
        entity_id=str(entity.pk),
        before=before,
        after=after,
    )
