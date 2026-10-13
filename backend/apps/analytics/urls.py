from django.urls import path

from apps.analytics.views import LineOEEView

urlpatterns = [
    path("lines/<int:line_id>/oee/", LineOEEView.as_view(), name="line-oee"),
]
