from django.urls import path

from apps.live.consumers import LineConsumer

websocket_urlpatterns = [
    path("ws/lines/<int:line_id>/", LineConsumer.as_asgi()),
]
