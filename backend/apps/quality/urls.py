from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.quality.views import (
    DefectTypeViewSet,
    InspectionResultExportView,
    InspectionResultViewSet,
    InspectionStationViewSet,
    QualityParetoView,
    QualitySummaryView,
    QualityTrendView,
)

router = SimpleRouter()
router.register("defect-types", DefectTypeViewSet, basename="defect-type")
router.register("inspection-stations", InspectionStationViewSet, basename="inspection-station")
router.register("inspection-results", InspectionResultViewSet, basename="inspection-result")

urlpatterns = [
    path(
        "inspection-results/export.csv",
        InspectionResultExportView.as_view(),
        name="inspection-result-export",
    ),
    path("quality/summary/", QualitySummaryView.as_view(), name="quality-summary"),
    path("quality/pareto/", QualityParetoView.as_view(), name="quality-pareto"),
    path("quality/trend/", QualityTrendView.as_view(), name="quality-trend"),
    *router.urls,
]
