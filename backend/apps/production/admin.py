from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.production.models import IngestedEvent, LineApiKey, MachineStateEvent, ProductionEvent
from apps.production.services.api_keys import revoke


class ReadOnlyObservationAdmin(admin.ModelAdmin):
    """Raw observations can be viewed but never added, changed or deleted."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(IngestedEvent)
class IngestedEventAdmin(ReadOnlyObservationAdmin):
    list_display = ["timestamp", "event_type", "machine", "alarm_code", "count", "received_at"]
    list_filter = ["event_type", "machine__line", "machine"]
    search_fields = ["event_id", "machine__external_id", "alarm_code"]
    date_hierarchy = "timestamp"
    list_select_related = ["machine"]


@admin.register(MachineStateEvent)
class MachineStateEventAdmin(ReadOnlyObservationAdmin):
    list_display = ["timestamp", "machine", "state", "alarm_code", "source", "received_at"]
    list_filter = ["state", "machine__line", "machine"]
    search_fields = ["event_id", "machine__external_id", "alarm_code"]
    date_hierarchy = "timestamp"
    list_select_related = ["machine"]


@admin.register(ProductionEvent)
class ProductionEventAdmin(ReadOnlyObservationAdmin):
    list_display = ["timestamp", "machine", "count", "rejected", "received_at"]
    list_filter = ["machine__line", "machine"]
    search_fields = ["event_id", "machine__external_id"]
    date_hierarchy = "timestamp"
    list_select_related = ["machine"]


@admin.register(LineApiKey)
class LineApiKeyAdmin(admin.ModelAdmin):
    """Keys are created with `manage.py create_line_api_key`; here they can be revoked."""

    list_display = ["name", "line", "prefix", "created_at", "last_used_at", "revoked_at"]
    list_filter = ["line__factory__organization", "line"]
    search_fields = ["name", "prefix", "line__name"]
    fields = ["line", "name", "prefix", "created_at", "last_used_at", "revoked_at"]
    readonly_fields = fields
    actions = ["revoke_keys"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @admin.action(description="Revoke selected keys")
    def revoke_keys(self, request: HttpRequest, queryset: QuerySet[LineApiKey]) -> None:
        active = queryset.filter(revoked_at__isnull=True)
        count = active.count()
        for api_key in active:
            revoke(api_key)
        self.message_user(request, f"Revoked {count} key(s).", messages.SUCCESS)
