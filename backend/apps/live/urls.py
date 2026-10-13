from django.urls import path

from apps.live.views import WsTicketView

urlpatterns = [
    path("ws-ticket/", WsTicketView.as_view(), name="ws-ticket"),
]
