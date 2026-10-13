from django.contrib import admin
from django.urls import include, path

from config.health import health

admin.site.site_header = "LineMind admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", health, name="health"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.organizations.urls")),
    path("api/v1/", include("apps.production.urls")),
    path("api/v1/", include("apps.downtime.urls")),
]
