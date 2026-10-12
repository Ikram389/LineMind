"""Run modes: when each tick is simulated, and which start time it gets.

- realtime:    simulated time starts now and follows the wall clock.
- accelerated: one real second = `speed` simulated seconds. Simulated time is
               placed so that it *ends* when the run ends, so no timestamp is
               ever in the future (the backend rejects events more than
               5 minutes ahead).
- backfill:    no waiting at all; the whole scenario must lie in the past.

In realtime/accelerated mode a tick is simulated once the wall clock has
reached the end of that tick, so its events are never ahead of real time.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from senders import EventSink
from simulation import Simulation

logger = logging.getLogger(__name__)


class Mode(StrEnum):
    REALTIME = "realtime"
    ACCELERATED = "accelerated"
    BACKFILL = "backfill"


class RunError(ValueError):
    """Invalid combination of options."""


def resolve_start(
    mode: Mode,
    duration_seconds: int,
    *,
    now: datetime,
    speed: float = 1.0,
    start: datetime | None = None,
    scenario_start: datetime | None = None,
) -> datetime:
    """The simulated start time for a run."""
    if mode == Mode.BACKFILL:
        chosen = start or scenario_start
        if chosen is None:
            raise RunError("Backfill needs --start (or a 'start' in the scenario).")
        if chosen.tzinfo is None:
            raise RunError("--start must include a timezone, e.g. 2026-10-05T06:00:00Z.")
        if chosen + timedelta(seconds=duration_seconds) > now:
            raise RunError(
                "Backfill must end in the past: start + duration is later than now. "
                "Choose an earlier --start or use --mode realtime/accelerated."
            )
        return chosen

    if start is not None:
        raise RunError("--start can only be used with --mode backfill.")
    pace = 1.0 if mode == Mode.REALTIME else speed
    if pace < 1:
        raise RunError("--speed must be at least 1.")
    # Simulated time runs `pace` times faster than real time, so start it early
    # enough that it reaches "now" exactly when the run finishes.
    lead = duration_seconds - duration_seconds / pace
    return (now - timedelta(seconds=lead)).replace(microsecond=0)


def run(
    simulation: Simulation,
    sink: EventSink,
    mode: Mode,
    *,
    speed: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    progress_every_ticks: int = 600,
) -> None:
    """Simulate every tick, pacing it according to `mode`, and hand events to `sink`."""
    pace = None if mode == Mode.BACKFILL else (1.0 if mode == Mode.REALTIME else speed)
    tick_seconds = simulation.scenario.tick_seconds
    real_start = clock()

    while not simulation.finished:
        if pace is not None:
            due = real_start + (simulation.tick + 1) * tick_seconds / pace
            wait = due - clock()
            if wait > 0:
                sleep(wait)
        sink.submit(simulation.step())
        sink.poll()
        if simulation.tick % progress_every_ticks == 0 or simulation.finished:
            logger.info(
                "Simulated %s / %s (%s)",
                timedelta(seconds=simulation.tick * tick_seconds),
                timedelta(seconds=simulation.total_ticks * tick_seconds),
                simulation.time_at(simulation.tick * tick_seconds).isoformat(),
            )
