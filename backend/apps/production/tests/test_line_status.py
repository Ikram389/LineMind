"""GET /api/v1/lines/{id}/status/ and the line status service."""

from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.organizations.models import Machine
from apps.production.services.line_status import get_line_status
from apps.production.tests.events import make_event
from tests.helpers import ApiFactory, World

EVENTS_URL = "/api/v1/events/"


def status_url(world: World) -> str:
    return f"/api/v1/lines/{world.line_a.id}/status/"


def send(sender: APIClient, event_type: str, at: datetime, **extra: object) -> None:
    response = sender.post(EVENTS_URL, make_event(event_type, at=at, **extra), format="json")
    assert response.status_code == 201, response.json()


def machine_entry(body: dict, external_id: str = "M01") -> dict:
    return next(m for m in body["machines"] if m["external_id"] == external_id)


def test_status_lists_machines_with_latest_state_and_count(
    world: World, sender: APIClient, api: ApiFactory, machine_a2: Machine
) -> None:
    now = timezone.now()
    send(sender, "machine_started", now - timedelta(seconds=30))
    send(sender, "production_count_updated", now - timedelta(seconds=20), count=100, rejected=2)
    send(sender, "machine_stopped", now - timedelta(seconds=10), alarm_code="E-204")

    response = api(world.users["analyst"]).get(status_url(world))

    assert response.status_code == 200
    body = response.json()
    assert body["line"] == {"id": world.line_a.id, "name": "Line A1"}
    assert body["stale_after_seconds"] == 60
    assert [m["external_id"] for m in body["machines"]] == ["M01", "M02"]
    m01 = machine_entry(body)
    assert m01["state"] == "stopped"
    assert m01["reported_state"] == "stopped"
    assert m01["alarm_code"] == "E-204"
    assert m01["is_stale"] is False
    assert m01["last_count"]["count"] == 100
    assert m01["last_count"]["rejected"] == 2
    assert m01["last_seen"] == m01["state_since"]


def test_out_of_order_events_use_latest_timestamp(
    world: World, sender: APIClient, api: ApiFactory
) -> None:
    now = timezone.now()
    # The newer event arrives first; the older one arrives afterwards.
    send(sender, "machine_stopped", now - timedelta(seconds=5))
    send(sender, "machine_started", now - timedelta(seconds=40))
    send(sender, "production_count_updated", now - timedelta(seconds=3), count=500)
    send(sender, "production_count_updated", now - timedelta(seconds=30), count=400)

    m01 = machine_entry(api(world.users["analyst"]).get(status_url(world)).json())

    assert m01["state"] == "stopped"
    assert m01["last_count"]["count"] == 500


def test_machine_without_events_is_unknown(
    world: World, api: ApiFactory, machine_a2: Machine
) -> None:
    body = api(world.users["analyst"]).get(status_url(world)).json()

    m02 = machine_entry(body, "M02")
    assert m02["state"] == "unknown"
    assert m02["reported_state"] is None
    assert m02["last_seen"] is None
    assert m02["last_count"] is None
    assert m02["is_stale"] is True


def test_stale_machine_is_reported_unknown_never_running(
    world: World, sender: APIClient, api: ApiFactory
) -> None:
    send(sender, "machine_started", timezone.now() - timedelta(seconds=120))

    m01 = machine_entry(api(world.users["analyst"]).get(status_url(world)).json())

    assert m01["state"] == "unknown"
    assert m01["reported_state"] == "running"
    assert m01["is_stale"] is True


def test_factory_stale_threshold_is_respected(world: World, sender: APIClient) -> None:
    now = timezone.now()
    send(sender, "machine_started", now - timedelta(seconds=120))
    world.factory_a.stale_after_seconds = 300
    world.factory_a.save()
    world.line_a.refresh_from_db()

    status = get_line_status(world.line_a, now=now)

    assert status["machines"][0]["state"] == "running"
    assert status["stale_after_seconds"] == 300


def test_any_event_type_keeps_machine_fresh(world: World, sender: APIClient) -> None:
    now = timezone.now()
    send(sender, "machine_started", now - timedelta(seconds=600))
    send(sender, "production_count_updated", now - timedelta(seconds=5), count=1)

    status = get_line_status(world.line_a, now=now)

    assert status["machines"][0]["state"] == "running"
    assert status["machines"][0]["is_stale"] is False


def test_stale_boundary_uses_threshold(world: World, sender: APIClient) -> None:
    at = timezone.now() - timedelta(seconds=10)
    send(sender, "machine_started", at)

    fresh = get_line_status(world.line_a, now=at + timedelta(seconds=60))
    stale = get_line_status(world.line_a, now=at + timedelta(seconds=61))

    assert fresh["machines"][0]["state"] == "running"
    assert stale["machines"][0]["state"] == "unknown"


def test_sensor_disconnected_is_unknown_until_real_state_event(
    world: World, sender: APIClient
) -> None:
    now = timezone.now()
    send(sender, "machine_started", now - timedelta(seconds=30))
    send(sender, "sensor_disconnected", now - timedelta(seconds=20))
    send(sender, "sensor_reconnected", now - timedelta(seconds=10))

    after_reconnect = get_line_status(world.line_a, now=now)["machines"][0]
    assert after_reconnect["state"] == "unknown"
    assert after_reconnect["is_stale"] is False

    send(sender, "machine_started", now - timedelta(seconds=5))
    assert get_line_status(world.line_a, now=now)["machines"][0]["state"] == "running"


def test_status_isolation(world: World, api: ApiFactory) -> None:
    other = api(world.users["other_manager"]).get(status_url(world))
    limited = api(world.users["limited_operator"]).get(f"/api/v1/lines/{world.line_b.id}/status/")
    anonymous = APIClient().get(status_url(world))

    assert other.status_code == 404
    assert limited.status_code == 404
    assert anonymous.status_code == 401
