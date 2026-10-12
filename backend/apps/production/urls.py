from django.urls import path

from apps.production.views import (
    EventBatchView,
    EventView,
    LineStatusView,
    MachineStateEventListView,
    ProductionEventListView,
)

urlpatterns = [
    path("events/", EventView.as_view(), name="event-ingest"),
    path("events/batch/", EventBatchView.as_view(), name="event-ingest-batch"),
    path(
        "machines/<int:machine_id>/state-events/",
        MachineStateEventListView.as_view(),
        name="machine-state-events",
    ),
    path(
        "machines/<int:machine_id>/production-events/",
        ProductionEventListView.as_view(),
        name="machine-production-events",
    ),
    path("lines/<int:line_id>/status/", LineStatusView.as_view(), name="line-status"),
]
