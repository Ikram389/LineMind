from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import MeView

urlpatterns = [
    # POST {"email", "password"} -> {"access", "refresh"}
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    # POST {"refresh"} -> {"access"}
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
]
