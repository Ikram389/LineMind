"""Arrival order must never change the result: derivation sorts by event timestamp.

The same fixture is loaded twice, on two identical lines: once in timestamp
order and once shuffled. The derived downtime and incidents must be identical.
(A rebuild of the *same* shuffled database would not prove this: if the code
sorted by arrival, both would be wrong in the same way.)
"""

import random
import uuid
from typing import Any

import pytest

from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.downtime.tests.support import Bottling, create_bottling_line, read_fixture
from apps.production.services.ingestion import ingest_batch, ingest_event
from tests.helpers import World

# Every event_id must be unique, so the second copy gets new (deterministic) ids.
COPY_NAMESPACE = uuid.UUID("0b8e6a52-5d1c-4f43-9a0e-3a7f4c1d2e90")


def renamed(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**e, "event_id": str(uuid.uuid5(COPY_NAMESPACE, e["event_id"]))} for e in events]


def canonical(line: Bottling) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Everything derived for a line, without ids that differ between the two copies."""
    events = sorted(
        (
            e.machine.external_id,
            e.start_kind,
            e.category,
            e.started_at,
            e.ended_at,
            e.alarm_code,
            e.is_first_stop,
            e.incident.started_at if e.incident else None,
        )
        for e in DowntimeEvent.objects.filter(line=line.line).select_related("machine", "incident")
    )
    incidents = sorted(
        (
            i.started_at,
            i.ended_at,
            i.origin,
            i.first_machine.external_id if i.first_machine else None,
            i.has_simultaneous_first_stops,
            i.events.count(),
        )
        for i in LineStopIncident.objects.filter(line=line.line).select_related("first_machine")
    )
    return events, incidents


def send_in_batches(line: Bottling, events: list[dict[str, Any]], batch_size: int) -> None:
    for i in range(0, len(events), batch_size):
        results = ingest_batch(line.api_key, events[i : i + batch_size])
        assert {r.status for r in results} == {"created"}


@pytest.fixture
def ordered_and_shuffled(world: World, bottling: Bottling) -> tuple[Bottling, Bottling]:
    return bottling, create_bottling_line(world.factory_b, "Bottling Line (shuffled copy)")


@pytest.mark.parametrize("name", ["labeler_jam", "reference_1h", "sensor_dropout"])
@pytest.mark.parametrize(("seed", "batch_size"), [(7, 37), (2026, 500)])
def test_shuffled_batches_equal_timestamp_order(
    ordered_and_shuffled: tuple[Bottling, Bottling], name: str, seed: int, batch_size: int
) -> None:
    in_order, shuffled = ordered_and_shuffled
    events = sorted(read_fixture(name), key=lambda e: e["timestamp"])
    shuffled_events = renamed(events)
    random.Random(seed).shuffle(shuffled_events)

    send_in_batches(in_order, events, 500)
    send_in_batches(shuffled, shuffled_events, batch_size)

    expected = canonical(in_order)
    assert expected[0], "the fixture should produce downtime events"
    assert canonical(shuffled) == expected


def test_labeler_jam_reversed_one_by_one_still_finds_the_labeler_first(
    ordered_and_shuffled: tuple[Bottling, Bottling],
) -> None:
    """Worst case: newest event first, one request per event."""
    in_order, reversed_line = ordered_and_shuffled
    events = sorted(read_fixture("labeler_jam"), key=lambda e: e["timestamp"])
    send_in_batches(in_order, events, 500)

    for event in reversed(renamed(events)):
        assert ingest_event(reversed_line.api_key, event).status == "created"

    assert canonical(reversed_line) == canonical(in_order)
    incident = LineStopIncident.objects.get(line=reversed_line.line)
    assert incident.first_machine.external_id == "M05"
