"""REST additions for the dashboard: current shift and the richer line status."""

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from django.utils import timezone

from apps.production.models import Shift
from tests.helpers import ApiFactory, World
from tests.lines import Bottling


def status(api: ApiFactory, world: World, bottling: Bottling) -> dict:
    return (
        api(world.users["production_supervisor"])
        .get(f"/api/v1/lines/{bottling.line.id}/status/")
        .json()
    )


def machine(body: dict, external_id: str) -> dict:
    return next(m for m in body["machines"] if m["external_id"] == external_id)


def all_day_shift(bottling: Bottling) -> Shift:
    # start == end: a 24-hour shift, so "now" is always inside a shift.
    return Shift.objects.create(
        factory=bottling.line.factory, name="All day", start_time=time(0), end_time=time(0)
    )


def test_state_since_is_when_the_current_state_began(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    base = timezone.now() - timedelta(seconds=40)
    send("M05", "machine_started", base)
    send("M05", "machine_stopped", base + timedelta(seconds=10), alarm_code="E-204")
    send("M05", "machine_stopped", base + timedelta(seconds=20), alarm_code="E-205")  # repeat

    m05 = machine(status(api, world, bottling), "M05")

    assert m05["state"] == "stopped"
    assert m05["state_since"] == (base + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    assert m05["alarm_code"] == "E-205"  # the latest report of the current stop
    assert m05["last_alarm_code"] == "E-205"


def test_last_alarm_stays_available_after_restart(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    base = timezone.now() - timedelta(seconds=40)
    send("M05", "machine_stopped", base, alarm_code="E-204")
    send("M05", "machine_started", base + timedelta(seconds=20))

    m05 = machine(status(api, world, bottling), "M05")

    assert m05["state"] == "running"
    assert m05["alarm_code"] is None
    assert m05["last_alarm_code"] == "E-204"
    assert m05["last_alarm_at"].startswith(base.strftime("%Y-%m-%dT%H:%M:%S"))


def test_stale_machine_state_since_is_when_data_stopped(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    last = timezone.now() - timedelta(minutes=5)
    send("M05", "machine_started", last)

    m05 = machine(status(api, world, bottling), "M05")

    assert m05["state"] == "unknown"
    assert m05["reported_state"] == "running"
    assert m05["state_since"] == last.isoformat().replace("+00:00", "Z")


def test_shift_count_since_shift_start_with_reset(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    all_day_shift(bottling)
    now = timezone.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    before_shift = midnight - timedelta(minutes=5)
    send("M06", "production_count_updated", before_shift, count=5000, rejected=10)
    for offset, count, rejected in [
        (30, 5100, 11),
        (20, 5300, 12),
        (10, 40, 0),
    ]:  # reset at the end
        moment = max(midnight + timedelta(seconds=1), now - timedelta(seconds=offset))
        send("M06", "production_count_updated", moment, count=count, rejected=rejected)

    m06 = machine(status(api, world, bottling), "M06")

    assert m06["shift_count"] == 100 + 200 + 40
    assert m06["shift_rejected"] == 1 + 1 + 0


def test_no_shift_means_no_shift_count(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    send("M06", "production_count_updated", timezone.now(), count=10, rejected=0)

    body = status(api, world, bottling)

    assert body["current_shift_start"] is None
    assert machine(body, "M06")["shift_count"] is None


def test_open_incident_in_status(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    base = timezone.now() - timedelta(seconds=30)
    send("M05", "machine_stopped", base, alarm_code="E-204")
    send("M04", "machine_blocked", base + timedelta(seconds=3))

    incident = status(api, world, bottling)["open_incident"]

    assert incident["first_observed_stop"]["machines"][0]["external_id"] == "M05"
    assert incident["first_observed_stop"]["alarm_code"] == "E-204"
    assert [m["external_id"] for m in incident["affected_machines"]] == ["M05", "M04"]
    assert incident["ended_at"] is None


def test_current_shift_endpoint(bottling: Bottling, world: World, api: ApiFactory) -> None:
    factory = bottling.line.factory  # UTC
    client = api(world.users["production_supervisor"])
    url = f"/api/v1/factories/{factory.id}/current-shift/"

    assert client.get(url).json() is None  # no shifts yet

    all_day_shift(bottling)
    body = client.get(url).json()
    today = timezone.now().astimezone(UTC).date()
    assert body["name"] == "All day"
    assert body["start"] == datetime.combine(today, time(0), tzinfo=UTC).isoformat().replace(
        "+00:00", "Z"
    )
    assert body["factory_timezone"] == "UTC"


def test_current_shift_is_tenant_scoped(bottling: Bottling, world: World, api: ApiFactory) -> None:
    url = f"/api/v1/factories/{bottling.line.factory.id}/current-shift/"

    assert api(world.users["other_manager"]).get(url).status_code == 404
    assert api(world.users["limited_operator"]).get(url).status_code == 404


def test_shift_occurrences_endpoint(bottling: Bottling, world: World, api: ApiFactory) -> None:
    factory = bottling.line.factory  # UTC
    Shift.objects.create(factory=factory, name="Night", start_time=time(22), end_time=time(6))
    url = f"/api/v1/factories/{factory.id}/shift-occurrences/"
    params = {"start": "2026-10-12T00:00:00Z", "end": "2026-10-13T12:00:00Z"}

    body = api(world.users["analyst"]).get(url, params).json()

    assert [(o["label"], o["start"], o["end"]) for o in body] == [
        ("Night 2026-10-11", "2026-10-11T22:00:00Z", "2026-10-12T06:00:00Z"),
        ("Night 2026-10-12", "2026-10-12T22:00:00Z", "2026-10-13T06:00:00Z"),
    ]
    assert api(world.users["other_manager"]).get(url, params).status_code == 404
    assert api(world.users["analyst"]).get(url, {"start": params["start"]}).status_code == 400
