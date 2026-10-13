"""Group a line's downtime events into line stop incidents (cascades).

Rules:
- Only breakdown, blocked and starved events take part (not planned, not no_data).
- Events are swept in time order (ties: breakdown first, then line position).
  An event that begins while the current incident is still open joins it;
  otherwise it starts a new incident. An incident is open until its last
  member machine is running again.
- First observed stop = the earliest breakdown in the incident. Breakdowns
  starting at exactly that moment are all first stops (simultaneous). With no
  breakdown at all, the origin is "unknown" and there is no first machine.
- Incidents keep their database id across rebuilds: they are matched by `key`,
  the identity of their earliest member.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from apps.downtime.models import (
    INCIDENT_CATEGORIES,
    DowntimeCategory,
    DowntimeEvent,
    IncidentOrigin,
    LineStopIncident,
)
from apps.downtime.services.windows import Window
from apps.organizations.models import ProductionLine


@dataclass
class Cascade:
    members: list[DowntimeEvent] = field(default_factory=list)
    ended_at: datetime | None = None  # None while any member is ongoing

    def is_open_at(self, moment: datetime) -> bool:
        return self.ended_at is None or moment < self.ended_at

    def add(self, event: DowntimeEvent) -> None:
        if not self.members:
            self.ended_at = event.ended_at
        elif self.ended_at is not None:
            self.ended_at = None if event.ended_at is None else max(self.ended_at, event.ended_at)
        self.members.append(event)


def group_events(events: Sequence[DowntimeEvent]) -> list[Cascade]:
    cascades: list[Cascade] = []
    for event in sorted(events, key=_sort_key):
        if not cascades or not cascades[-1].is_open_at(event.started_at):
            cascades.append(Cascade())
        cascades[-1].add(event)
    return cascades


def regroup_incidents(line: ProductionLine, window: Window) -> None:
    """Recompute the incidents of `line` around `window` (widened to whole cascades)."""
    events, span = _load_cascades(line, window)

    stale = {
        incident.key: incident
        for incident in LineStopIncident.objects.filter(line=line).filter(
            span.overlap_q("started_at", "ended_at")
        )
    }
    for cascade in group_events(events):
        incident = _save_cascade(line, cascade)
        stale.pop(incident.key, None)
    for incident in stale.values():
        incident.delete()  # its former members were re-linked above (FK is SET_NULL)

    # Events that cannot be incident members never carry a link.
    DowntimeEvent.objects.filter(line=line).filter(span.overlap_q()).exclude(
        category__in=INCIDENT_CATEGORIES
    ).update(incident=None, is_first_stop=False)


def _load_cascades(line: ProductionLine, window: Window) -> tuple[list[DowntimeEvent], Window]:
    """Candidate events touching the window, widened until no cascade is cut in two."""
    candidates = DowntimeEvent.objects.filter(
        line=line, is_obsolete=False, category__in=INCIDENT_CATEGORIES
    ).select_related("machine")

    span = window
    # Incidents currently touching the window must be rebuilt (or removed) as a whole.
    for incident in LineStopIncident.objects.filter(line=line).filter(
        window.overlap_q("started_at", "ended_at")
    ):
        span = span.widen(incident.started_at, incident.ended_at)

    while True:
        events = list(candidates.filter(span.overlap_q()))
        widened = span
        for event in events:
            widened = widened.widen(event.started_at, event.ended_at)
        if widened == span:
            return events, span
        span = widened


def _sort_key(event: DowntimeEvent) -> tuple[object, ...]:
    return (
        event.started_at,
        0 if event.category == DowntimeCategory.BREAKDOWN else 1,
        event.machine.position,
        event.start_kind,
        event.start_event_id,
    )


def _save_cascade(line: ProductionLine, cascade: Cascade) -> LineStopIncident:
    members = sorted(cascade.members, key=_sort_key)
    breakdowns = [m for m in members if m.category == DowntimeCategory.BREAKDOWN]
    first_stops: list[DowntimeEvent] = []
    if breakdowns:
        earliest = min(b.started_at for b in breakdowns)
        first_stops = [b for b in breakdowns if b.started_at == earliest]
    first_machine = min((b.machine for b in first_stops), key=lambda m: m.position, default=None)

    incident, _ = LineStopIncident.objects.update_or_create(
        key=members[0].identity,
        defaults={
            "line": line,
            "started_at": members[0].started_at,
            "ended_at": cascade.ended_at,
            "origin": IncidentOrigin.MACHINE_STOP if first_stops else IncidentOrigin.UNKNOWN,
            "first_machine": first_machine,
            "has_simultaneous_first_stops": len(first_stops) > 1,
        },
    )
    first_ids = {m.pk for m in first_stops}
    for member in members:
        is_first = member.pk in first_ids
        if member.incident_id != incident.pk or member.is_first_stop != is_first:
            member.incident = incident
            member.is_first_stop = is_first
            member.save(update_fields=["incident", "is_first_stop", "updated_at"])
    return incident
