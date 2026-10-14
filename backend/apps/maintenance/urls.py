from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.maintenance.views import MaintenanceActionViewSet, MaintenanceExportView

router = SimpleRouter()
router.register("maintenance-actions", MaintenanceActionViewSet, basename="maintenance-action")

urlpatterns = [
    path(
        "maintenance-actions/export.csv",
        MaintenanceExportView.as_view(),
        name="maintenance-export",
    ),
    *router.urls,
]
