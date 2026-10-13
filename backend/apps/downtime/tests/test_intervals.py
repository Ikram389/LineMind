"""Pure interval logic (no database)."""

import uuid
from datetime import UTC, datetime, timedelta

from apps.downtime.services.durations import duration_seconds, exceeds_threshold
from apps.downtime.services.intervals import (
    Observation,
    Transition,
    effective_intervals,
    find_gaps,
    state_intervals,
)

T0 = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def transition(seconds: float, state: str, alarm: str | None = None) -> Transition:
    return Transition(at(seconds), uuid.uuid4(), state, alarm)


def test_each_state_lasts_until_next_different_state() -> None:
    intervals = state_intervals(
        [transition(0, "running"), transition(60, "stopped", "E-1"), transition(150, "running")]
    )

    assert [(i.state, i.started_at, i.ended_at, i.alarm_code) for i in intervals] == [
        ("running", at(0), at(60), None),
        ("stopped", at(60), at(150), "E-1"),
        ("running", at(150), None, None),  # latest interval stays open
    ]


def test_repeated_state_continues_first_interval() -> None:
    first = transition(60, "stopped", "E-1")
    intervals = state_intervals(
        [first, transition(70, "stopped", "E-2"), transition(90, "running")]
    )

    assert intervals[0].start_event_id == first.event_id
    assert (intervals[0].started_at, intervals[0].ended_at, intervals[0].alarm_code) == (
        at(60),
        at(90),
        "E-1",
    )


def test_order_is_by_timestamp_not_input_order() -> None:
    events = [transition(150, "running"), transition(0, "running"), transition(60, "stopped")]

    assert [i.state for i in state_intervals(events)] == ["running", "stopped", "running"]
    assert state_intervals(events) == state_intervals(list(reversed(events)))


def test_equal_timestamps_ordered_by_event_id() -> None:
    a = Transition(at(10), uuid.UUID(int=1), "stopped", None)
    b = Transition(at(10), uuid.UUID(int=2), "blocked", None)

    assert state_intervals([b, a]) == state_intervals([a, b])
    assert [i.state for i in state_intervals([b, a])] == ["stopped", "blocked"]


def test_gaps_longer_than_threshold_only() -> None:
    observations = [Observation(at(s), uuid.uuid4()) for s in (0, 10, 20, 150, 160)]

    gaps = find_gaps(observations, stale_after_seconds=60)

    assert [(g.started_at, g.ended_at) for g in gaps] == [(at(20), at(150))]


def test_gap_cuts_state_interval_and_state_resumes_after() -> None:
    running = transition(0, "running")
    observations = [Observation(at(s), uuid.uuid4()) for s in (0, 10, 20)]
    after_gap = Observation(at(150), uuid.uuid4())
    observations.append(after_gap)

    intervals = effective_intervals([running], observations, stale_after_seconds=60)

    assert [(i.start_kind, i.state, i.started_at, i.ended_at) for i in intervals] == [
        ("transition", "running", at(0), at(20)),
        ("gap", "unknown", at(20), at(150)),
        ("resume", "running", at(150), None),
    ]
    assert intervals[2].start_event_id == after_gap.event_id


def test_trailing_silence_is_not_a_gap() -> None:
    observations = [Observation(at(0), uuid.uuid4())]

    assert find_gaps(observations, 60) == []


def test_duration_of_open_interval_grows_with_now() -> None:
    assert duration_seconds(at(0), None, now=at(30)) == 30
    assert duration_seconds(at(0), None, now=at(45)) == 45
    assert duration_seconds(at(0), at(10), now=at(45)) == 10


def test_exceeds_threshold_is_strictly_longer() -> None:
    assert not exceeds_threshold(at(0), at(600), 600, now=at(900))
    assert exceeds_threshold(at(0), at(601), 600, now=at(900))
    assert exceeds_threshold(at(0), None, 600, now=at(601))
