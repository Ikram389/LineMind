"""The line: machines connected by buffers, advanced one tick at a time.

How one tick works (see also README / CLAUDE.md "Simulator"):
- Machines are processed from the last (packer) to the first (feeder), so each
  machine frees space before the machine upstream tries to fill it.
- A machine with a fault is "stopped"; one in a planned stop is "planned_stop".
  Neither processes anything nor builds up speed credit.
- A healthy machine gets speed credit, then processes
  n = min(units its credit allows, units in its input buffer, free output space).
  The feeder always has input; the packer can always output.
- Each processed unit is inspected; a defective unit is counted as rejected and
  removed from the line, a good one goes into the output buffer.
- Derived state: processed >= 1 -> running; else input empty -> starved;
  else output full -> blocked; else running (nothing due yet on a slow machine).
"""

from __future__ import annotations

import random
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import floor
from typing import Literal, Protocol

from machines import Buffer, Machine, MachineState
from scenarios import LineConfig

UNLIMITED = sys.maxsize


@dataclass(frozen=True)
class Condition:
    """Something that stops a machine during a tick."""

    kind: Literal["fault", "planned_stop"]
    alarm_code: str | None = None


@dataclass(frozen=True)
class MachineTick:
    """What happened to one machine during one tick."""

    external_id: str
    state: MachineState
    processed: int
    defects: tuple[str, ...]
    alarm_code: str | None


# --- Defect models ---------------------------------------------------------------------


class DefectModel(Protocol):
    def inspect(self, machine: Machine, units: int) -> list[str]:
        """Return one defect code per defective unit among the next `units` units."""
        ...


class NoDefects:
    def inspect(self, machine: Machine, units: int) -> list[str]:
        return []


class ExactDefects:
    """Deterministic: after N units, a code has rejected round(N x rate) units in total."""

    def __init__(self, rates: Mapping[str, Mapping[str, Fraction]]) -> None:
        self._rates = rates

    def inspect(self, machine: Machine, units: int) -> list[str]:
        rates = self._rates.get(machine.external_id)
        if not rates or units <= 0:
            return []
        produced_after = machine.count + units
        defects: list[str] = []
        for code, rate in sorted(rates.items()):
            target = floor(produced_after * rate + Fraction(1, 2))  # round half up, exactly
            missing = target - machine.rejected_by_code[code]
            take = min(missing, units - len(defects))
            defects.extend([code] * max(take, 0))
        return defects


class RandomDefects:
    """Each unit is independently defective with the configured probabilities (seeded)."""

    def __init__(self, rates: Mapping[str, Mapping[str, Fraction]], seed: int) -> None:
        self._rates = {
            machine: sorted((code, float(rate)) for code, rate in codes.items())
            for machine, codes in rates.items()
        }
        self._rng = random.Random(seed)

    def inspect(self, machine: Machine, units: int) -> list[str]:
        rates = self._rates.get(machine.external_id)
        if not rates:
            return []
        defects = []
        for _ in range(units):
            roll = self._rng.random()
            cumulative = 0.0
            for code, rate in rates:
                cumulative += rate
                if roll < cumulative:
                    defects.append(code)
                    break
        return defects


# --- Line ------------------------------------------------------------------------------


class Line:
    def __init__(self, config: LineConfig, defect_model: DefectModel | None = None) -> None:
        self.config = config
        self.machines = [Machine(m) for m in config.machines]
        self.buffers = [Buffer.from_config(b) for b in config.buffers]
        self.defect_model = defect_model or NoDefects()

    def machine(self, external_id: str) -> Machine:
        return next(m for m in self.machines if m.external_id == external_id)

    def buffer(self, name: str) -> Buffer:
        return next(b for b in self.buffers if b.name == name)

    def tick(
        self, conditions: Mapping[str, Condition], tick_seconds: int
    ) -> dict[str, MachineTick]:
        results: dict[str, MachineTick] = {}
        last = len(self.machines) - 1
        for index in range(last, -1, -1):  # downstream first
            machine = self.machines[index]
            input_buffer = self.buffers[index - 1] if index > 0 else None
            output_buffer = self.buffers[index] if index < last else None
            results[machine.external_id] = self._tick_machine(
                machine,
                input_buffer,
                output_buffer,
                conditions.get(machine.external_id),
                tick_seconds,
            )
        return results

    def _tick_machine(
        self,
        machine: Machine,
        input_buffer: Buffer | None,
        output_buffer: Buffer | None,
        condition: Condition | None,
        tick_seconds: int,
    ) -> MachineTick:
        if condition is not None:
            machine.state = (
                MachineState.STOPPED if condition.kind == "fault" else MachineState.PLANNED_STOP
            )
            machine.alarm_code = condition.alarm_code
            return MachineTick(machine.external_id, machine.state, 0, (), machine.alarm_code)

        machine.alarm_code = None
        machine.credit += machine.units_per_tick(tick_seconds)
        wanted = floor(machine.credit)
        available = input_buffer.level if input_buffer else UNLIMITED
        space = output_buffer.free_space if output_buffer else UNLIMITED
        processed = min(wanted, available, space)

        defects = self.defect_model.inspect(machine, processed)
        if input_buffer:
            input_buffer.level -= processed
        if output_buffer:
            output_buffer.level += processed - len(defects)
        machine.count += processed
        machine.rejected += len(defects)
        machine.rejected_by_code.update(defects)
        # Credit that could not be used because of a buffer is dropped, so a
        # machine never "catches up" with a burst faster than its speed.
        machine.credit -= wanted

        if processed >= 1:
            machine.state = MachineState.RUNNING
        elif available == 0:
            machine.state = MachineState.STARVED
        elif space == 0:
            machine.state = MachineState.BLOCKED
        else:
            machine.state = MachineState.RUNNING
        return MachineTick(machine.external_id, machine.state, processed, tuple(defects), None)
