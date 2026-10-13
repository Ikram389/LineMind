"""TimeSet: a set of half-open time intervals [start, end), always merged and sorted.

Union, intersection and difference never count the same second twice, which is
what OEE needs when breaks, planned stops and downtime overlap. Durations are
exact (whole microseconds, returned as Fraction seconds).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class TimeSet:
    intervals: tuple[Interval, ...] = ()

    @classmethod
    def of(cls, intervals: Iterable[Interval]) -> TimeSet:
        ordered = sorted((s, e) for s, e in intervals if e > s)
        merged: list[Interval] = []
        for start, end in ordered:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return cls(tuple(merged))

    def __bool__(self) -> bool:
        return bool(self.intervals)

    def __or__(self, other: TimeSet) -> TimeSet:
        return TimeSet.of([*self.intervals, *other.intervals])

    def __and__(self, other: TimeSet) -> TimeSet:
        result: list[Interval] = []
        i = j = 0
        a, b = self.intervals, other.intervals
        while i < len(a) and j < len(b):
            start = max(a[i][0], b[j][0])
            end = min(a[i][1], b[j][1])
            if end > start:
                result.append((start, end))
            if a[i][1] < b[j][1]:
                i += 1
            else:
                j += 1
        return TimeSet(tuple(result))

    def __sub__(self, other: TimeSet) -> TimeSet:
        result: list[Interval] = []
        for start, end in self.intervals:
            cursor = start
            for o_start, o_end in other.intervals:
                if o_end <= cursor or o_start >= end:
                    continue
                if o_start > cursor:
                    result.append((cursor, o_start))
                cursor = max(cursor, o_end)
                if cursor >= end:
                    break
            if cursor < end:
                result.append((cursor, end))
        return TimeSet(tuple(result))

    def clip(self, start: datetime, end: datetime) -> TimeSet:
        return self & TimeSet.of([(start, end)])

    def seconds(self) -> Fraction:
        micros = sum(_micros(end - start) for start, end in self.intervals)
        return Fraction(micros, 1_000_000)

    def contains_end_inclusive(self, moment: datetime) -> bool:
        """True if start < moment <= end for some interval.

        Used for counter readings: a reading at `moment` reports what was produced
        up to `moment`, so it belongs to the interval that ends there.
        """
        return any(start < moment <= end for start, end in self.intervals)


def _micros(delta: timedelta) -> int:
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
