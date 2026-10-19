from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.assistant.views import AskView, ConversationViewSet, FeedbackView, StatusView

router = DefaultRouter()
router.register("assistant/conversations", ConversationViewSet, basename="assistant-conversation")

urlpatterns = [
    path("assistant/status/", StatusView.as_view(), name="assistant-status"),
    path("assistant/conversations/<int:pk>/ask/", AskView.as_view(), name="assistant-ask"),
    path(
        "assistant/messages/<int:pk>/feedback/", FeedbackView.as_view(), name="assistant-feedback"
    ),
    *router.urls,
]
