"""Scenario files: bundled ones load; invalid ones fail with clear messages."""

from __future__ import annotations

from datetime import UTC, datetime
from fractions import Fraction

import pytest

from scenarios import ScenarioError, load_scenario, parse_duration, parse_scenario
from tests.helpers import CONFIG_DIR, SCENARIOS_DIR, make_scenario

BUNDLED = [
    "normal_shift",
    "labeler_jam",
    "labeler_recurring_jams",
    "labeler_after_fix",
    "reference_1h",
    "reference_quality_1h",
    "secondary_breakdown",
    "sensor_dropout",
]


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_scenarios_load(name: str) -> None:
    scenario = load_scenario(SCENARIOS_DIR / f"{name}.yaml")

    assert scenario.name == name
    assert scenario.line.machine_ids == ("M01", "M02", "M03", "M04", "M05", "M06")
    assert scenario.start.tzinfo is not None


def test_reference_scenario_values() -> None:
    scenario = load_scenario(SCENARIOS_DIR / "reference_1h.yaml")

    assert scenario.duration == 3600
    assert scenario.defect_mode == "exact"
    assert {m.speed_per_hour for m in scenario.line.machines} == {6000}
    assert [(f.machine, f.duration) for f in scenario.faults] == [("M06", 300)]
    assert sum(scenario.defect_rates["M06"].values()) == Fraction(3, 100)


def test_reference_quality_scenario_values() -> None:
    scenario = load_scenario(SCENARIOS_DIR / "reference_quality_1h.yaml")

    assert scenario.duration == 3600
    assert scenario.faults == ()
    assert scenario.defect_rates == {"M05": {"Q02": Fraction(2, 100)}}
    speeds = {m.external_id: m.speed_per_hour for m in scenario.line.machines}
    assert speeds == {"M01": 6000, "M02": 6000, "M03": 6000, "M04": 6000, "M05": 6000, "M06": 5880}


def test_machine_speed_override_changes_only_that_machine() -> None:
    scenario = make_scenario(machines={"M03": {"speed_per_hour": 4000}})

    assert [m.speed_per_hour for m in scenario.line.machines] == [
        6000,
        6000,
        4000,
        6000,
        6000,
        6000,
    ]
    assert [m.name for m in scenario.line.machines][2] == "Filler"


def test_normal_shift_is_eight_hours_with_about_one_percent_defects() -> None:
    scenario = load_scenario(SCENARIOS_DIR / "normal_shift.yaml")

    assert scenario.duration == 8 * 3600
    total_rate = sum(sum(r.values()) for r in scenario.defect_rates.values())
    assert total_rate == Fraction(1, 100)
    assert {c for r in scenario.defect_rates.values() for c in r} == {
        "Q01",
        "Q02",
        "Q03",
        "Q04",
        "Q05",
        "Q06",
    }


@pytest.mark.parametrize(
    ("value", "seconds"), [(90, 90), ("90s", 90), ("15m", 900), ("8h", 28800), ("45", 45)]
)
def test_duration_formats(value: object, seconds: int) -> None:
    assert parse_duration(value, "duration", "test") == seconds


def test_buffer_overrides_apply() -> None:
    scenario = make_scenario(buffers={"M03-M04": {"capacity": 80, "initial_level": 19}})

    buffer = next(b for b in scenario.line.buffers if b.name == "M03-M04")
    assert (buffer.capacity, buffer.initial_level) == (80, 19)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"faults": [{"machine": "M99", "at": 10, "duration": 5}]}, "unknown machine 'M99'"),
        ({"faults": [{"machine": "M01", "at": 10, "duration": 0}]}, "greater than zero"),
        ({"duration": -5}, "duration"),
        ({"duration": "soon"}, "duration"),
        ({"defects": [{"machine": "M06", "rates": {"Q02": 1.5}}]}, "between 0 and 1"),
        ({"defects": [{"machine": "M06", "rates": {"Q09": 0.1}}]}, "unknown defect code"),
        (
            {"defects": [{"machine": "M06", "rates": {"Q01": 0.6, "Q02": 0.6}}]},
            "more than 1",
        ),
        ({"surprise": True}, "unknown key(s): surprise"),
        ({"faults": [{"machine": "M01", "at": 10, "duration": 5, "colour": "red"}]}, "colour"),
        ({"start": "2026-10-12T10:00:00"}, "timezone"),
        ({"defect_mode": "sometimes"}, "defect_mode"),
        ({"buffers": {"M01-M03": {"capacity": 5}}}, "unknown buffer"),
        ({"machines": {"M09": {"speed_per_hour": 100}}}, "unknown key(s): M09"),
        ({"random_faults": [{"machine": "M05", "every": "40m", "duration": [1, 2]}]}, "[min, max]"),
        (
            {"random_faults": [{"machine": "M05", "every": [60, 40], "duration": [1, 2]}]},
            "min <= max",
        ),
        (
            {"random_faults": [{"machine": "M99", "every": [40, 60], "duration": [1, 2]}]},
            "unknown machine",
        ),
        (
            {"random_faults": [{"machine": "M05", "every": [40, 60], "duration": [1, 2], "x": 1}]},
            "unknown key",
        ),
        ({"machines": {"M06": {"name": "x"}}}, "unknown key(s): name"),
        ({"machines": {"M06": {"speed_per_hour": 0}}}, "greater than zero"),
        ({"buffers": {"M01-M02": {"initial_level": 60}}}, "initial_level"),
        (
            {"sensor_dropouts": [{"machine": "M03", "at": 1, "duration": 1, "announce": "yes"}]},
            "announce",
        ),
    ],
)
def test_invalid_scenarios_fail_clearly(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ScenarioError, match=message.replace("(", r"\(").replace(")", r"\)")):
        make_scenario(**overrides)


@pytest.mark.parametrize("key", ["name", "line", "start", "duration", "seed"])
def test_missing_required_key(key: str) -> None:
    data = {
        "name": "x",
        "line": str(CONFIG_DIR / "bottling_line_1.yaml"),
        "start": "2026-10-12T10:00:00Z",
        "duration": 60,
        "seed": 1,
    }
    del data[key]

    with pytest.raises(ScenarioError, match=f"'{key}' is required"):
        parse_scenario(data, base_dir=SCENARIOS_DIR)


def test_planned_stop_all_machines() -> None:
    scenario = make_scenario(planned_stops=[{"machines": "all", "at": 60, "duration": 60}])

    assert all(scenario.planned_stop_for(m, 60) for m in scenario.line.machine_ids)
    assert scenario.planned_stop_for("M01", 120) is None


def test_yaml_datetime_start_is_accepted() -> None:
    scenario = make_scenario(start=datetime(2026, 10, 12, 10, tzinfo=UTC))

    assert scenario.start == datetime(2026, 10, 12, 10, tzinfo=UTC)


def test_random_faults_are_reproducible_and_within_their_ranges() -> None:
    spec = [
        {
            "machine": "M05",
            "alarm_code": "E-204",
            "every": ["40m", "60m"],
            "duration": ["60s", "120s"],
        }
    ]
    first = make_scenario(duration=48 * 3600, random_faults=spec, seed=5)
    again = make_scenario(duration=48 * 3600, random_faults=spec, seed=5)
    other = make_scenario(duration=48 * 3600, random_faults=spec, seed=6)

    assert first.faults == again.faults
    assert first.faults != other.faults
    assert {(f.machine, f.alarm_code) for f in first.faults} == {("M05", "E-204")}
    assert all(60 <= f.duration <= 120 for f in first.faults)
    gaps = [
        b.at - (a.at + a.duration) for a, b in zip(first.faults, first.faults[1:], strict=False)
    ]
    assert all(40 * 60 <= gap <= 60 * 60 for gap in gaps)
    assert 40 <= len(first.faults) <= 72  # 48 h / (40-60 min + 1-2 min)


def test_the_maintenance_scenarios_have_frequent_then_rare_jams() -> None:
    before = load_scenario(SCENARIOS_DIR / "labeler_recurring_jams.yaml")
    after = load_scenario(SCENARIOS_DIR / "labeler_after_fix.yaml")

    assert before.duration == after.duration == 7 * 24 * 3600
    assert 160 <= len(before.faults) <= 250
    assert 12 <= len(after.faults) <= 30
    assert {f.alarm_code for f in before.faults + after.faults} == {"E-204"}
