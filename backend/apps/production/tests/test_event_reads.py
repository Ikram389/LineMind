"""GET /api/v1/machines/{id}/state-events/ and /production-events/."""

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.production.tests.events import make_event
from tests.helpers import ApiFactory, World

EVENTS_URL = "/api/v1/events/"


def state_url(machine_id: int) -> str:
    return f"/api/v1/machines/{machine_id}/state-events/"


def production_url(machine_id: int) -> str:
    return f"/api/v1/machines/{machine_id}/production-events/"


@pytest.fixture
def base_time() -> datetime:
    return (timezone.now() - timedelta(hours=1)).replace(microsecond=0)


@pytest.fixture
def stored(world: World, sender: APIClient, base_time: datetime) -> None:
    """Sends events out of order: minutes 20, 0, 10 (states) and 15, 5 (counts)."""
    for minute, event_type in [
        (20, "machine_stopped"),
        (0, "machine_started"),
        (10, "machine_blocked"),
    ]:
        sender.post(
            EVENTS_URL,
            make_event(event_type, at=base_time + timedelta(minutes=minute)),
            format="json",
        )
    for minute, count in [(15, 150), (5, 50)]:
        sender.post(
            EVENTS_URL,
            make_event(
                "production_count_updated", at=base_time + timedelta(minutes=minute), count=count
            ),
            format="json",
        )


def test_state_events_are_ordered_by_timestamp(world: World, api: ApiFactory, stored: None) -> None:
    response = api(world.users["analyst"]).get(state_url(world.machine_a.id))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert [e["state"] for e in body["results"]] == ["running", "blocked", "stopped"]


def test_production_events_are_ordered_by_timestamp(
    world: World, api: ApiFactory, stored: None
) -> None:
    body = api(world.users["analyst"]).get(production_url(world.machine_a.id)).json()

    assert [e["count"] for e in body["results"]] == [50, 150]


def test_time_range_filter_includes_start_excludes_end(
    world: World, api: ApiFactory, stored: None, base_time: datetime
) -> None:
    start = (base_time + timedelta(minutes=10)).isoformat()
    end = (base_time + timedelta(minutes=20)).isoformat()

    response = api(world.users["analyst"]).get(
        state_url(world.machine_a.id), {"start": start, "end": end}
    )

    assert [e["state"] for e in response.json()["results"]] == ["blocked"]


@pytest.mark.parametrize("value", ["2026-10-12T10:00:00", "not-a-date"])
def test_invalid_time_filter_returns_400(
    world: World, api: ApiFactory, stored: None, value: str
) -> None:
    response = api(world.users["analyst"]).get(state_url(world.machine_a.id), {"start": value})

    assert response.status_code == 400
    assert "start" in response.json()


def test_pagination_limit(world: World, api: ApiFactory, stored: None) -> None:
    body = api(world.users["analyst"]).get(state_url(world.machine_a.id), {"limit": 2}).json()

    assert body["count"] == 3
    assert len(body["results"]) == 2
    assert body["next"] is not None


@pytest.mark.parametrize("url_for", [state_url, production_url])
def test_other_organization_gets_404(
    world: World, api: ApiFactory, stored: None, url_for: Callable[[int], str]
) -> None:
    response = api(world.users["other_manager"]).get(url_for(world.machine_a.id))

    assert response.status_code == 404


@pytest.mark.parametrize("url_for", [state_url, production_url])
def test_limited_user_cannot_read_other_factory_machine(
    world: World, api: ApiFactory, url_for: Callable[[int], str]
) -> None:
    response = api(world.users["limited_operator"]).get(url_for(world.machine_b.id))

    assert response.status_code == 404


@pytest.mark.parametrize("url_for", [state_url, production_url])
def test_unauthenticated_gets_401(world: World, url_for: Callable[[int], str]) -> None:
    assert APIClient().get(url_for(world.machine_a.id)).status_code == 401


def test_unknown_machine_gets_404(world: World, api: ApiFactory) -> None:
    assert api(world.users["analyst"]).get(state_url(999999)).status_code == 404
