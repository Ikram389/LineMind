from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.downtime.views import (
    DowntimeEventViewSet,
    DowntimeExportView,
    DowntimeReasonViewSet,
    IncidentViewSet,
    ParetoView,
    RecurringView,
    SummaryView,
)

router = SimpleRouter()
router.register("downtime-events", DowntimeEventViewSet, basename="downtime-event")
router.register("incidents", IncidentViewSet, basename="incident")
router.register("downtime-reasons", DowntimeReasonViewSet, basename="downtime-reason")

urlpatterns = [
    path("downtime-events/export.csv", DowntimeExportView.as_view(), name="downtime-export"),
    path("downtime/pareto/", ParetoView.as_view(), name="downtime-pareto"),
    path("downtime/summary/", SummaryView.as_view(), name="downtime-summary"),
    path("downtime/recurring/", RecurringView.as_view(), name="downtime-recurring"),
    *router.urls,
]
