"""Run modes: start-time placement and pacing (with a fake clock)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from events import Event
from runner import Mode, RunError, resolve_start, run
from senders import SendSummary
from simulation import Simulation
from tests.helpers import make_scenario

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)


class RecordingSink:
    """Records when (on the fake clock) each event was handed over."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.received: list[tuple[float, Event]] = []

    def submit(self, events: Sequence[Event]) -> None:
        self.received.extend((self.clock.now, e) for e in events)

    def poll(self) -> None:
        pass

    def close(self, drain_timeout: float = 0) -> SendSummary:
        return SendSummary()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_realtime_starts_now() -> None:
    assert resolve_start(Mode.REALTIME, 900, now=NOW) == NOW


def test_accelerated_run_ends_at_now() -> None:
    start = resolve_start(Mode.ACCELERATED, 900, now=NOW, speed=60)

    # 900 simulated seconds take 15 real seconds, so simulated time must end 15 s from now.
    assert start + timedelta(seconds=900) == NOW + timedelta(seconds=15)


@pytest.mark.parametrize(("speed", "duration"), [(60, 900), (10, 3600), (1, 300), (600, 28800)])
def test_accelerated_timestamps_never_ahead_of_wall_clock(speed: float, duration: int) -> None:
    start = resolve_start(Mode.ACCELERATED, duration, now=NOW, speed=speed)
    clock = FakeClock()
    sink = RecordingSink(clock)

    run(
        Simulation(make_scenario(duration=duration), start=start),
        sink,
        Mode.ACCELERATED,
        speed=speed,
        clock=clock,
        sleep=clock.sleep,
    )

    for real_elapsed, event in sink.received:
        wall_clock = NOW + timedelta(seconds=real_elapsed)
        assert event.timestamp <= wall_clock + timedelta(milliseconds=5)  # ms tie-breaks only
    assert clock.now == pytest.approx(duration / speed)


def test_backfill_does_not_wait() -> None:
    clock = FakeClock()
    sink = RecordingSink(clock)

    run(
        Simulation(make_scenario(duration=600)),
        sink,
        Mode.BACKFILL,
        clock=clock,
        sleep=clock.sleep,
    )

    assert clock.now == 0
    assert sink.received


def test_backfill_must_end_in_the_past() -> None:
    with pytest.raises(RunError, match="end in the past"):
        resolve_start(Mode.BACKFILL, 3600, now=NOW, start=NOW - timedelta(minutes=30))

    ok = resolve_start(Mode.BACKFILL, 3600, now=NOW, start=NOW - timedelta(hours=1))
    assert ok == NOW - timedelta(hours=1)


def test_backfill_uses_scenario_start_by_default() -> None:
    scenario_start = datetime(2026, 10, 5, 6, tzinfo=UTC)

    assert resolve_start(Mode.BACKFILL, 3600, now=NOW, scenario_start=scenario_start) == (
        scenario_start
    )


def test_start_option_only_for_backfill() -> None:
    with pytest.raises(RunError, match="only be used with --mode backfill"):
        resolve_start(Mode.ACCELERATED, 900, now=NOW, speed=60, start=NOW)


def test_speed_below_one_is_refused() -> None:
    with pytest.raises(RunError, match="at least 1"):
        resolve_start(Mode.ACCELERATED, 900, now=NOW, speed=0.5)
