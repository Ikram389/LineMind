"""Recomputing: order independence, stable identity, thresholds, live and edge cases."""

import random
from collections.abc import Callable
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.downtime.services.classification import classify_downtime
from apps.downtime.services.derivation import rebuild_line
from apps.downtime.services.durations import duration_seconds
from apps.downtime.tests.support import Bottling, read_fixture
from apps.organizations.models import ProductionLine
from apps.production.models import IngestedEvent, MachineStateEvent
from apps.production.services.ingestion import ingest_event
from tests.helpers import ApiFactory, World

Snapshot = tuple[list[tuple[object, ...]], list[tuple[object, ...]]]


def snapshot(line: ProductionLine) -> Snapshot:
    events = sorted(
        (
            e.machine.external_id,
            e.start_kind,
            str(e.start_event_id),
            e.category,
            e.started_at,
            e.ended_at,
            e.alarm_code,
            e.is_first_stop,
            e.incident.key if e.incident else None,
            e.is_obsolete,
        )
        for e in DowntimeEvent.objects.filter(line=line).select_related("machine", "incident")
    )
    incidents = sorted(
        (
            i.key,
            i.started_at,
            i.ended_at,
            i.origin,
            i.first_machine.external_id if i.first_machine else None,
            i.has_simultaneous_first_stops,
        )
        for i in LineStopIncident.objects.filter(line=line).select_related("first_machine")
    )
    return events, incidents


def rebuild_from_scratch(line: ProductionLine) -> Snapshot:
    DowntimeEvent.objects.filter(line=line).delete()
    LineStopIncident.objects.filter(line=line).delete()
    rebuild_line(line)
    return snapshot(line)


# --- Order independence ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["labeler_jam", "reference_1h", "sensor_dropout"])
@pytest.mark.parametrize(("shuffle_seed", "batch_size"), [(None, 500), (7, 37), (2026, 500)])
def test_any_arrival_order_gives_the_same_result(
    bottling: Bottling,
    load: Callable[..., None],
    name: str,
    shuffle_seed: int | None,
    batch_size: int,
) -> None:
    load(name, shuffle_seed=shuffle_seed, batch_size=batch_size)
    incremental = snapshot(bottling.line)

    # A full rebuild only depends on the stored data, never on arrival order.
    assert incremental == rebuild_from_scratch(bottling.line)
    assert incremental[0], "the fixture should produce downtime events"


@pytest.mark.parametrize("shuffle_seed", [1, 2, 3])
def test_single_events_in_random_order_give_the_same_result(
    bottling: Bottling, shuffle_seed: int
) -> None:
    """One request per event: every transition lands exactly on its own window start."""
    # Without the count updates, a 90 s stop would be silent for longer than the
    # default stale threshold and become "no_data"; allow long silences here.
    factory = bottling.line.factory
    factory.stale_after_seconds = 3600
    factory.save()
    events = [
        e for e in read_fixture("labeler_jam") if e["event_type"] != "production_count_updated"
    ]
    random.Random(shuffle_seed).shuffle(events)
    for event in events:
        assert ingest_event(bottling.api_key, event).status == "created"

    incremental = snapshot(bottling.line)
    assert incremental == rebuild_from_scratch(bottling.line)
    assert LineStopIncident.objects.filter(first_machine__external_id="M05").exists()


def test_stop_is_closed_by_a_later_transition_after_count_updates(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    """The state in force before the window must be found even when other events
    (count updates) lie between it and the transition that ends it."""
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base, alarm_code="E-204")
    send("M05", "production_count_updated", base + timedelta(seconds=10), count=100)
    send("M05", "production_count_updated", base + timedelta(seconds=20), count=100)
    send("M05", "machine_started", base + timedelta(seconds=30))

    stop = DowntimeEvent.objects.get(machine=bottling.machines["M05"])
    assert (stop.category, stop.alarm_code) == ("breakdown", "E-204")
    assert (stop.started_at, stop.ended_at) == (base, base + timedelta(seconds=30))


# --- Stable identity -------------------------------------------------------------------


def test_rebuilding_twice_keeps_ids_and_classifications(
    bottling: Bottling, load: Callable[..., None], world: World
) -> None:
    load("labeler_jam")
    labeler = DowntimeEvent.objects.get(machine=bottling.machines["M05"])
    reason = bottling.line.factory.downtime_reasons.get(code="MECH-JAM")
    classification = classify_downtime(
        labeler, reason, "Label web snapped", world.users["machine_operator"]
    )
    before_ids = sorted(DowntimeEvent.objects.values_list("id", flat=True))
    incident_id = LineStopIncident.objects.get().id

    for _ in range(2):
        call_command("rebuild_downtime", "--line", str(bottling.line.id), stdout=StringIO())

    assert sorted(DowntimeEvent.objects.values_list("id", flat=True)) == before_ids
    assert LineStopIncident.objects.get().id == incident_id
    labeler.refresh_from_db()
    assert labeler.current_classification == classification
    assert labeler.classifications.count() == 1


def test_classified_stop_keeps_id_and_classification_when_its_end_changes(
    bottling: Bottling, send: Callable[..., str], world: World
) -> None:
    """A late event inside a classified stop shortens it: the row is updated, not replaced."""
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base, alarm_code="E-204")
    send("M05", "machine_started", base + timedelta(seconds=60))
    stop = DowntimeEvent.objects.get(machine=bottling.machines["M05"])
    reason = bottling.line.factory.downtime_reasons.get(code="MECH-JAM")
    classification = classify_downtime(stop, reason, "", world.users["machine_operator"])

    send("M05", "machine_blocked", base + timedelta(seconds=30))  # arrives late

    stop.refresh_from_db()
    assert (stop.started_at, stop.ended_at) == (base, base + timedelta(seconds=30))
    assert stop.current_classification == classification
    assert not stop.is_obsolete
    assert DowntimeEvent.objects.filter(machine=bottling.machines["M05"]).count() == 2  # + blocked


def test_rebuild_with_window(bottling: Bottling, load: Callable[..., None]) -> None:
    load("labeler_jam")
    expected = snapshot(bottling.line)

    call_command(
        "rebuild_downtime",
        "--line",
        str(bottling.line.id),
        "--start",
        "2026-10-12T10:05:30Z",
        "--end",
        "2026-10-12T10:06:00Z",
        stdout=StringIO(),
    )

    assert snapshot(bottling.line) == expected


def test_late_event_shrinking_a_classified_stop_keeps_it_as_obsolete(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base)
    send("M05", "machine_started", base + timedelta(seconds=60))
    stop = DowntimeEvent.objects.get(machine=bottling.machines["M05"])
    reason = bottling.line.factory.downtime_reasons.get(code="MECH-JAM")
    classify_downtime(stop, reason, "", world.users["machine_operator"])

    # A late "running" 2 s after the stop: the stop is now shorter than 5 s.
    send("M05", "machine_started", base + timedelta(seconds=2))

    stop.refresh_from_db()
    assert stop.is_obsolete
    assert stop.classifications.count() == 1
    listed = api(world.users["analyst"]).get("/api/v1/downtime-events/").json()["results"]
    assert stop.id not in {e["id"] for e in listed}


# --- Threshold -------------------------------------------------------------------------


def test_short_stops_are_ignored_and_threshold_change_needs_rebuild(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base)
    send("M05", "machine_started", base + timedelta(seconds=3))  # 3 s: below 5 s
    send("M04", "machine_stopped", base + timedelta(seconds=100))
    send("M04", "machine_started", base + timedelta(seconds=110))  # 10 s

    def machines_with_downtime() -> list[str]:
        return sorted(
            DowntimeEvent.objects.filter(line=bottling.line).values_list(
                "machine__external_id", flat=True
            )
        )

    assert machines_with_downtime() == ["M04"]

    factory = bottling.line.factory
    factory.oee_settings = {**factory.oee_settings, "minimum_stop_seconds": 2}
    factory.save()
    assert machines_with_downtime() == ["M04"]  # nothing changes until a rebuild
    call_command("rebuild_downtime", "--line", str(bottling.line.id), stdout=StringIO())
    assert machines_with_downtime() == ["M04", "M05"]

    factory.oee_settings = {**factory.oee_settings, "minimum_stop_seconds": 15}
    factory.save()
    call_command("rebuild_downtime", "--line", str(bottling.line.id), stdout=StringIO())
    assert machines_with_downtime() == []


# --- Live and edge cases ---------------------------------------------------------------


def test_ongoing_stop_is_open_and_its_duration_grows(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    started = timezone.now() - timedelta(seconds=30)
    send("M05", "machine_stopped", started)

    stop = DowntimeEvent.objects.get(machine=bottling.machines["M05"])
    assert stop.ended_at is None
    assert duration_seconds(stop.started_at, stop.ended_at, started + timedelta(seconds=40)) == 40
    assert duration_seconds(stop.started_at, stop.ended_at, started + timedelta(seconds=90)) == 90

    body = api(world.users["analyst"]).get(f"/api/v1/downtime-events/{stop.id}/").json()
    assert body["is_ongoing"] is True
    assert body["ended_at"] is None
    assert body["duration_seconds"] >= 30
    incident = LineStopIncident.objects.get()
    assert incident.ended_at is None


def test_simultaneous_first_stops_are_all_recorded(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base)
    send("M03", "machine_stopped", base)
    send("M04", "machine_blocked", base + timedelta(seconds=3))
    for machine in ("M03", "M04", "M05"):
        send(machine, "machine_started", base + timedelta(seconds=60))

    incident = LineStopIncident.objects.get()
    firsts = DowntimeEvent.objects.filter(is_first_stop=True).values_list(
        "machine__external_id", flat=True
    )
    assert sorted(firsts) == ["M03", "M05"]
    assert incident.has_simultaneous_first_stops
    assert incident.first_machine.external_id == "M03"  # earliest in line order


def test_cascade_without_breakdown_has_unknown_origin(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M04", "machine_blocked", base)
    send("M06", "machine_starved", base + timedelta(seconds=5))
    send("M04", "machine_started", base + timedelta(seconds=60))
    send("M06", "machine_started", base + timedelta(seconds=60))

    incident = LineStopIncident.objects.get()
    assert incident.origin == "unknown"
    assert incident.first_machine is None
    assert not DowntimeEvent.objects.filter(is_first_stop=True).exists()


def test_incident_ends_when_last_member_runs_again(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M05", "machine_stopped", base)
    send("M04", "machine_blocked", base + timedelta(seconds=3))
    send("M05", "machine_started", base + timedelta(seconds=30))
    send("M04", "machine_started", base + timedelta(seconds=31))
    send("M02", "machine_stopped", base + timedelta(seconds=40))  # after: a new incident
    send("M02", "machine_started", base + timedelta(seconds=50))

    incidents = list(LineStopIncident.objects.order_by("started_at"))
    assert len(incidents) == 2
    assert incidents[0].ended_at == base + timedelta(seconds=31)
    assert incidents[0].events.count() == 2
    assert incidents[1].first_machine.external_id == "M02"


def test_planned_stops_and_no_data_are_not_incident_members(
    bottling: Bottling, send: Callable[..., str]
) -> None:
    base = timezone.now() - timedelta(hours=1)
    send("M05", "planned_stop_started", base)
    send("M05", "planned_stop_ended", base + timedelta(seconds=60))

    event = DowntimeEvent.objects.get()
    assert event.category == "planned"
    assert event.incident is None
    assert not LineStopIncident.objects.exists()


def test_escalation_flag_uses_factory_setting(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    base = timezone.now() - timedelta(hours=2)
    send("M05", "machine_stopped", base)
    send("M05", "machine_started", base + timedelta(minutes=11))
    send("M04", "machine_stopped", timezone.now() - timedelta(minutes=11))  # still ongoing
    client = api(world.users["analyst"])

    def flags() -> dict[str, bool]:
        events = client.get("/api/v1/downtime-events/").json()["results"]
        return {e["machine"]["external_id"]: e["exceeds_escalation_threshold"] for e in events}

    assert flags() == {"M05": True, "M04": True}

    factory = bottling.line.factory
    factory.escalation_after_seconds = 900
    factory.save()
    assert flags() == {"M05": False, "M04": False}


def test_raw_observations_are_untouched_by_derivation(
    bottling: Bottling, load: Callable[..., None]
) -> None:
    load("labeler_jam")
    before = (
        list(MachineStateEvent.objects.order_by("id").values()),
        IngestedEvent.objects.count(),
    )
    rebuild_line(bottling.line)

    assert (
        list(MachineStateEvent.objects.order_by("id").values()),
        IngestedEvent.objects.count(),
    ) == before
