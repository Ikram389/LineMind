"""Health check endpoint: tells the caller whether the backend and its database work."""

from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


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
    if database_is_reachable():
        return Response({"status": "ok", "database": "ok"})
    return Response(
        {"status": "error", "database": "error"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
