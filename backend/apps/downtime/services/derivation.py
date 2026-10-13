"""Derive DowntimeEvent rows from raw observations, for one machine over a time window.

Steps for rebuild_machine(machine, start, end):
1. Widen the window to the next state transition after `end`, so every interval
   that touches the window is fully known.
2. Load the raw transitions and observation times needed (from the last
   transition at or before `start`).
3. Compute effective intervals (services/intervals.py) and keep the non-running
   ones; closed intervals shorter than the factory's minimum stop are dropped.
4. Upsert them by stable identity (start_kind, start_event_id). Rows in the window
   that are no longer produced are deleted, or marked obsolete if classified.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.db.models import Window as SqlWindow
from django.db.models.functions import Lag

from apps.downtime.models import DowntimeCategory, DowntimeEvent
from apps.downtime.services.durations import duration_seconds
from apps.downtime.services.incidents import regroup_incidents
from apps.downtime.services.intervals import (
    Interval,
    Observation,
    Transition,
    effective_intervals,
)
from apps.downtime.services.windows import Window, union
from apps.organizations.models import Machine, ProductionLine
from apps.production.models import IngestedEvent, MachineStateEvent

logger = logging.getLogger(__name__)

STATE_TO_CATEGORY: dict[str, str] = {
    "stopped": DowntimeCategory.BREAKDOWN,
    "blocked": DowntimeCategory.BLOCKED,
    "starved": DowntimeCategory.STARVED,
    "planned_stop": DowntimeCategory.PLANNED,
    "unknown": DowntimeCategory.NO_DATA,
}  # "running" is not downtime


def minimum_stop_seconds(machine: Machine) -> int:
    return int(machine.line.factory.oee_settings.get("minimum_stop_seconds", 5))


def is_downtime(interval: Interval, minimum_seconds: int) -> bool:
    if interval.state not in STATE_TO_CATEGORY:
        return False
    if interval.ended_at is None:
        return True  # ongoing stops are shown right away
    return duration_seconds(interval.started_at, interval.ended_at) >= minimum_seconds


def rebuild_machine(
    machine: Machine, start: datetime | None = None, end: datetime | None = None
) -> Window:
    """Recompute the machine's downtime events overlapping [start, end]. Returns the window used."""
    # Widen to the next transition: an event inserted before it can change (or merge
    # away) the interval it starts.
    window_end = _transition_after(machine, end) if end is not None else None
    window = Window(start, window_end)
    # Load one transition further so the interval starting at window_end is closed.
    load_until = _transition_after(machine, window_end) if window_end is not None else None
    stale_after = machine.line.factory.stale_after_seconds
    transitions, observations = _load_raw(machine, start, load_until, stale_after)
    computed = [
        interval
        for interval in effective_intervals(transitions, observations, stale_after)
        if window.overlaps(interval.started_at, interval.ended_at)
        and is_downtime(interval, minimum_stop_seconds(machine))
    ]
    _save(machine, window, computed)
    return window


def rebuild_line(
    line: ProductionLine, start: datetime | None = None, end: datetime | None = None
) -> None:
    """Recompute downtime events and incidents of every machine on a line."""
    with transaction.atomic():
        windows = [
            rebuild_machine(machine, start, end)
            for machine in line.machines.select_related("line__factory")
        ]
        regroup_incidents(line, union(windows))


def rebuild_after_ingestion(stored: Iterable[tuple[int, datetime]]) -> None:
    """Called by the ingestion service once per request with (machine_id, timestamp) pairs.

    Kept separate so it can later run as a background (Celery) task.
    A failure here never loses events: they are already stored, and
    `manage.py rebuild_downtime` can repair the derived data.
    """
    by_machine: dict[int, list[datetime]] = defaultdict(list)
    for machine_id, timestamp in stored:
        by_machine[machine_id].append(timestamp)
    if not by_machine:
        return

    try:
        with transaction.atomic():
            machines = Machine.objects.select_related("line__factory").filter(pk__in=by_machine)
            windows_by_line: dict[int, list[Window]] = defaultdict(list)
            lines: dict[int, ProductionLine] = {}
            for machine in machines:
                times = by_machine[machine.pk]
                window = rebuild_machine(machine, min(times), max(times))
                windows_by_line[machine.line_id].append(window)
                lines[machine.line_id] = machine.line
            for line_id, windows in windows_by_line.items():
                regroup_incidents(lines[line_id], union(windows))
    except Exception:
        logger.exception("Downtime derivation failed; run rebuild_downtime to repair.")


# --- internals -------------------------------------------------------------------------


def _transition_after(machine: Machine, moment: datetime) -> datetime | None:
    """Timestamp of the first state transition strictly after `moment` (None if none yet)."""
    return (
        MachineStateEvent.objects.filter(machine=machine, timestamp__gt=moment)
        .order_by("timestamp", "event_id")
        .values_list("timestamp", flat=True)
        .first()
    )


def _load_raw(
    machine: Machine, start: datetime | None, until: datetime | None, stale_after: int
) -> tuple[list[Transition], list[Observation]]:
    """Load just enough raw data to compute every interval touching [start, until].

    - The state in force at `start` comes from the last transition strictly before
      it (the "anchor"). A transition exactly at `start` ends that interval, so the
      interval is recomputed too.
    - Observations (any event) are only needed from the last gap before `start`
      (found by the database), or else from the last observation before `start`.
      Loading every event since the anchor would be slow during long runs.
    """
    states = MachineStateEvent.objects.filter(machine=machine)
    events = IngestedEvent.objects.filter(machine=machine)
    anchor: Transition | None = None

    if start is not None:
        anchor_row = (
            states.filter(timestamp__lt=start)
            .order_by("-timestamp", "-event_id")
            .values_list("timestamp", "event_id", "state", "alarm_code")
            .first()
        )
        lower = (
            events.filter(timestamp__lt=start)
            .order_by("-timestamp", "-event_id")
            .values_list("timestamp", flat=True)
            .first()
        )
        if anchor_row is not None:
            anchor = Transition(*anchor_row)
            lower = _last_gap_start(machine, anchor.timestamp, start, stale_after) or lower
        if lower is not None:
            states = states.filter(timestamp__gte=lower)
            events = events.filter(timestamp__gte=lower)
    if until is not None:
        states = states.filter(timestamp__lte=until)
        events = events.filter(timestamp__lte=until)

    transitions = [
        Transition(ts, event_id, state, alarm)
        for ts, event_id, state, alarm in states.values_list(
            "timestamp", "event_id", "state", "alarm_code"
        )
    ]
    if anchor is not None and anchor.event_id not in {t.event_id for t in transitions}:
        transitions.insert(0, anchor)
    observations = [
        Observation(ts, event_id) for ts, event_id in events.values_list("timestamp", "event_id")
    ]
    return transitions, observations


def _last_gap_start(
    machine: Machine, since: datetime, before: datetime, stale_after: int
) -> datetime | None:
    """Start of the last telemetry gap between `since` and `before` (computed in SQL)."""
    with_previous = IngestedEvent.objects.filter(
        machine=machine, timestamp__gte=since, timestamp__lt=before
    ).annotate(
        previous=SqlWindow(Lag("timestamp"), order_by=[F("timestamp").asc(), F("event_id").asc()])
    )
    return (
        with_previous.filter(timestamp__gt=F("previous") + timedelta(seconds=stale_after))
        .order_by("-timestamp", "-event_id")
        .values_list("previous", flat=True)
        .first()
    )


def _save(machine: Machine, window: Window, computed: Sequence[Interval]) -> None:
    existing = {
        row.identity: row
        for row in DowntimeEvent.objects.filter(machine=machine).filter(window.overlap_q())
    }
    wanted = {interval.identity for interval in computed}

    for interval in computed:
        values = {
            "machine_id": machine.pk,
            "line_id": machine.line_id,
            "state": interval.state,
            "category": STATE_TO_CATEGORY[interval.state],
            "started_at": interval.started_at,
            "ended_at": interval.ended_at,
            "alarm_code": interval.alarm_code,
            "is_obsolete": False,
        }
        row = (
            existing.get(interval.identity)
            or DowntimeEvent.objects.filter(
                start_kind=interval.start_kind, start_event_id=interval.start_event_id
            ).first()
        )
        if row is None:
            DowntimeEvent.objects.create(
                start_kind=interval.start_kind, start_event_id=interval.start_event_id, **values
            )
            continue
        changed = [name for name, value in values.items() if getattr(row, name) != value]
        if changed:  # skip the write when nothing changed (most rebuilds)
            for name in changed:
                setattr(row, name, values[name])
            row.save(update_fields=[*changed, "updated_at"])

    for identity, row in existing.items():
        if identity in wanted:
            continue
        if row.classifications.exists():
            # Never lose classifications: keep the row, hidden from normal lists.
            row.is_obsolete = True
            row.incident = None
            row.is_first_stop = False
            row.save(update_fields=["is_obsolete", "incident", "is_first_stop", "updated_at"])
        else:
            row.delete()
