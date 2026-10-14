"""What the line was doing when a defect was detected (computed when read, never stored).

For each inspection result:
- the product and production order running at that moment;
- the station machine's state at that moment and its last alarm code;
- the latest line stop incident on the line that *ended* within the factory's
  `quality_incident_window_minutes` before the defect, with its first observed stop.

This is context, not a diagnosis: the wording says when things happened
("Occurred 2 min after incident #14 ended"), never that one caused the other.
Computed on read because incidents and orders can still change (late events,
edited orders); a list of results is handled in a few batched queries.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.organizations.models import ProductionLine
from apps.production.models import MachineStateEvent
from apps.production.services.orders import active_orders
from apps.quality.models import InspectionResult


@dataclass(frozen=True)
class _Order:
    start: datetime
    end: datetime
    pk: int
    product: dict[str, Any]

    def covers(self, moment: datetime) -> bool:
        return self.start < moment <= self.end  # the same rule as the OEE (OrderSpan)


def elapsed_text(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} s"
    return f"{int(seconds // 60)} min"


def incident_text(incident_id: int, seconds_after: float, first: dict[str, Any] | None) -> str:
    text = f"Occurred {elapsed_text(seconds_after)} after incident #{incident_id} ended"
    if first is not None:
        detail = first["machine"] + (f", {first['alarm_code']}" if first["alarm_code"] else "")
        text += f" (first observed stop: {detail})"
    return text


def _orders(
    lines: Sequence[ProductionLine], start: datetime, end: datetime
) -> dict[int, list[_Order]]:
    by_line: dict[int, list[_Order]] = defaultdict(list)
    for line in lines:
        for order in (
            active_orders(line)
            .filter(effective_from__lt=end, effective_to__gte=start)
            .select_related("product")
        ):
            by_line[line.pk].append(
                _Order(
                    order.effective_from,
                    order.effective_to,
                    order.pk,
                    {"id": order.product_id, "sku": order.product.sku, "name": order.product.name},
                )
            )
    return by_line


class _Timeline:
    """Events of one machine sorted by time, to find "the latest at or before t"."""

    def __init__(self, rows: list[tuple[datetime, Any]]) -> None:
        rows.sort(key=lambda r: r[0])
        self.times = [r[0] for r in rows]
        self.values = [r[1] for r in rows]

    def at(self, moment: datetime) -> Any:
        index = bisect_right(self.times, moment)
        return self.values[index - 1] if index else None


def _timelines(
    machine_ids: set[int], start: datetime, end: datetime, alarms_only: bool
) -> dict[int, _Timeline]:
    events = MachineStateEvent.objects.all()
    if alarms_only:
        events = events.filter(alarm_code__isnull=False)
    rows: dict[int, list[tuple[datetime, Any]]] = {m: [] for m in machine_ids}
    for machine_id in machine_ids:
        # The last one before the range, as the starting point.
        baseline = (
            events.filter(machine_id=machine_id, timestamp__lt=start)
            .order_by("-timestamp", "-event_id")
            .values_list("timestamp", "state", "alarm_code")
            .first()
        )
        if baseline:
            rows[machine_id].append((baseline[0], baseline))
    for row in (
        events.filter(machine_id__in=machine_ids, timestamp__gte=start, timestamp__lte=end)
        .order_by("timestamp", "event_id")
        .values_list("machine_id", "timestamp", "state", "alarm_code")
    ):
        rows[row[0]].append((row[1], row[1:]))
    return {m: _Timeline(r) for m, r in rows.items()}


def _incidents(
    lines: Sequence[ProductionLine], start: datetime, end: datetime
) -> dict[int, _Timeline]:
    """Closed incidents per line, by end time, with their first observed stop."""
    window = {
        line.pk: timedelta(minutes=line.factory.quality_incident_window_minutes) for line in lines
    }
    earliest = start - max(window.values(), default=timedelta(0))
    incidents = list(
        LineStopIncident.objects.filter(
            line__in=lines, ended_at__isnull=False, ended_at__gte=earliest, ended_at__lte=end
        ).values_list("pk", "line_id", "ended_at")
    )
    first_stops: dict[int, dict[str, Any]] = {}
    for incident_id, machine_name, alarm in (
        DowntimeEvent.objects.filter(
            incident_id__in=[i[0] for i in incidents], is_first_stop=True, is_obsolete=False
        )
        .order_by("started_at", "machine__position")
        .values_list("incident_id", "machine__name", "alarm_code")
    ):
        first_stops.setdefault(incident_id, {"machine": machine_name, "alarm_code": alarm})
    rows: dict[int, list[tuple[datetime, Any]]] = defaultdict(list)
    for pk, line_id, ended_at in incidents:
        rows[line_id].append((ended_at, (pk, ended_at, first_stops.get(pk))))
    return {line_id: _Timeline(r) for line_id, r in rows.items()}


def contexts_for(results: Sequence[InspectionResult]) -> dict[int, dict[str, Any]]:
    """The context of each result, keyed by result id."""
    if not results:
        return {}
    start = min(r.timestamp for r in results)
    end = max(r.timestamp for r in results)
    lines = list(
        ProductionLine.objects.select_related("factory").filter(pk__in={r.line_id for r in results})
    )
    line_by_id = {line.pk: line for line in lines}
    machine_ids = {r.machine_id for r in results}
    orders = _orders(lines, start, end)
    states = _timelines(machine_ids, start, end, alarms_only=False)
    alarms = _timelines(machine_ids, start, end, alarms_only=True)
    incidents = _incidents(lines, start, end)

    contexts: dict[int, dict[str, Any]] = {}
    for result in results:
        moment = result.timestamp
        order = next((o for o in orders.get(result.line_id, []) if o.covers(moment)), None)
        state = states[result.machine_id].at(moment)
        alarm = alarms[result.machine_id].at(moment)

        incident = None
        window = timedelta(
            minutes=line_by_id[result.line_id].factory.quality_incident_window_minutes
        )
        found = incidents[result.line_id].at(moment) if result.line_id in incidents else None
        if found is not None:
            incident_id, ended_at, first = found
            seconds_after = (moment - ended_at).total_seconds()
            if seconds_after <= window.total_seconds():
                incident = {
                    "id": incident_id,
                    "ended_at": ended_at,
                    "seconds_after": round(seconds_after, 3),
                    "first_observed_stop": first,
                    "text": incident_text(incident_id, seconds_after, first),
                }

        contexts[result.pk] = {
            "product": order.product if order else None,
            "order_id": order.pk if order else None,
            "machine_state": state[1] if state else "unknown",
            "machine_state_since": state[0] if state else None,
            "last_alarm_code": alarm[2] if alarm else None,
            "last_alarm_at": alarm[0] if alarm else None,
            "incident": incident,
        }
    return contexts
