"""Shared pytest fixtures for all backend tests. Helpers live in tests/helpers.py."""

from typing import Any

import pytest

from tests.helpers import ApiFactory, World, build_world, client_for


@pytest.fixture(autouse=True)
def fast_password_hasher(settings: Any) -> None:
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def world(db: None) -> World:
    """Two organizations with factories, lines, machines and one user per role."""
    return build_world()


@pytest.fixture
def api() -> ApiFactory:
    """`api(user)` returns an API client authenticated with a real JWT for that user."""
    return client_for
