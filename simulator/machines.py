"""Machines and buffers: the physical pieces of the virtual line (no events, no time)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from scenarios import BufferConfig, MachineConfig


class MachineState(StrEnum):
    """The exact state values used by LineMind (CLAUDE.md, PRODUCT.md §4)."""

    RUNNING = "running"
    STOPPED = "stopped"
    BLOCKED = "blocked"
    STARVED = "starved"
    PLANNED_STOP = "planned_stop"
    UNKNOWN = "unknown"


@dataclass
class Buffer:
    """A conveyor between two machines, holding whole units."""

    name: str
    capacity: int
    level: int

    @classmethod
    def from_config(cls, config: BufferConfig) -> Buffer:
        return cls(config.name, config.capacity, config.initial_level)

    @property
    def free_space(self) -> int:
        return self.capacity - self.level

    @property
    def is_full(self) -> bool:
        return self.level >= self.capacity

    @property
    def is_empty(self) -> bool:
        return self.level <= 0


@dataclass
class Machine:
    """One machine with a cumulative counter.

    `credit` is how many units the machine is allowed to process so far but
    hasn't yet. Each tick adds speed x tick time (as an exact fraction), so
    6,000 units/hour over 3,600 one-second ticks gives exactly 6,000 units.
    """

    config: MachineConfig
    credit: Fraction = Fraction(0)
    count: int = 0  # units processed (good + rejected), cumulative
    rejected: int = 0
    rejected_by_code: Counter[str] = field(default_factory=Counter)
    state: MachineState = MachineState.RUNNING
    alarm_code: str | None = None

    @property
    def external_id(self) -> str:
        return self.config.external_id

    @property
    def good(self) -> int:
        return self.count - self.rejected

    def units_per_tick(self, tick_seconds: int) -> Fraction:
        return Fraction(self.config.speed_per_hour, 3600) * tick_seconds
