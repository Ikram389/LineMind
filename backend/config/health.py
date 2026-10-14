"""Health check endpoint: whether the backend, its database and the alert engine work."""

from django.db import DatabaseError, connection
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.notifications.services.heartbeat import engine_health


def database_is_reachable() -> bool:
    """Run a trivial query against PostgreSQL; return False if it fails."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return False
    return True


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    if not database_is_reachable():
        return Response(
            {"status": "error", "database": "error"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    # The backend works; the alert engine (Celery) may still be stopped: say so.
    engine = engine_health(timezone.now())
    return Response(
        {
            "status": "ok",
            "database": "ok",
            "alerts": engine["status"],
            "alerts_last_heartbeat": engine["last_heartbeat"],
            "alerts_worker_last_task": engine["worker_last_task"],
        }
    )
