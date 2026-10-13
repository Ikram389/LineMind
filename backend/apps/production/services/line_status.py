"""Current status of every machine on a line.

Rules:
- The latest state is chosen by event *timestamp* (when it happened), never by
  arrival order. Ties are broken by event_id, as in the downtime derivation.
- `last_seen` is the newest event timestamp of any type for that machine.
- If nothing was seen for longer than the factory's `stale_after_seconds`, or
  the machine never reported a state, the state is "unknown", never "running".
"""

from datetime import datetime
from typing import Any

from django.db.models import Max
from django.utils import timezone

from apps.organizations.models import ProductionLine
from apps.production.event_types import MachineState
from apps.production.models import IngestedEvent, MachineStateEvent, ProductionEvent


def get_line_status(line: ProductionLine, now: datetime | None = None) -> dict[str, Any]:
    now = now or timezone.now()
    threshold = line.factory.stale_after_seconds
    machines = list(line.machines.order_by("position"))

    # One query each, using PostgreSQL DISTINCT ON to take the newest row per machine.
    latest_states = {
        event.machine_id: event
        for event in MachineStateEvent.objects.filter(machine__line=line)
        .order_by("machine_id", "-timestamp", "-event_id")
        .distinct("machine_id")
    }
    latest_counts = {
        event.machine_id: event
        for event in ProductionEvent.objects.filter(machine__line=line)
        .order_by("machine_id", "-timestamp", "-event_id")
        .distinct("machine_id")
    }
    last_seen_by_machine = dict(
        IngestedEvent.objects.filter(machine__line=line)
        .values("machine_id")
        .annotate(last_seen=Max("timestamp"))
        .values_list("machine_id", "last_seen")
    )

    return {
        "line": {"id": line.id, "name": line.name},
        "factory_timezone": line.factory.timezone,
        "stale_after_seconds": threshold,
        "generated_at": now,
        "machines": [
            _machine_status(
                machine,
                latest_states.get(machine.id),
                latest_counts.get(machine.id),
                last_seen_by_machine.get(machine.id),
                now,
                threshold,
            )
            for machine in machines
        ],
    }


def is_stale(last_seen: datetime | None, now: datetime, threshold_seconds: int) -> bool:
    if last_seen is None:
        return True
    return (now - last_seen).total_seconds() > threshold_seconds


def _machine_status(
    machine: Any,
    state_event: MachineStateEvent | None,
    count_event: ProductionEvent | None,
    last_seen: datetime | None,
    now: datetime,
    threshold: int,
) -> dict[str, Any]:
    stale = is_stale(last_seen, now, threshold)
    if stale or state_event is None:
        state = MachineState.UNKNOWN.value
    else:
        state = state_event.state

    return {
        "id": machine.id,
        "external_id": machine.external_id,
        "name": machine.name,
        "position": machine.position,
        "state": state,
        "reported_state": state_event.state if state_event else None,
        "state_since": state_event.timestamp if state_event else None,
        "alarm_code": state_event.alarm_code if state_event else None,
        "is_stale": stale,
        "last_seen": last_seen,
        "last_count": (
            {
                "count": count_event.count,
                "rejected": count_event.rejected,
                "timestamp": count_event.timestamp,
            }
            if count_event
            else None
        ),
    }
