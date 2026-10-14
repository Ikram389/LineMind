"""Turn raw `quality_defect_detected` events into InspectionResults.

- One result per defect event, identified by its event_id: processing the same event
  again updates the same row (idempotent), so reviews stay attached.
- Raw events are only read, never changed.
- Nothing is dropped: an unknown defect code or a machine without an active station
  still gives a result, with an empty defect type / station and a warning saying why.
- Called once per ingestion request (like the downtime rebuild), after configuration
  changes that affect the mapping, and by `manage.py rebuild_quality`.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.organizations.models import Machine, ProductionLine
from apps.production.event_types import EventType
from apps.production.models import IngestedEvent
from apps.quality.models import DefectType, InspectionResult, InspectionStation

BATCH_SIZE = 2000
MAPPED_FIELDS = ("station", "defect_type", "reported_code", "confidence", "source", "warnings")


def defect_events() -> QuerySet[IngestedEvent]:
    return IngestedEvent.objects.filter(event_type=EventType.QUALITY_DEFECT_DETECTED)


class _Catalogue:
    """Active stations by machine and defect types by (organization, code), loaded once."""

    def __init__(self) -> None:
        self._stations: dict[int, InspectionStation | None] = {}
        self._checked: dict[int, set[int]] = {}
        self._types: dict[tuple[int, str], DefectType | None] = {}

    def station(self, machine_id: int) -> InspectionStation | None:
        if machine_id not in self._stations:
            station = (
                InspectionStation.objects.filter(machine_id=machine_id, is_active=True)
                .prefetch_related("defect_types")
                .first()
            )
            self._stations[machine_id] = station
            if station is not None:
                self._checked[station.pk] = {t.pk for t in station.defect_types.all()}
        return self._stations[machine_id]

    def kept(self, station_id: int, machine_id: int) -> InspectionStation | None:
        """A result's own station, kept although archived (history stays as it was)."""
        station = (
            InspectionStation.objects.filter(pk=station_id, machine_id=machine_id)
            .prefetch_related("defect_types")
            .first()
        )
        if station is not None:
            self._checked[station.pk] = {t.pk for t in station.defect_types.all()}
        return station

    def checks(self, station: InspectionStation, defect_type: DefectType) -> bool:
        return defect_type.pk in self._checked.get(station.pk, set())

    def defect_type(self, organization_id: int, code: str) -> DefectType | None:
        key = (organization_id, code)
        if key not in self._types:
            # Archived types still match: an archived type keeps its history.
            self._types[key] = DefectType.objects.filter(
                organization_id=organization_id, code=code
            ).first()
        return self._types[key]


def parse_confidence(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    """(confidence, warning). Missing is fine; a bad value is kept out with a warning."""
    raw = payload.get("confidence")
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not 0 <= raw <= 1:
        return None, f"Confidence {raw!r} was ignored: it must be a number between 0 and 1."
    return float(raw), None


def mapped_fields(
    event: IngestedEvent,
    machine: Machine,
    catalogue: _Catalogue,
    current_station_id: int | None = None,
) -> dict[str, Any]:
    """Everything a result derives from its raw event and the current configuration.

    The station is the machine's active station. When the machine has none, a result
    keeps the station it already had (archiving a station never rewrites history).
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    code = str(payload.get("defect_code") or "").strip()
    warnings: list[str] = []

    station = catalogue.station(machine.pk)
    if station is None and current_station_id is not None:
        station = catalogue.kept(current_station_id, machine.pk)
    if station is None:
        warnings.append(f"No active inspection station is configured on {machine.name}.")

    defect_type = None
    if not code:
        warnings.append("The event has no defect code.")
    else:
        defect_type = catalogue.defect_type(machine.line.factory.organization_id, code)
        if defect_type is None:
            warnings.append(f"Unknown defect code '{code}': it is not in the defect catalogue.")
        elif station is not None and not catalogue.checks(station, defect_type):
            warnings.append(f"Station '{station.name}' is not configured to check {code}.")

    confidence, confidence_warning = parse_confidence(payload)
    if confidence_warning:
        warnings.append(confidence_warning)

    return {
        "station": station,
        "defect_type": defect_type,
        "reported_code": code[:50],
        "confidence": confidence,
        "source": station.source if station is not None else "event_api",
        "warnings": warnings,
    }


def _changed(result: InspectionResult, values: dict[str, Any]) -> bool:
    return any(
        getattr(result, f"{name}_id" if name in ("station", "defect_type") else name)
        != (value.pk if hasattr(value, "pk") else value)
        for name, value in values.items()
    )


def process_events(events: Iterable[IngestedEvent]) -> int:
    """Create or update the result of each defect event. Returns how many rows changed."""
    catalogue = _Catalogue()
    changed = 0
    batch: list[IngestedEvent] = []
    for event in events:
        batch.append(event)
        if len(batch) >= BATCH_SIZE:
            changed += _process_batch(batch, catalogue)
            batch = []
    if batch:
        changed += _process_batch(batch, catalogue)
    return changed


def _process_batch(events: list[IngestedEvent], catalogue: _Catalogue) -> int:
    machines = {
        m.pk: m
        for m in Machine.objects.select_related("line__factory").filter(
            pk__in={e.machine_id for e in events}
        )
    }
    existing = {
        r.event_id: r
        for r in InspectionResult.objects.filter(event_id__in=[e.event_id for e in events])
    }
    to_create: list[InspectionResult] = []
    to_update: list[InspectionResult] = []
    for event in events:
        machine = machines[event.machine_id]
        result = existing.get(event.event_id)
        values = mapped_fields(event, machine, catalogue, result.station_id if result else None)
        if result is None:
            to_create.append(
                InspectionResult(
                    event_id=event.event_id,
                    raw_event=event,
                    line_id=machine.line_id,
                    machine=machine,
                    timestamp=event.timestamp,
                    **values,
                )
            )
        elif _changed(result, values):
            for name, value in values.items():
                setattr(result, name, value)
            result.updated_at = timezone.now()
            to_update.append(result)
    with transaction.atomic():
        InspectionResult.objects.bulk_create(to_create, ignore_conflicts=True)
        InspectionResult.objects.bulk_update(to_update, [*MAPPED_FIELDS, "updated_at"])
    return len(to_create) + len(to_update)


def process_after_ingestion(event_ids: Iterable[UUID]) -> list[int]:
    """Process the defect events stored by one ingestion request; returns their line ids."""
    events = list(defect_events().filter(event_id__in=list(event_ids)).order_by("timestamp"))
    process_events(events)
    return sorted(
        {
            line_id
            for line_id in Machine.objects.filter(
                pk__in={e.machine_id for e in events}
            ).values_list("line_id", flat=True)
        }
    )


def rebuild_quality(
    line: ProductionLine, start: datetime | None = None, end: datetime | None = None
) -> int:
    """Re-derive every result of the line in [start, end) from the raw events."""
    events = defect_events().filter(machine__line=line)
    if start is not None:
        events = events.filter(timestamp__gte=start)
    if end is not None:
        events = events.filter(timestamp__lt=end)
    return process_events(events.order_by("timestamp", "event_id").iterator(chunk_size=BATCH_SIZE))


def reprocess_machines(machine_ids: Iterable[int]) -> int:
    """After a station change: re-map every result of these machines."""
    events = defect_events().filter(machine_id__in=set(machine_ids))
    return process_events(events.order_by("timestamp", "event_id").iterator(chunk_size=BATCH_SIZE))


def reprocess_code(organization_id: int, code: str) -> int:
    """After a defect type is created: results that reported its code get it."""
    raw_ids = InspectionResult.objects.filter(
        line__factory__organization_id=organization_id, reported_code=code, defect_type=None
    ).values_list("raw_event_id", flat=True)
    return process_events(IngestedEvent.objects.filter(pk__in=list(raw_ids)).order_by("timestamp"))
