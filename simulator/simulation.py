"""Runs a scenario on the line tick by tick and turns what happens into events.

This module knows nothing about HTTP, files or wall-clock time: `step()` simply
returns the events of the next tick. runner.py decides when to call it and
where the events go.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from events import PLANNED_STOP_ENDED, STATE_EVENT_TYPES, Event, EventFactory
from factory import Condition, DefectModel, ExactDefects, Line, MachineTick, RandomDefects
from machines import MachineState
from scenarios import Scenario


@dataclass
class MachineStats:
    produced: int = 0
    rejected: int = 0
    rejected_by_code: Counter[str] = field(default_factory=Counter)
    state_changes: int = 0
    seconds_in_state: Counter[str] = field(default_factory=Counter)

    @property
    def good(self) -> int:
        return self.produced - self.rejected


def build_defect_model(scenario: Scenario) -> DefectModel:
    if scenario.defect_mode == "random":
        return RandomDefects(scenario.defect_rates, scenario.seed)
    return ExactDefects(scenario.defect_rates)


class Simulation:
    def __init__(self, scenario: Scenario, start: datetime | None = None) -> None:
        self.scenario = scenario
        self.start = (start or scenario.start).astimezone(UTC)
        self.line = Line(scenario.line, build_defect_model(scenario))
        self.events = EventFactory(f"{scenario.name}|{scenario.seed}|{self.start.isoformat()}")
        self.tick = 0
        self.total_ticks = scenario.duration // scenario.tick_seconds
        ids = scenario.line.machine_ids
        self._last_sent_state: dict[str, MachineState | None] = dict.fromkeys(ids)
        self._previous_state: dict[str, MachineState | None] = dict.fromkeys(ids)
        self.stats: dict[str, MachineStats] = {m: MachineStats() for m in ids}

    @property
    def finished(self) -> bool:
        return self.tick >= self.total_ticks

    def time_at(self, offset_seconds: int) -> datetime:
        return self.start + timedelta(seconds=offset_seconds)

    def run_all(self) -> list[Event]:
        """Run to the end and return every event (used by tests and file output)."""
        events: list[Event] = []
        while not self.finished:
            events.extend(self.step())
        return events

    def step(self) -> list[Event]:
        if self.finished:
            raise RuntimeError("The simulation has already finished.")
        dt = self.scenario.tick_seconds
        offset = self.tick * dt
        at = self.time_at(offset)

        results = self.line.tick(self._conditions(offset), dt)

        events: list[Event] = []
        for machine_id in self.scenario.line.machine_ids:  # emit in line order
            result = results[machine_id]
            self._record_stats(result, dt)
            events.extend(self._dropout_events(machine_id, offset, at))
            if self.scenario.is_silent(machine_id, offset):
                continue
            events.extend(self._state_events(result, at))
            events.extend(
                self.events.create(
                    machine_id, "quality_defect_detected", at, payload={"defect_code": code}
                )
                for code in result.defects
            )

        self.tick += 1
        end_offset = self.tick * dt
        if end_offset % self.scenario.count_interval_seconds == 0 or self.finished:
            events.extend(self._count_events(end_offset))
        return events

    # --- helpers -----------------------------------------------------------------------

    def _conditions(self, offset: int) -> dict[str, Condition]:
        conditions: dict[str, Condition] = {}
        for machine_id in self.scenario.line.machine_ids:
            fault = self.scenario.fault_for(machine_id, offset)
            if fault is not None:
                conditions[machine_id] = Condition("fault", fault.alarm_code)
            elif self.scenario.planned_stop_for(machine_id, offset) is not None:
                conditions[machine_id] = Condition("planned_stop")
        return conditions

    def _state_events(self, result: MachineTick, at: datetime) -> list[Event]:
        previous = self._last_sent_state[result.external_id]
        if result.state == previous:
            return []
        self._last_sent_state[result.external_id] = result.state
        if result.state == MachineState.RUNNING and previous == MachineState.PLANNED_STOP:
            event_type = PLANNED_STOP_ENDED
        else:
            event_type = STATE_EVENT_TYPES[result.state]
        return [
            self.events.create(result.external_id, event_type, at, alarm_code=result.alarm_code)
        ]

    def _dropout_events(self, machine_id: str, offset: int, at: datetime) -> list[Event]:
        events: list[Event] = []
        for dropout in self.scenario.sensor_dropouts:
            if dropout.machine != machine_id or not dropout.announce:
                continue
            if offset == dropout.at:
                events.append(self.events.create(machine_id, "sensor_disconnected", at))
                # The backend now shows "unknown", so the real state must be sent again later.
                self._last_sent_state[machine_id] = MachineState.UNKNOWN
            elif offset == dropout.at + dropout.duration:
                events.append(self.events.create(machine_id, "sensor_reconnected", at))
        return events

    def _count_events(self, end_offset: int) -> list[Event]:
        at = self.time_at(end_offset)
        return [
            self.events.create(
                machine.external_id,
                "production_count_updated",
                at,
                count=machine.count,
                rejected=machine.rejected,
            )
            for machine in self.line.machines
            if not self.scenario.is_silent(machine.external_id, end_offset)
        ]

    def _record_stats(self, result: MachineTick, dt: int) -> None:
        stats = self.stats[result.external_id]
        machine = self.line.machine(result.external_id)
        stats.produced = machine.count
        stats.rejected = machine.rejected
        stats.rejected_by_code = Counter(machine.rejected_by_code)
        stats.seconds_in_state[result.state.value] += dt
        if result.state != self._previous_state[result.external_id]:
            stats.state_changes += 1
            self._previous_state[result.external_id] = result.state
