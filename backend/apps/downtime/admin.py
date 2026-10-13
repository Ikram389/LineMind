from django.contrib import admin
from django.http import HttpRequest

from apps.downtime.models import (
    DowntimeClassification,
    DowntimeEvent,
    DowntimeReason,
    LineStopIncident,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Derived data and history: view only."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


class ClassificationInline(admin.TabularInline):
    model = DowntimeClassification
    fk_name = "downtime_event"
    extra = 0
    fields = ["created_at", "reason", "comment", "source", "created_by"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(DowntimeEvent)
class DowntimeEventAdmin(ReadOnlyAdmin):
    list_display = [
        "started_at",
        "machine",
        "category",
        "ended_at",
        "alarm_code",
        "is_first_stop",
        "incident",
        "current_classification",
        "is_obsolete",
    ]
    list_filter = ["category", "is_first_stop", "is_obsolete", "line"]
    search_fields = ["machine__external_id", "alarm_code", "start_event_id"]
    date_hierarchy = "started_at"
    list_select_related = ["machine", "incident", "current_classification__reason"]
    inlines = [ClassificationInline]


class IncidentEventInline(admin.TabularInline):
    model = DowntimeEvent
    fk_name = "incident"
    extra = 0
    fields = ["started_at", "machine", "category", "ended_at", "is_first_stop", "alarm_code"]
    readonly_fields = fields
    can_delete = False
    ordering = ["started_at"]

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(LineStopIncident)
class LineStopIncidentAdmin(ReadOnlyAdmin):
    list_display = ["started_at", "line", "ended_at", "origin", "first_machine"]
    list_filter = ["origin", "line"]
    date_hierarchy = "started_at"
    inlines = [IncidentEventInline]


@admin.register(DowntimeClassification)
class DowntimeClassificationAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "downtime_event", "reason", "source", "created_by"]
    list_filter = ["source", "reason__category"]
    search_fields = ["comment", "created_by__email", "reason__code"]


@admin.register(DowntimeReason)
class DowntimeReasonAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "factory", "is_active"]
    list_filter = ["factory", "category", "is_active"]
    search_fields = ["code", "name"]
