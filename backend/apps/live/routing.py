from django.urls import path

from apps.live.consumers import LineConsumer, UserConsumer

websocket_urlpatterns = [
    path("ws/lines/<int:line_id>/", LineConsumer.as_asgi()),
    path("ws/me/", UserConsumer.as_asgi()),
]
