"""Current status of every machine on a line (REST /lines/{id}/status/ and live messages).

Rules:
- The latest state is chosen by event *timestamp* (when it happened), never by
  arrival order. Ties are broken by event_id, as in the downtime derivation.
- `state_since` is when the current state began: the first event of the current
  run of that state (a repeated state event does not restart it). For a stale
  machine it is `last_seen`, the moment the data stopped.
- `last_seen` is the newest event timestamp of any type for that machine.
- If nothing was seen for longer than the factory's `stale_after_seconds`, or
  the machine never reported a state, the state is "unknown", never "running".
- `shift_count` / `shift_rejected`: production since the current shift started
  (shared counter rule, production/services/counters.py); null without a shift.
"""

from datetime import datetime
from typing import Any

from django.db.models import Max, Q
from django.utils import timezone

from apps.downtime.services.incident_summary import open_incident_summary
from apps.organizations.models import Machine, ProductionLine
from apps.production.event_types import MachineState
from apps.production.models import IngestedEvent, MachineStateEvent, ProductionEvent
from apps.production.services.counters import produced_between
from apps.production.services.shifts import current_shift


def get_line_status(line: ProductionLine, now: datetime | None = None) -> dict[str, Any]:
    now = now or timezone.now()
    shift = current_shift(line.factory, now)
    shift_start = shift.start if shift else None
    return {
        "line": {"id": line.id, "name": line.name},
        "factory_timezone": line.factory.timezone,
        "stale_after_seconds": line.factory.stale_after_seconds,
        "generated_at": now,
        "current_shift_start": shift_start,
        "machines": [
            machine_status(machine, now, shift_start)
            for machine in line.machines.select_related("line__factory").order_by("position")
        ],
        "open_incident": open_incident_summary(line),
    }


def is_stale(last_seen: datetime | None, now: datetime, threshold_seconds: int) -> bool:
    if last_seen is None:
        return True
    return (now - last_seen).total_seconds() > threshold_seconds


def machine_status(machine: Machine, now: datetime, shift_start: datetime | None) -> dict[str, Any]:
    states = MachineStateEvent.objects.filter(machine=machine)
    latest = states.order_by("-timestamp", "-event_id").first()
    last_seen = IngestedEvent.objects.filter(machine=machine).aggregate(last=Max("timestamp"))[
        "last"
    ]
    stale = is_stale(last_seen, now, machine.line.factory.stale_after_seconds)
    last_count = (
        ProductionEvent.objects.filter(machine=machine).order_by("-timestamp", "-event_id").first()
    )
    last_alarm = (
        states.exclude(alarm_code__isnull=True)
        .exclude(alarm_code="")
        .order_by("-timestamp", "-event_id")
        .values_list("alarm_code", "timestamp")
        .first()
    )

    if stale or latest is None:
        state = MachineState.UNKNOWN.value
        state_since = last_seen
        alarm_code = None
    else:
        state = latest.state
        state_since = _run_start(states, latest)
        alarm_code = latest.alarm_code

    shift_count = shift_rejected = None
    if shift_start is not None:
        shift_count, shift_rejected = produced_between(machine, shift_start, now)

    return {
        "id": machine.id,
        "external_id": machine.external_id,
        "name": machine.name,
        "position": machine.position,
        "state": state,
        "reported_state": latest.state if latest else None,
        "state_since": state_since,
        "alarm_code": alarm_code,  # alarm of the current state (e.g. the current stop)
        "last_alarm_code": last_alarm[0] if last_alarm else None,
        "last_alarm_at": last_alarm[1] if last_alarm else None,
        "is_stale": stale,
        "last_seen": last_seen,
        "shift_count": shift_count,
        "shift_rejected": shift_rejected,
        "last_count": (
            {
                "count": last_count.count,
                "rejected": last_count.rejected,
                "timestamp": last_count.timestamp,
            }
            if last_count
            else None
        ),
    }


def _run_start(states: Any, latest: MachineStateEvent) -> datetime:
    """When the current run of `latest.state` began (repeated states do not restart it)."""
    before_latest = Q(timestamp__lt=latest.timestamp) | Q(
        timestamp=latest.timestamp, event_id__lt=latest.event_id
    )
    previous_other = (
        states.filter(before_latest)
        .exclude(state=latest.state)
        .order_by("-timestamp", "-event_id")
        .first()
    )
    run = states.filter(state=latest.state)
    if previous_other is not None:
        run = run.filter(
            Q(timestamp__gt=previous_other.timestamp)
            | Q(timestamp=previous_other.timestamp, event_id__gt=previous_other.event_id)
        )
    first = run.order_by("timestamp", "event_id").first()
    return first.timestamp if first else latest.timestamp
