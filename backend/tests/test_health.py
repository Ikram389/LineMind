from unittest.mock import patch

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient

HEALTH_URL = "/api/v1/health/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_health_reports_ok_when_database_is_reachable(client: APIClient) -> None:
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_error_when_database_is_unreachable(client: APIClient) -> None:
    with patch(
        "config.health.connection.cursor",
        side_effect=OperationalError("connection refused"),
    ):
        response = client.get(HEALTH_URL)

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}


def test_health_rejects_post(client: APIClient) -> None:
    response = client.post(HEALTH_URL)

    assert response.status_code == 405
