"""Audit log of changes to classifications and configuration (CLAUDE.md rule 8).

Entries are append-only: they can be created but never changed or deleted
through the ORM instance.
"""

from typing import Any

from django.conf import settings
from django.db import models

from apps.organizations.models import Organization


class AuditLogImmutableError(Exception):
    pass


class AuditLog(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=100, help_text="e.g. 'downtime.classified'")
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M:%S} {self.action} {self.entity_type}#{self.entity_id}"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AuditLogImmutableError("Audit log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise AuditLogImmutableError("Audit log entries cannot be deleted.")
