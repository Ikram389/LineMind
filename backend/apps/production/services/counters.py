"""The one rule for turning cumulative counter readings into produced units.

Counters are cumulative. Production is the difference between two consecutive
readings, credited to the later one. A machine's first reading is only a
starting point. A counter that goes down was reset: the new value counts from
zero. Used by the OEE calculation and the live line status.

It also holds the one rule for line-wide counts (`LineCounts`, docs/PRODUCT.md §4):
a rejected bottle leaves the line at the machine that rejected it, so

    total count = counting machine output + rejects of the machines upstream of it
    good count  = counting machine output - rejects at the counting machine
"""

from bisect import bisect_left
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.organizations.models import Machine, ProductionLine
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


@dataclass(frozen=True)
class LineCounts:
    output: int = 0  # units counted by the counting machine (good + its own rejects)
    output_rejected: int = 0  # rejected at the counting machine
    upstream_rejected: int = 0  # removed upstream; these never reached the counting machine

    @property
    def total(self) -> int:
        return self.output + self.upstream_rejected

    @property
    def rejected(self) -> int:
        return self.output_rejected + self.upstream_rejected

    @property
    def good(self) -> int:
        return self.output - self.output_rejected


def upstream_machines(line: ProductionLine) -> list[Machine]:
    """Machines before the counting machine on the line (their rejects never reach it)."""
    counting = line.output_machine()
    if counting is None:
        return []
    return list(line.machines.filter(position__lt=counting.position).order_by("position"))


def line_counts_between(line: ProductionLine, start: datetime, end: datetime) -> LineCounts:
    """Line-wide counts in (start, end], with no planned-time filter (the OEE applies its own)."""
    return line_counts_by_bucket(line, [(start, end)])[0]


Keep = Callable[[datetime], bool]


def machine_counts_by_bucket(
    machine: Machine, buckets: Sequence[tuple[datetime, datetime]], keep: Keep | None = None
) -> list[tuple[int, int]]:
    """(produced, rejected) per bucket; a delta belongs to the bucket with start < t <= end.

    Readings are loaded once for the whole span. `keep` can drop deltas by time
    (e.g. only while a given product was running).
    """
    totals = [(0, 0)] * len(buckets)
    if not buckets:
        return totals
    ends = [end for _, end in buckets]
    readings = load_readings(machine, buckets[0][0], buckets[-1][1])
    for delta in counter_deltas(readings):
        moment = delta.reading.timestamp
        index = bisect_left(ends, moment)
        if index == len(buckets) or not buckets[index][0] < moment:
            continue
        if keep is not None and not keep(moment):
            continue
        produced, rejected = totals[index]
        totals[index] = (produced + delta.produced, rejected + delta.rejected)
    return totals


def line_counts_by_bucket(
    line: ProductionLine, buckets: Sequence[tuple[datetime, datetime]], keep: Keep | None = None
) -> list[LineCounts]:
    """LineCounts per (sorted, non-overlapping) bucket."""
    counting = line.output_machine()
    if counting is None:
        return [LineCounts() for _ in buckets]
    output = machine_counts_by_bucket(counting, buckets, keep)
    upstream = [0] * len(buckets)
    for machine in upstream_machines(line):
        for index, (_, rejected) in enumerate(machine_counts_by_bucket(machine, buckets, keep)):
            upstream[index] += rejected
    return [
        LineCounts(produced, rejected, up)
        for (produced, rejected), up in zip(output, upstream, strict=True)
    ]


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
