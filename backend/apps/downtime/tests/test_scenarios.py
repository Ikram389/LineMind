"""Simulator fixtures loaded through the real ingestion service."""

from collections.abc import Callable

import pytest

from apps.downtime.models import DowntimeCategory, DowntimeEvent, LineStopIncident
from apps.downtime.services.durations import duration_seconds
from apps.downtime.services.losses import incident_loss
from tests.lines import Bottling


def seconds(event: DowntimeEvent) -> float:
    return duration_seconds(event.started_at, event.ended_at)


def test_labeler_jam_is_one_incident_with_labeler_first(
    bottling: Bottling, load: Callable[..., None]
) -> None:
    load("labeler_jam")

    incident = LineStopIncident.objects.get(line=bottling.line)
    members = list(incident.events.order_by("started_at", "machine__position"))

    assert incident.origin == "machine_stop"
    assert incident.first_machine.external_id == "M05"
    assert not incident.has_simultaneous_first_stops
    assert [(m.machine.external_id, m.category) for m in members] == [
        ("M05", "breakdown"),
        ("M04", "blocked"),
        ("M06", "starved"),
        ("M03", "blocked"),
        ("M02", "blocked"),
        ("M01", "blocked"),
    ]
    labeler, capper, packer = members[0], members[1], members[2]
    assert labeler.is_first_stop and labeler.alarm_code == "E-204"
    assert not capper.is_first_stop and not packer.is_first_stop
    assert seconds(labeler) == pytest.approx(90, abs=0.01)
    assert seconds(capper) == pytest.approx(87, abs=0.01)
    assert seconds(packer) == pytest.approx(83, abs=0.01)
    assert incident.ended_at == packer.ended_at  # last machine back to running
    assert DowntimeEvent.objects.filter(line=bottling.line).count() == 6


def test_reference_1h_packer_stops_5_minutes_and_loses_500_units(
    bottling: Bottling, load: Callable[..., None]
) -> None:
    load("reference_1h")

    packer = DowntimeEvent.objects.filter(
        machine=bottling.machines["M06"], category=DowntimeCategory.BREAKDOWN
    )
    assert sum(seconds(e) for e in packer) == pytest.approx(300, abs=0.01)

    incident = LineStopIncident.objects.get(line=bottling.line)
    assert incident.first_machine.external_id == "M06"
    loss = incident_loss(incident.started_at, incident.ended_at, 6000, incident.ended_at)
    assert loss == {
        "units": 500,
        "is_estimate": True,
        "basis": "duration x line nominal speed, slowest machine (6000/h)",
    }


def test_sensor_dropout_is_no_data_not_breakdown(
    bottling: Bottling, load: Callable[..., None]
) -> None:
    load("sensor_dropout")

    events = list(DowntimeEvent.objects.filter(line=bottling.line))
    assert [(e.machine.external_id, e.category, e.start_kind) for e in events] == [
        ("M03", "no_data", "gap")
    ]
    assert 120 <= seconds(events[0]) <= 140
    assert not DowntimeEvent.objects.filter(category=DowntimeCategory.BREAKDOWN).exists()
    assert not LineStopIncident.objects.exists()
