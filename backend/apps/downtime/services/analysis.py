"""Downtime analysis: the one place where lost time is added up (CLAUDE.md rule 3).

Two views:
- **line view** (default): when one machine stops, others become blocked or starved;
  adding all of them would multiply the lost time. So each line stop incident is
  ONE entry, lasting from its first stop until the last affected machine runs again,
  attributed to its first observed stop (machine, current classification, alarm).
  An incident with no breakdown (origin unknown) is attributed to its earliest
  member. Planned and no-data time, when included, is merged per line and
  category so a line-wide break counts once.
- **machine view**: every downtime event of every machine, *including* blocked
  and starved time. For maintenance analysis; totals are larger by design.

Every entry is clipped to the requested range; ongoing stops count up to `now`.
Durations are kept in whole microseconds, so group totals add up exactly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any

from django.db.models import Min, Prefetch

from apps.downtime.models import (
    INCIDENT_CATEGORIES,
    DowntimeCategory,
    DowntimeEvent,
    LineStopIncident,
)
from apps.organizations.models import Machine, ProductionLine

LINE_VIEW = "line"
MACHINE_VIEW = "machine"
VIEWS = (LINE_VIEW, MACHINE_VIEW)
OPTIONAL_CATEGORIES = frozenset({DowntimeCategory.PLANNED, DowntimeCategory.NO_DATA})
GROUP_BY = ("reason", "machine", "category", "alarm_code")

VIEW_NOTES = {
    LINE_VIEW: (
        "Line view: each line stop is counted once and attributed to its first observed "
        "stop. Blocked and starved consequences are not added."
    ),
    MACHINE_VIEW: (
        "Machine view: every machine's downtime, including time blocked or starved because "
        "of other machines. Totals are larger than the line view because one line stop is "
        "counted on several machines."
    ),
}

EVENT_SELECT = (
    "machine",
    "line__factory",
    "incident",
    "current_classification__reason",
    "current_classification__created_by",
)


@dataclass(frozen=True)
class AnalysisFilters:
    start: datetime
    end: datetime
    now: datetime
    view: str = LINE_VIEW
    include: frozenset[str] = frozenset()  # planned and/or no_data
    machine_id: int | None = None
    categories: frozenset[str] | None = None
    reason: str | None = None  # reason code, or "unclassified"
    alarm: str | None = None  # alarm code, or "none"
    classified: bool | None = None
    min_duration: float | None = None
    max_duration: float | None = None

    @property
    def effective_end(self) -> datetime:
        return min(self.end, self.now)


@dataclass
class Entry:
    """One unit of lost time in the chosen view."""

    kind: str  # "incident", "event" or "cluster"
    started_at: datetime
    ended_at: datetime | None
    clipped_micros: int
    attributed: DowntimeEvent
    speed_per_hour: int
    incident_id: int | None = None
    has_secondary_breakdown: bool = False
    origin_unknown: bool = False
    members: tuple[DowntimeEvent, ...] = field(default_factory=tuple)

    @property
    def category(self) -> str:
        return self.attributed.category

    @property
    def machine(self) -> Machine:
        return self.attributed.machine

    @property
    def reason(self) -> Any:
        classification = self.attributed.current_classification
        return classification.reason if classification else None

    @property
    def clipped_seconds(self) -> Fraction:
        return Fraction(self.clipped_micros, 1_000_000)


# --- Clipping --------------------------------------------------------------------------


def _micros(delta: timedelta) -> int:
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def clipped_micros(
    started_at: datetime, ended_at: datetime | None, start: datetime, end: datetime
) -> int:
    """Length of [started_at, ended_at or end] inside [start, end], in microseconds."""
    begin = max(started_at, start)
    finish = min(ended_at or end, end)
    return max(0, _micros(finish - begin))


# --- Building entries ------------------------------------------------------------------


def _line_speeds(lines: Iterable[ProductionLine]) -> dict[int, int]:
    return dict(
        Machine.objects.filter(line__in=lines)
        .values("line_id")
        .annotate(speed=Min("nominal_speed_per_hour"))
        .values_list("line_id", "speed")
    )


def _events_in_range(lines: Sequence[ProductionLine], f: AnalysisFilters) -> Any:
    return (
        DowntimeEvent.objects.filter(
            line__in=lines, is_obsolete=False, started_at__lt=f.effective_end
        )
        .exclude(ended_at__lte=f.start)
        .select_related(*EVENT_SELECT)
    )


def build_entries(lines: Sequence[ProductionLine], f: AnalysisFilters) -> list[Entry]:
    """All entries of the chosen view in the range, before the attribute filters."""
    end = f.effective_end
    if end <= f.start:
        return []
    allowed = set(INCIDENT_CATEGORIES) | set(f.include)

    if f.view == MACHINE_VIEW:
        return [
            Entry(
                kind="event",
                started_at=event.started_at,
                ended_at=event.ended_at,
                clipped_micros=clipped_micros(event.started_at, event.ended_at, f.start, end),
                attributed=event,
                speed_per_hour=event.machine.nominal_speed_per_hour,
                incident_id=event.incident_id,
                members=(event,),
            )
            for event in _events_in_range(lines, f).filter(category__in=allowed)
        ]

    speeds = _line_speeds(lines)
    entries = [
        _incident_entry(incident, f.start, end, speeds.get(incident.line_id, 0))
        for incident in LineStopIncident.objects.filter(line__in=lines, started_at__lt=end)
        .exclude(ended_at__lte=f.start)
        .prefetch_related(
            Prefetch("events", queryset=DowntimeEvent.objects.select_related(*EVENT_SELECT))
        )
    ]
    optional = [c for c in OPTIONAL_CATEGORIES if c in f.include]
    if optional:
        events = list(_events_in_range(lines, f).filter(category__in=optional))
        entries.extend(_clusters(events, f.start, end, speeds))
    return [e for e in entries if e.clipped_micros > 0]


def _incident_entry(
    incident: LineStopIncident, start: datetime, end: datetime, speed: int
) -> Entry:
    members = sorted(incident.events.all(), key=lambda e: (e.started_at, e.machine.position, e.pk))
    firsts = [m for m in members if m.is_first_stop]
    preferred = [m for m in firsts if m.machine_id == incident.first_machine_id]
    attributed = (preferred or firsts or members)[0]
    return Entry(
        kind="incident",
        started_at=incident.started_at,
        ended_at=incident.ended_at,
        clipped_micros=clipped_micros(incident.started_at, incident.ended_at, start, end),
        attributed=attributed,
        speed_per_hour=speed,
        incident_id=incident.pk,
        has_secondary_breakdown=any(is_secondary_breakdown(m) for m in members),
        origin_unknown=not firsts,
        members=tuple(members),
    )


def _clusters(
    events: list[DowntimeEvent], start: datetime, end: datetime, speeds: dict[int, int]
) -> list[Entry]:
    """Merge overlapping planned (or no-data) events of a line into one entry each."""
    entries: list[Entry] = []
    groups: dict[tuple[int, str], list[DowntimeEvent]] = defaultdict(list)
    for event in events:
        groups[(event.line_id, event.category)].append(event)
    for (line_id, _), group in groups.items():
        group.sort(key=lambda e: (e.started_at, e.machine.position, e.pk))
        cluster: list[DowntimeEvent] = []
        cluster_end: datetime | None = None
        for event in group:
            if cluster and (cluster_end is None or event.started_at < cluster_end):
                cluster.append(event)
                if cluster_end is not None:
                    cluster_end = (
                        None if event.ended_at is None else max(cluster_end, event.ended_at)
                    )
                continue
            if cluster:
                entries.append(_cluster_entry(cluster, cluster_end, start, end, speeds[line_id]))
            cluster, cluster_end = [event], event.ended_at
        if cluster:
            entries.append(_cluster_entry(cluster, cluster_end, start, end, speeds[line_id]))
    return entries


def _cluster_entry(
    cluster: list[DowntimeEvent],
    cluster_end: datetime | None,
    start: datetime,
    end: datetime,
    speed: int,
) -> Entry:
    first = cluster[0]
    return Entry(
        kind="cluster",
        started_at=first.started_at,
        ended_at=cluster_end,
        clipped_micros=clipped_micros(first.started_at, cluster_end, start, end),
        attributed=first,
        speed_per_hour=speed,
        members=tuple(cluster),
    )


def is_secondary_breakdown(event: DowntimeEvent) -> bool:
    """A breakdown inside an incident that is not its first observed stop."""
    return (
        event.incident_id is not None
        and event.category == DowntimeCategory.BREAKDOWN
        and not event.is_first_stop
    )


def matches(entry: Entry, f: AnalysisFilters) -> bool:
    """The attribute filters, applied to the entry's attributed event."""
    if f.machine_id is not None and entry.machine.pk != f.machine_id:
        return False
    if f.categories is not None and entry.category not in f.categories:
        return False
    reason = entry.reason
    if f.classified is not None and (reason is not None) != f.classified:
        return False
    if f.reason is not None:
        if f.reason == "unclassified":
            if reason is not None:
                return False
        elif reason is None or reason.code != f.reason:
            return False
    if f.alarm is not None:
        alarm = entry.attributed.alarm_code
        if (f.alarm == "none" and alarm) or (f.alarm != "none" and alarm != f.alarm):
            return False
    seconds = entry.clipped_micros / 1_000_000
    if f.min_duration is not None and seconds < f.min_duration:
        return False
    return not (f.max_duration is not None and seconds > f.max_duration)


def select_entries(lines: Sequence[ProductionLine], f: AnalysisFilters) -> list[Entry]:
    return [e for e in build_entries(lines, f) if matches(e, f)]


# --- Results ---------------------------------------------------------------------------


def _seconds(micros: int) -> float:
    return round(micros / 1_000_000, 3)


def _loss(entries: Iterable[Entry], basis: str) -> dict[str, Any]:
    units = sum((e.clipped_seconds * e.speed_per_hour / 3600 for e in entries), Fraction(0))
    rounded = int(units + Fraction(1, 2))  # half up
    return {"units": rounded, "is_estimate": True, "basis": basis}


def _loss_basis(view: str) -> str:
    if view == LINE_VIEW:
        return "duration x line nominal speed (slowest machine)"
    return "duration x the machine's nominal speed"


def machine_summary(machine: Machine) -> dict[str, Any]:
    return {"id": machine.pk, "external_id": machine.external_id, "name": machine.name}


def reason_summary(reason: Any) -> dict[str, Any] | None:
    if reason is None:
        return None
    return {"id": reason.pk, "code": reason.code, "name": reason.name, "category": reason.category}


def _group_key(entry: Entry, group_by: str) -> tuple[str, str]:
    if group_by == "reason":
        reason = entry.reason
        if reason is None:
            return "unclassified", "Unclassified"
        return f"reason:{reason.pk}", f"{reason.code} · {reason.name}"
    if group_by == "machine":
        machine = entry.machine
        return f"machine:{machine.pk}", f"{machine.external_id} {machine.name}"
    if group_by == "category":
        return f"category:{entry.category}", DowntimeCategory(entry.category).label
    alarm = entry.attributed.alarm_code
    return (f"alarm:{alarm}", alarm) if alarm else ("alarm:none", "No alarm code")


def pareto(entries: Sequence[Entry], group_by: str, view: str) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key, label = _group_key(entry, group_by)
        group = groups.setdefault(key, {"key": key, "label": label, "entries": []})
        group["entries"].append(entry)

    total = sum(e.clipped_micros for e in entries)
    ordered = sorted(
        groups.values(),
        key=lambda g: (-sum(e.clipped_micros for e in g["entries"]), g["label"]),
    )
    basis = _loss_basis(view)
    result_groups = []
    running = 0
    for group in ordered:
        micros = sum(e.clipped_micros for e in group["entries"])
        running += micros
        result_groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "total_seconds": _seconds(micros),
                "total_micros": micros,
                "occurrences": len(group["entries"]),
                "estimated_lost_units": _loss(group["entries"], basis),
                "share": round(micros / total, 6) if total else 0.0,
                "cumulative_share": round(running / total, 6) if total else 0.0,
            }
        )
    if result_groups and total:
        result_groups[-1]["cumulative_share"] = 1.0  # exact: running == total
    return {
        "view": view,
        "view_note": VIEW_NOTES[view],
        "group_by": group_by,
        "total_seconds": _seconds(total),
        "total_micros": total,
        "total_occurrences": len(entries),
        "estimated_lost_units": _loss(entries, basis),
        "groups": result_groups,
    }


def summary(entries: Sequence[Entry], view: str) -> dict[str, Any]:
    total = sum(e.clipped_micros for e in entries)
    longest = max(
        entries, key=lambda e: (e.clipped_micros, -e.started_at.timestamp()), default=None
    )
    return {
        "view": view,
        "view_note": VIEW_NOTES[view],
        "total_seconds": _seconds(total),
        "total_micros": total,
        "stops": len(entries),
        "unclassified": sum(1 for e in entries if e.reason is None),
        "secondary_breakdowns": len(
            {e.incident_id for e in entries if e.kind == "incident" and e.has_secondary_breakdown}
        ),
        "longest": (
            {
                "machine": machine_summary(longest.machine),
                "started_at": longest.started_at,
                "duration_seconds": _seconds(longest.clipped_micros),
                "category": longest.category,
                "reason": reason_summary(longest.reason),
                "incident": longest.incident_id,
            }
            if longest
            else None
        ),
        "estimated_lost_units": _loss(entries, _loss_basis(view)),
    }


def recurring(lines: Sequence[ProductionLine], f: AnalysisFilters) -> dict[str, Any]:
    """Breakdowns (first or secondary) repeating on a machine for the same reason or alarm."""
    end = f.effective_end
    events = _events_in_range(lines, f).filter(category=DowntimeCategory.BREAKDOWN)
    buckets: dict[tuple[int, str], list[DowntimeEvent]] = defaultdict(list)
    for event in events:
        reason = event.current_classification.reason if event.current_classification else None
        key = f"reason:{reason.pk}" if reason else f"alarm:{event.alarm_code or ''}"
        buckets[(event.machine_id, key)].append(event)

    items = []
    for group in buckets.values():
        first = group[0]
        threshold = first.line.factory.recurring_stop_threshold
        if len(group) < threshold:
            continue
        reason = first.current_classification.reason if first.current_classification else None
        micros = sum(clipped_micros(e.started_at, e.ended_at, f.start, end) for e in group)
        items.append(
            {
                "machine": machine_summary(first.machine),
                "reason": reason_summary(reason),
                "alarm_code": None if reason else first.alarm_code,
                "count": len(group),
                "threshold": threshold,
                "total_seconds": _seconds(micros),
                "last_occurrence": max(e.started_at for e in group),
            }
        )
    items.sort(key=lambda i: (-i["count"], -i["total_seconds"]))
    thresholds = {line.factory.recurring_stop_threshold for line in lines}
    return {"threshold": min(thresholds) if thresholds else None, "items": items}


# --- Which stops need a reason ---------------------------------------------------------


def needs_reason_ids(
    lines: Sequence[ProductionLine], start: datetime, end: datetime, now: datetime
) -> list[int]:
    """Stops that should be classified: each line entry's attributed event (first observed
    stops, origin-unknown leads, planned stops) and every secondary breakdown.
    Blocked and starved consequences never need a reason; neither does no-data time."""
    f = AnalysisFilters(
        start=start, end=end, now=now, include=frozenset({DowntimeCategory.PLANNED})
    )
    ordered: list[int] = []
    for entry in sorted(build_entries(lines, f), key=lambda e: e.started_at):
        ordered.append(entry.attributed.pk)
        ordered.extend(
            m.pk for m in entry.members if is_secondary_breakdown(m) and m.pk != entry.attributed.pk
        )
    return ordered
