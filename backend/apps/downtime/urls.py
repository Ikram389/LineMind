from rest_framework.routers import SimpleRouter

from apps.downtime.views import DowntimeEventViewSet, DowntimeReasonViewSet, IncidentViewSet

router = SimpleRouter()
router.register("downtime-events", DowntimeEventViewSet, basename="downtime-event")
router.register("incidents", IncidentViewSet, basename="incident")
router.register("downtime-reasons", DowntimeReasonViewSet, basename="downtime-reason")

urlpatterns = router.urls
