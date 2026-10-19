"""Superuser tools: turn the assistant on per organization (audited), read traces."""

from typing import Any

from django.contrib import admin
from django.db import transaction
from django.http import HttpRequest

from apps.assistant.models import AssistantSettings, Conversation, Message, ToolCall
from apps.audit.mixins import snapshot
from apps.audit.services import record_audit


@admin.register(AssistantSettings)
class AssistantSettingsAdmin(admin.ModelAdmin):
    list_display = ["organization", "enabled", "daily_question_limit", "updated_at"]
    list_filter = ["enabled"]

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        with transaction.atomic():
            before = snapshot(AssistantSettings.objects.get(pk=obj.pk)) if change else None
            super().save_model(request, obj, form, change)
            record_audit(
                user=request.user,  # type: ignore[arg-type]
                action="assistantsettings.updated" if change else "assistantsettings.created",
                entity=obj,
                organization=obj.organization,
                before=before,
                after=snapshot(obj),
            )


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class ToolCallInline(admin.TabularInline):
    model = ToolCall
    extra = 0
    can_delete = False
    fields = ["order", "name", "arguments", "invalid", "error", "duration_ms"]
    readonly_fields = fields


@admin.register(Message)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ["id", "conversation", "role", "status", "model", "duration_ms", "created_at"]
    list_filter = ["role", "status", "model"]
    inlines = [ToolCallInline]


@admin.register(Conversation)
class ConversationAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "organization", "title", "updated_at"]
