from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.production.planning_views import (
    ProductCycleTimeViewSet,
    ProductionOrderViewSet,
    ProductViewSet,
    ShiftBreakViewSet,
    ShiftViewSet,
)
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

router = SimpleRouter()
router.register("shifts", ShiftViewSet, basename="shift")
router.register("shift-breaks", ShiftBreakViewSet, basename="shift-break")
router.register("products", ProductViewSet, basename="product")
router.register("product-cycle-times", ProductCycleTimeViewSet, basename="product-cycle-time")
router.register("production-orders", ProductionOrderViewSet, basename="production-order")
urlpatterns += router.urls
