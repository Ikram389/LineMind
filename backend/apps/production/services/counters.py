"""The one rule for turning cumulative counter readings into produced units.

Counters are cumulative. Production is the difference between two consecutive
readings, credited to the later one. A machine's first reading is only a
starting point. A counter that goes down was reset: the new value counts from
zero. Used by the OEE calculation and the live line status.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.organizations.models import Machine
from apps.production.models import ProductionEvent


class CounterReading(Protocol):
    @property
    def timestamp(self) -> datetime: ...
    @property
    def count(self) -> int: ...
    @property
    def rejected(self) -> int | None: ...


@dataclass(frozen=True)
class Reading:
    timestamp: datetime
    count: int
    rejected: int | None


@dataclass(frozen=True)
class CounterDelta:
    reading: CounterReading
    produced: int
    rejected: int
    was_reset: bool
    rejects_missing: bool


def counter_deltas(readings: Sequence[CounterReading]) -> Iterator[CounterDelta]:
    """One delta per reading after the first, in the given (time) order."""
    previous: CounterReading | None = None
    for reading in readings:
        if previous is not None:
            produced = reading.count - previous.count
            was_reset = produced < 0
            if was_reset:
                produced = reading.count
            if reading.rejected is None or previous.rejected is None:
                rejected, missing = 0, True
            else:
                rejected = reading.rejected - previous.rejected
                if rejected < 0:
                    rejected = reading.rejected
                missing = False
            yield CounterDelta(reading, produced, rejected, was_reset, missing)
        previous = reading


def load_readings(machine: Machine, start: datetime, end: datetime) -> list[Reading]:
    """The last reading at or before `start` (the baseline) plus every reading in (start, end]."""
    readings = ProductionEvent.objects.filter(machine=machine)
    baseline = (
        readings.filter(timestamp__lte=start)
        .order_by("-timestamp", "-event_id")
        .values_list("timestamp", "count", "rejected")
        .first()
    )
    rows = list(
        readings.filter(timestamp__gt=start, timestamp__lte=end)
        .order_by("timestamp", "event_id")
        .values_list("timestamp", "count", "rejected")
    )
    return [Reading(*row) for row in ([baseline] if baseline else []) + rows]


def produced_between(machine: Machine, start: datetime, end: datetime) -> tuple[int, int]:
    """(produced, rejected) by the machine in (start, end]."""
    produced = rejected = 0
    for delta in counter_deltas(load_readings(machine, start, end)):
        if start < delta.reading.timestamp <= end:
            produced += delta.produced
            rejected += delta.rejected
    return produced, rejected
