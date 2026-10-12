"""What gets emitted: the reference case, determinism, transitions, counts, timestamps."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from events import Event
from scenarios import load_scenario
from simulation import Simulation
from tests.helpers import SCENARIOS_DIR, make_scenario, state_events

VALID_STATE_EVENTS = {
    "machine_started",
    "machine_stopped",
    "machine_blocked",
    "machine_starved",
    "planned_stop_started",
    "planned_stop_ended",
    "sensor_disconnected",
    "sensor_reconnected",
}


def run(name: str, start: datetime | None = None) -> tuple[Simulation, list[Event]]:
    sim = Simulation(load_scenario(SCENARIOS_DIR / f"{name}.yaml"), start=start)
    return sim, sim.run_all()


def last_count(events: list[Event], machine: str) -> Event:
    return [
        e
        for e in events
        if e.machine_external_id == machine and e.event_type == "production_count_updated"
    ][-1]


# --- Reference case (PRODUCT.md §14) ---------------------------------------------------


def test_reference_1h_exact_gives_known_answer() -> None:
    sim, events = run("reference_1h")

    packer = sim.stats["M06"]
    assert (packer.produced, packer.rejected, packer.good) == (5500, 165, 5335)
    assert dict(packer.rejected_by_code) == {"Q02": 110, "Q04": 55}

    final = last_count(events, "M06")
    assert (final.count, final.rejected) == (5500, 165)
    assert final.timestamp == sim.start + timedelta(hours=1)

    defects = [e for e in events if e.event_type == "quality_defect_detected"]
    assert len(defects) == 165
    assert {e.payload["defect_code"] for e in defects} == {"Q02", "Q04"}


def test_reference_without_fault_would_make_6000() -> None:
    scenario = load_scenario(SCENARIOS_DIR / "reference_1h.yaml")
    sim = Simulation(replace(scenario, faults=()))
    sim.run_all()

    assert sim.stats["M06"].produced == 6000  # planned 6,000; the stop lost 500


# --- Determinism -----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["reference_1h", "labeler_jam", "sensor_dropout"])
def test_same_scenario_seed_and_start_give_identical_events(name: str) -> None:
    _, first = run(name)
    _, second = run(name)

    assert first == second


def test_random_mode_is_reproducible_and_seed_dependent() -> None:
    scenario = make_scenario(
        duration=1800,
        defect_mode="random",
        defects=[{"machine": "M05", "rates": {"Q02": 0.05}}],
    )
    first = Simulation(scenario).run_all()
    second = Simulation(scenario).run_all()
    other_seed = Simulation(replace(scenario, seed=999)).run_all()

    def defects(events: list[Event]) -> list[datetime]:
        return [e.timestamp for e in events if e.event_type == "quality_defect_detected"]

    assert defects(first) == defects(second)
    assert defects(first) != defects(other_seed)


def test_random_defect_rate_is_close_to_configured() -> None:
    sim = Simulation(
        make_scenario(
            duration=3600,
            defect_mode="random",
            defects=[{"machine": "M06", "rates": {"Q01": 0.03}}],
        )
    )
    sim.run_all()

    assert 0.02 < sim.stats["M06"].rejected / sim.stats["M06"].produced < 0.04


def test_different_start_gives_different_event_ids() -> None:
    _, first = run("labeler_jam")
    _, later = run("labeler_jam", start=datetime(2026, 10, 13, 10, tzinfo=UTC))

    assert {e.event_id for e in first}.isdisjoint({e.event_id for e in later})


def test_event_ids_are_unique_uuids() -> None:
    _, events = run("normal_shift")

    ids = [e.event_id for e in events]
    assert len(ids) == len(set(ids))
    assert all(uuid.UUID(i) for i in ids[:100])


# --- Transitions, counts, timestamps ---------------------------------------------------


@pytest.mark.parametrize("name", ["normal_shift", "labeler_jam", "reference_1h"])
def test_state_events_only_on_transitions(name: str) -> None:
    _, events = run(name)

    by_machine: dict[str, list[str]] = defaultdict(list)
    for event in events:
        if event.event_type in VALID_STATE_EVENTS:
            by_machine[event.machine_external_id].append(event.event_type)

    for machine, types in by_machine.items():
        assert all(a != b for a, b in zip(types, types[1:], strict=False)), machine


def test_each_machine_starts_with_a_state_event() -> None:
    _, events = run("labeler_jam")

    for machine in ("M01", "M02", "M03", "M04", "M05", "M06"):
        first = next(e for e in events if e.machine_external_id == machine)
        assert first.event_type == "machine_started"
        assert first.timestamp == datetime(2026, 10, 12, 10, tzinfo=UTC)


def test_counts_every_interval_plus_final_and_never_decreasing() -> None:
    sim, events = run("labeler_jam")  # 15 min, interval 10 s -> 90 updates per machine

    counts = [e for e in events if e.event_type == "production_count_updated"]
    for machine in ("M01", "M06"):
        series = [e for e in counts if e.machine_external_id == machine]
        assert len(series) == 90
        assert [e.count for e in series] == sorted(e.count for e in series)
        assert series[-1].count == sim.stats[machine].produced
        assert all(e.rejected is not None for e in series)


@pytest.mark.parametrize("name", ["normal_shift", "labeler_jam", "reference_1h", "sensor_dropout"])
def test_timestamps_are_utc_and_strictly_increasing_per_machine(name: str) -> None:
    _, events = run(name)

    last: dict[str, datetime] = {}
    for event in events:
        assert event.timestamp.tzinfo is not None
        assert event.timestamp.utcoffset() == timedelta(0)
        previous = last.get(event.machine_external_id)
        assert previous is None or event.timestamp > previous
        last[event.machine_external_id] = event.timestamp


def test_fault_event_carries_alarm_code() -> None:
    _, events = run("labeler_jam")

    stopped = [e for e in events if e.event_type == "machine_stopped"]
    assert [(e.machine_external_id, e.alarm_code) for e in stopped] == [("M05", "E-204")]


def test_planned_stop_events() -> None:
    sim = Simulation(
        make_scenario(duration=300, planned_stops=[{"machines": "all", "at": 60, "duration": 60}])
    )
    events = state_events(sim.run_all(), "M03")

    assert [e.event_type for e in events] == [
        "machine_started",
        "planned_stop_started",
        "planned_stop_ended",
    ]
    # Same second as the stop; a count update stamped at that second may come 1 ms earlier.
    assert events[1].timestamp.replace(microsecond=0) == sim.time_at(60)
    assert events[2].timestamp.replace(microsecond=0) == sim.time_at(120)


def test_planned_stop_ended_followed_by_derived_state() -> None:
    # Only the packer has a planned stop; upstream gets blocked meanwhile.
    sim = Simulation(
        make_scenario(duration=300, planned_stops=[{"machines": ["M06"], "at": 60, "duration": 90}])
    )
    m05 = [e.event_type for e in state_events(sim.run_all(), "M05")]

    assert m05 == ["machine_started", "machine_blocked", "machine_started"]


# --- Sensor dropouts -------------------------------------------------------------------


def test_silent_dropout_sends_nothing_for_that_machine() -> None:
    sim, events = run("sensor_dropout")  # M03 silent from 3m to 5m
    window_start, window_end = sim.time_at(180), sim.time_at(300)

    m03_in_window = [
        e
        for e in events
        if e.machine_external_id == "M03" and window_start <= e.timestamp < window_end
    ]
    m04_in_window = [
        e
        for e in events
        if e.machine_external_id == "M04" and window_start <= e.timestamp < window_end
    ]
    assert m03_in_window == []
    assert len(m04_in_window) == 12  # other machines keep reporting (count every 10 s)

    # The cumulative counter catches up on the first update after the dropout:
    # 300 s at 6,000/h = 500 units, nothing lost while silent.
    after = next(
        e
        for e in events
        if e.machine_external_id == "M03"
        and e.event_type == "production_count_updated"
        and e.timestamp >= window_end
    )
    assert after.timestamp == window_end
    assert after.count == 500


def test_announced_dropout_sends_disconnect_reconnect_and_state() -> None:
    sim = Simulation(
        make_scenario(
            duration=300,
            sensor_dropouts=[{"machine": "M03", "at": 60, "duration": 60, "announce": True}],
        )
    )
    events = state_events(sim.run_all(), "M03")

    assert [e.event_type for e in events] == [
        "machine_started",
        "sensor_disconnected",
        "sensor_reconnected",
        "machine_started",  # state re-sent: the backend was showing "unknown"
    ]
    assert events[1].timestamp.replace(microsecond=0) == sim.time_at(60)


# --- JSON format (step 3 API contract) -------------------------------------------------


def test_event_json_matches_event_api() -> None:
    _, events = run("reference_1h")
    stopped = next(e for e in events if e.event_type == "machine_stopped").to_json()
    count = last_count(events, "M06").to_json()
    defect = next(e for e in events if e.event_type == "quality_defect_detected").to_json()

    assert set(stopped) == {
        "event_id",
        "machine_external_id",
        "event_type",
        "timestamp",
        "alarm_code",
    }
    assert stopped["timestamp"].endswith("Z")
    assert datetime.fromisoformat(stopped["timestamp"]).tzinfo is not None
    assert count["count"] == 5500 and count["rejected"] == 165
    assert defect["payload"]["defect_code"] in {"Q02", "Q04"}
    assert Event.from_json(count) == last_count(events, "M06")
