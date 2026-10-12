"""Fixtures for production tests (shared ones are in backend/conftest.py)."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Machine
from apps.production.services.api_keys import create_line_api_key
from tests.helpers import World, create_machine


@pytest.fixture
def line_a_key(world: World) -> str:
    """Plain-text API key for world.line_a (machine M01 at position 1)."""
    _, raw_key = create_line_api_key(world.line_a, "Test sender")
    return raw_key


@pytest.fixture
def key_client() -> Callable[[str | None], APIClient]:
    """`key_client(raw_key)` returns a client sending `Authorization: Api-Key <raw_key>`."""

    def make(raw_key: str | None) -> APIClient:
        client = APIClient()
        if raw_key is not None:
            client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
        return client

    return make


@pytest.fixture
def sender(key_client: Callable[[str | None], APIClient], line_a_key: str) -> APIClient:
    """A client authenticated with line A's key."""
    return key_client(line_a_key)


@pytest.fixture
def machine_a2(world: World) -> Machine:
    return create_machine(world.line_a, "M02", 2)
