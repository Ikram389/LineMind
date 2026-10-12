from rest_framework.routers import SimpleRouter

from apps.organizations.views import FactoryViewSet, MachineViewSet, ProductionLineViewSet

router = SimpleRouter()
router.register("factories", FactoryViewSet, basename="factory")
router.register("lines", ProductionLineViewSet, basename="line")
router.register("machines", MachineViewSet, basename="machine")

urlpatterns = router.urls
