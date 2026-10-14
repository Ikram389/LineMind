from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.notifications.views import (
    AlertRuleViewSet,
    AlertViewSet,
    NotificationPreferenceView,
    NotificationViewSet,
)

router = SimpleRouter()
router.register("alert-rules", AlertRuleViewSet, basename="alert-rule")
router.register("alerts", AlertViewSet, basename="alert")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path(
        "me/notification-preferences/",
        NotificationPreferenceView.as_view(),
        name="notification-preferences",
    ),
    *router.urls,
]
