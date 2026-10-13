"""Pure functions: raw points in time -> state intervals (no database access).

Ordering always uses (timestamp, event_id), never arrival order, so the result
is the same whatever order events arrived in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from apps.downtime.models import StartKind

UNKNOWN = "unknown"


@dataclass(frozen=True)
class Transition:
    timestamp: datetime
    event_id: UUID
    state: str
    alarm_code: str | None


@dataclass(frozen=True)
class Observation:
    """Any raw event (any type): proof that the machine was sending data at that moment."""

    timestamp: datetime
    event_id: UUID


@dataclass(frozen=True)
class Interval:
    start_kind: str
    start_event_id: UUID
    state: str
    started_at: datetime
    ended_at: datetime | None  # None = still ongoing
    alarm_code: str | None

    @property
    def identity(self) -> str:
        return f"{self.start_kind}:{self.start_event_id}"


@dataclass(frozen=True)
class Gap:
    started_at: datetime
    ended_at: datetime
    last_event_id: UUID  # last event before the silence
    next_event_id: UUID  # first event after the silence


def state_intervals(transitions: Sequence[Transition]) -> list[Interval]:
    """Each transition starts an interval that lasts until the next *different* state.

    A repeated state is not a transition: the interval continues from the first one.
    The last interval stays open.
    """
    ordered = sorted(transitions, key=lambda t: (t.timestamp, t.event_id))
    intervals: list[Interval] = []
    current: Transition | None = None
    for transition in ordered:
        if current is not None and transition.state == current.state:
            continue
        if current is not None:
            intervals.append(_interval(current, transition.timestamp))
        current = transition
    if current is not None:
        intervals.append(_interval(current, None))
    return intervals


def find_gaps(observations: Sequence[Observation], stale_after_seconds: int) -> list[Gap]:
    """Silences between two consecutive raw events longer than the stale threshold.

    Silence after the very last event is not a gap: the data may not have arrived yet.
    """
    ordered = sorted(observations, key=lambda o: (o.timestamp, o.event_id))
    limit = timedelta(seconds=stale_after_seconds)
    return [
        Gap(before.timestamp, after.timestamp, before.event_id, after.event_id)
        for before, after in zip(ordered, ordered[1:], strict=False)
        if after.timestamp - before.timestamp > limit
    ]


def effective_intervals(
    transitions: Sequence[Transition],
    observations: Sequence[Observation],
    stale_after_seconds: int,
) -> list[Interval]:
    """State intervals with telemetry gaps cut out and replaced by "unknown" intervals.

    After a gap, the state that was in force continues as a "resume" interval
    starting at the first event after the gap.
    """
    gaps = find_gaps(observations, stale_after_seconds)
    result: list[Interval] = []

    for interval in state_intervals(transitions):
        pieces = _cut_gaps(interval, gaps)
        result.extend(pieces)
    result.extend(
        Interval(StartKind.GAP, gap.last_event_id, UNKNOWN, gap.started_at, gap.ended_at, None)
        for gap in gaps
    )
    return sorted(result, key=lambda i: (i.started_at, i.start_kind, i.start_event_id))


def _cut_gaps(interval: Interval, gaps: Sequence[Gap]) -> list[Interval]:
    pieces: list[Interval] = []
    start = interval.started_at
    kind, event_id, alarm = interval.start_kind, interval.start_event_id, interval.alarm_code
    for gap in gaps:
        if gap.ended_at <= start:
            continue
        if interval.ended_at is not None and gap.started_at >= interval.ended_at:
            break
        if gap.started_at > start:
            pieces.append(Interval(kind, event_id, interval.state, start, gap.started_at, alarm))
        # Continue after the gap, identified by the first event after it.
        start = gap.ended_at
        kind, event_id, alarm = StartKind.RESUME, gap.next_event_id, None
    if interval.ended_at is None or interval.ended_at > start:
        pieces.append(Interval(kind, event_id, interval.state, start, interval.ended_at, alarm))
    return pieces


def _interval(transition: Transition, ended_at: datetime | None) -> Interval:
    return Interval(
        StartKind.TRANSITION,
        transition.event_id,
        transition.state,
        transition.timestamp,
        ended_at,
        transition.alarm_code,
    )
