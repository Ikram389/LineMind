"""Loading and validating line configs and scenario files (YAML).

Durations and offsets accept plain seconds (90) or strings: "90s", "15m", "8h".
Paths inside a scenario (`line:`) are relative to the scenario file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

DEFECT_CODES = frozenset({"Q01", "Q02", "Q03", "Q04", "Q05", "Q06"})
DEFECT_MODES = frozenset({"exact", "random"})

SCENARIO_KEYS = frozenset(
    {
        "name",
        "description",
        "line",
        "start",
        "duration",
        "seed",
        "tick_seconds",
        "count_interval_seconds",
        "defect_mode",
        "machines",
        "buffers",
        "faults",
        "planned_stops",
        "sensor_dropouts",
        "defects",
    }
)
LINE_KEYS = frozenset(
    {"name", "default_buffer_capacity", "default_initial_level", "machines", "buffers"}
)

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smh]?)\s*$")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600}


class ScenarioError(ValueError):
    """A scenario or line config file is invalid. The message says what to fix."""


# --- Data classes ----------------------------------------------------------------------


@dataclass(frozen=True)
class MachineConfig:
    external_id: str
    name: str
    machine_type: str
    speed_per_hour: int


@dataclass(frozen=True)
class BufferConfig:
    name: str  # "<upstream>-<downstream>"
    capacity: int
    initial_level: int


@dataclass(frozen=True)
class LineConfig:
    name: str
    machines: tuple[MachineConfig, ...]
    buffers: tuple[BufferConfig, ...]  # buffers[i] sits between machines[i] and machines[i+1]

    @property
    def machine_ids(self) -> tuple[str, ...]:
        return tuple(m.external_id for m in self.machines)


@dataclass(frozen=True)
class Fault:
    machine: str
    at: int
    duration: int
    alarm_code: str | None = None

    def active(self, offset: int) -> bool:
        return self.at <= offset < self.at + self.duration


@dataclass(frozen=True)
class PlannedStop:
    machines: frozenset[str]
    at: int
    duration: int
    reason: str = ""

    def active(self, offset: int) -> bool:
        return self.at <= offset < self.at + self.duration


@dataclass(frozen=True)
class SensorDropout:
    machine: str
    at: int
    duration: int
    announce: bool = False  # also send sensor_disconnected / sensor_reconnected

    def active(self, offset: int) -> bool:
        return self.at <= offset < self.at + self.duration


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    line: LineConfig
    start: datetime
    duration: int
    seed: int
    tick_seconds: int = 1
    count_interval_seconds: int = 10
    defect_mode: str = "exact"
    faults: tuple[Fault, ...] = ()
    planned_stops: tuple[PlannedStop, ...] = ()
    sensor_dropouts: tuple[SensorDropout, ...] = ()
    # machine external_id -> {defect code -> rate}
    defect_rates: dict[str, dict[str, Fraction]] = field(default_factory=dict)

    def fault_for(self, machine: str, offset: int) -> Fault | None:
        return next((f for f in self.faults if f.machine == machine and f.active(offset)), None)

    def planned_stop_for(self, machine: str, offset: int) -> PlannedStop | None:
        return next(
            (p for p in self.planned_stops if machine in p.machines and p.active(offset)), None
        )

    def is_silent(self, machine: str, offset: int) -> bool:
        """True while the machine's sensor is disconnected (its events are not sent)."""
        return any(d.machine == machine and d.active(offset) for d in self.sensor_dropouts)


# --- Loading ---------------------------------------------------------------------------


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    return parse_scenario(_read_yaml(path), base_dir=path.parent, source=str(path))


def load_line_config(path: str | Path) -> LineConfig:
    path = Path(path)
    return parse_line_config(_read_yaml(path), source=str(path))


def parse_scenario(data: dict[str, Any], base_dir: Path, source: str = "scenario") -> Scenario:
    _check_keys(data, SCENARIO_KEYS, source)
    for key in ("name", "line", "start", "duration", "seed"):
        if key not in data:
            raise ScenarioError(f"{source}: '{key}' is required.")

    line_path = Path(data["line"])
    if not line_path.is_absolute():
        line_path = base_dir / line_path
    line = load_line_config(line_path)
    line = _apply_machine_overrides(line, data.get("machines") or {}, source)
    line = _apply_buffer_overrides(line, data.get("buffers") or {}, source)

    tick = _positive_int(data.get("tick_seconds", 1), "tick_seconds", source)
    duration = parse_duration(data["duration"], "duration", source)
    if duration <= 0 or duration % tick:
        raise ScenarioError(f"{source}: 'duration' must be a positive multiple of tick_seconds.")
    count_interval = parse_duration(
        data.get("count_interval_seconds", 10), "count_interval_seconds", source
    )
    if count_interval <= 0 or count_interval % tick:
        raise ScenarioError(
            f"{source}: 'count_interval_seconds' must be a positive multiple of tick_seconds."
        )

    defect_mode = data.get("defect_mode", "exact")
    if defect_mode not in DEFECT_MODES:
        raise ScenarioError(f"{source}: 'defect_mode' must be 'exact' or 'random'.")

    machine_ids = set(line.machine_ids)
    ctx = _Context(source, machine_ids, tick, duration)

    return Scenario(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        line=line,
        start=parse_start(data["start"], source),
        duration=duration,
        seed=_int(data["seed"], "seed", source),
        tick_seconds=tick,
        count_interval_seconds=count_interval,
        defect_mode=defect_mode,
        faults=tuple(_parse_fault(item, ctx) for item in data.get("faults") or []),
        planned_stops=tuple(
            _parse_planned_stop(item, ctx) for item in data.get("planned_stops") or []
        ),
        sensor_dropouts=tuple(
            _parse_dropout(item, ctx) for item in data.get("sensor_dropouts") or []
        ),
        defect_rates=_parse_defects(data.get("defects") or [], ctx),
    )


def parse_line_config(data: dict[str, Any], source: str = "line config") -> LineConfig:
    _check_keys(data, LINE_KEYS, source)
    raw_machines = data.get("machines") or []
    if len(raw_machines) < 2:
        raise ScenarioError(f"{source}: a line needs at least two machines.")

    machines = []
    for item in raw_machines:
        _check_keys(item, frozenset({"external_id", "name", "type", "speed_per_hour"}), source)
        machines.append(
            MachineConfig(
                external_id=str(item["external_id"]),
                name=str(item.get("name", item["external_id"])),
                machine_type=str(item.get("type", "")),
                speed_per_hour=_positive_int(
                    item.get("speed_per_hour", 6000), "speed_per_hour", source
                ),
            )
        )
    ids = [m.external_id for m in machines]
    if len(set(ids)) != len(ids):
        raise ScenarioError(f"{source}: machine external_id values must be unique.")

    capacity = _positive_int(data.get("default_buffer_capacity", 50), "capacity", source)
    level = _int(data.get("default_initial_level", 0), "initial_level", source)
    buffers = tuple(
        BufferConfig(f"{a.external_id}-{b.external_id}", capacity, level)
        for a, b in zip(machines, machines[1:], strict=False)
    )
    line = LineConfig(str(data.get("name", "line")), tuple(machines), buffers)
    return _apply_buffer_overrides(line, data.get("buffers") or {}, source)


def parse_duration(value: Any, name: str, source: str) -> int:
    if isinstance(value, bool):
        raise ScenarioError(f"{source}: '{name}' must be a duration like 90, '90s', '15m' or '8h'.")
    if isinstance(value, int):
        if value < 0:
            raise ScenarioError(f"{source}: '{name}' cannot be negative.")
        return value
    match = _DURATION_RE.match(str(value))
    if not match:
        raise ScenarioError(f"{source}: '{name}' must be a duration like 90, '90s', '15m' or '8h'.")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def parse_start(value: Any, source: str) -> datetime:
    if isinstance(value, datetime):
        start = value
    else:
        try:
            start = datetime.fromisoformat(str(value))
        except ValueError:
            raise ScenarioError(
                f"{source}: 'start' must be an ISO date-time, e.g. 2026-10-12T10:00:00Z."
            ) from None
    if start.tzinfo is None:
        raise ScenarioError(f"{source}: 'start' must include a timezone (e.g. 'Z').")
    return start


# --- Helpers ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Context:
    source: str
    machine_ids: set[str]
    tick: int
    duration: int

    def machine(self, value: Any) -> str:
        machine = str(value)
        if machine not in self.machine_ids:
            known = ", ".join(sorted(self.machine_ids))
            raise ScenarioError(f"{self.source}: unknown machine '{machine}' (known: {known}).")
        return machine

    def window(self, item: dict[str, Any], kind: str) -> tuple[int, int]:
        at = parse_duration(item.get("at"), f"{kind}.at", self.source)
        duration = parse_duration(item.get("duration"), f"{kind}.duration", self.source)
        if duration <= 0:
            raise ScenarioError(f"{self.source}: {kind}.duration must be greater than zero.")
        if at % self.tick or duration % self.tick:
            raise ScenarioError(f"{self.source}: {kind} times must be multiples of tick_seconds.")
        return at, duration


def _parse_fault(item: dict[str, Any], ctx: _Context) -> Fault:
    _check_keys(item, frozenset({"machine", "at", "duration", "alarm_code"}), ctx.source)
    at, duration = ctx.window(item, "fault")
    alarm = item.get("alarm_code")
    return Fault(ctx.machine(item.get("machine")), at, duration, str(alarm) if alarm else None)


def _parse_planned_stop(item: dict[str, Any], ctx: _Context) -> PlannedStop:
    _check_keys(item, frozenset({"machines", "at", "duration", "reason"}), ctx.source)
    at, duration = ctx.window(item, "planned_stop")
    raw = item.get("machines", "all")
    if raw == "all":
        machines = frozenset(ctx.machine_ids)
    else:
        raw_list = raw if isinstance(raw, list) else [raw]
        machines = frozenset(ctx.machine(m) for m in raw_list)
    return PlannedStop(machines, at, duration, str(item.get("reason", "")))


def _parse_dropout(item: dict[str, Any], ctx: _Context) -> SensorDropout:
    _check_keys(item, frozenset({"machine", "at", "duration", "announce"}), ctx.source)
    at, duration = ctx.window(item, "sensor_dropout")
    announce = item.get("announce", False)
    if not isinstance(announce, bool):
        raise ScenarioError(f"{ctx.source}: sensor_dropout.announce must be true or false.")
    return SensorDropout(ctx.machine(item.get("machine")), at, duration, announce)


def _parse_defects(items: list[dict[str, Any]], ctx: _Context) -> dict[str, dict[str, Fraction]]:
    result: dict[str, dict[str, Fraction]] = {}
    for item in items:
        _check_keys(item, frozenset({"machine", "rates"}), ctx.source)
        machine = ctx.machine(item.get("machine"))
        rates: dict[str, Fraction] = {}
        for code, rate in (item.get("rates") or {}).items():
            if code not in DEFECT_CODES:
                raise ScenarioError(f"{ctx.source}: unknown defect code '{code}' (use Q01-Q06).")
            if isinstance(rate, bool) or not isinstance(rate, int | float):
                raise ScenarioError(f"{ctx.source}: defect rate for {code} must be a number.")
            # Fraction(str(...)) keeps 0.03 exactly 3/100 instead of a binary float.
            exact = Fraction(str(rate))
            if not 0 <= exact <= 1:
                raise ScenarioError(
                    f"{ctx.source}: defect rate for {code} must be between 0 and 1."
                )
            rates[code] = exact
        if sum(rates.values()) > 1:
            raise ScenarioError(f"{ctx.source}: defect rates for {machine} add up to more than 1.")
        result.setdefault(machine, {}).update(rates)
    return result


def _apply_machine_overrides(
    line: LineConfig, overrides: dict[str, Any], source: str
) -> LineConfig:
    """Per-scenario machine changes; only the speed can be overridden."""
    _check_keys(overrides, frozenset(line.machine_ids), source)
    machines = []
    for machine in line.machines:
        values = overrides.get(machine.external_id)
        if values is not None:
            _check_keys(values, frozenset({"speed_per_hour"}), source)
            speed = _positive_int(values.get("speed_per_hour"), "speed_per_hour", source)
            machine = MachineConfig(machine.external_id, machine.name, machine.machine_type, speed)
        machines.append(machine)
    return LineConfig(line.name, tuple(machines), line.buffers)


def _apply_buffer_overrides(line: LineConfig, overrides: dict[str, Any], source: str) -> LineConfig:
    by_name = {b.name: b for b in line.buffers}
    for name, values in overrides.items():
        if name not in by_name:
            known = ", ".join(by_name)
            raise ScenarioError(f"{source}: unknown buffer '{name}' (known: {known}).")
        _check_keys(values, frozenset({"capacity", "initial_level"}), source)
        current = by_name[name]
        by_name[name] = BufferConfig(
            name,
            _positive_int(values.get("capacity", current.capacity), "capacity", source),
            _int(values.get("initial_level", current.initial_level), "initial_level", source),
        )
    for buffer in by_name.values():
        if not 0 <= buffer.initial_level <= buffer.capacity:
            raise ScenarioError(
                f"{source}: buffer {buffer.name} initial_level must be between 0 and capacity."
            )
    return LineConfig(line.name, line.machines, tuple(by_name[b.name] for b in line.buffers))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ScenarioError(f"File not found: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ScenarioError(f"{path}: expected a YAML mapping at the top level.")
    return data


def _check_keys(data: Any, allowed: frozenset[str], source: str) -> None:
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: expected a mapping, got {type(data).__name__}.")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ScenarioError(f"{source}: unknown key(s): {', '.join(unknown)}.")


def _int(value: Any, name: str, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioError(f"{source}: '{name}' must be a whole number.")
    return value


def _positive_int(value: Any, name: str, source: str) -> int:
    number = _int(value, name, source)
    if number <= 0:
        raise ScenarioError(f"{source}: '{name}' must be greater than zero.")
    return number
