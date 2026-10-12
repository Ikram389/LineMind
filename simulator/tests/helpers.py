"""Helpers for building scenarios in tests without writing YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from events import Event
from scenarios import Scenario, parse_scenario

SIMULATOR_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = SIMULATOR_DIR / "scenarios"
CONFIG_DIR = SIMULATOR_DIR / "config"


def make_scenario(**overrides: Any) -> Scenario:
    data: dict[str, Any] = {
        "name": "test",
        "line": str(CONFIG_DIR / "bottling_line_1.yaml"),
        "start": "2026-10-12T10:00:00Z",
        "duration": 300,
        "seed": 1,
    }
    data.update(overrides)
    return parse_scenario(data, base_dir=SCENARIOS_DIR, source="test scenario")


def state_events(events: list[Event], machine: str | None = None) -> list[Event]:
    count_types = {"production_count_updated", "quality_defect_detected"}
    return [
        e
        for e in events
        if e.event_type not in count_types and (machine is None or e.machine_external_id == machine)
    ]
