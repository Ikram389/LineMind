"""Write an AuditLog entry for every create, update and delete made through a viewset.

Use it on every viewset that changes configuration (CLAUDE.md rule 8). The audit
entry is written in the same transaction as the change: if the change fails,
there is no entry; if the entry cannot be written, the change is rolled back.
"""

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Model
from django.forms.models import model_to_dict
from rest_framework.generics import GenericAPIView
from rest_framework.serializers import BaseSerializer

from apps.audit.services import record_audit
from apps.organizations.tenancy import get_membership


def snapshot(instance: Model) -> dict[str, Any]:
    """The instance's fields as plain JSON values (dates, decimals and times as strings)."""
    data = model_to_dict(instance)
    data["id"] = instance.pk
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


class AuditedModelViewSetMixin(GenericAPIView):
    def create_kwargs(self) -> dict[str, Any]:
        """Extra fields set by the server on create (e.g. the user's organization)."""
        return {}

    def perform_create(self, serializer: BaseSerializer) -> None:
        with transaction.atomic():
            instance = serializer.save(**self.create_kwargs())
            self._audit("created", instance, None, snapshot(instance))

    def perform_update(self, serializer: BaseSerializer) -> None:
        with transaction.atomic():
            before = snapshot(serializer.instance)
            instance = serializer.save()
            self._audit("updated", instance, before, snapshot(instance))

    def perform_destroy(self, instance: Model) -> None:
        with transaction.atomic():
            self._audit("deleted", instance, snapshot(instance), None)
            super().perform_destroy(instance)  # type: ignore[misc]

    def _audit(
        self,
        action: str,
        instance: Model,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        membership = get_membership(self.request.user)
        record_audit(
            user=self.request.user,
            action=f"{instance._meta.model_name}.{action}",
            entity=instance,
            organization=membership.organization if membership else None,
            before=before,
            after=after,
        )
