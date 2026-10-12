"""POST /api/v1/events/ and /api/v1/events/batch/."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.production.event_types import EVENT_TYPE_TO_STATE
from apps.production.models import IngestedEvent, MachineStateEvent, ProductionEvent
from apps.production.services.api_keys import create_line_api_key
from apps.production.tests.events import make_event
from tests.helpers import World, create_machine

EVENTS_URL = "/api/v1/events/"
BATCH_URL = "/api/v1/events/batch/"


# --- Single events ---------------------------------------------------------------------


@pytest.mark.parametrize(("event_type", "state"), list(EVENT_TYPE_TO_STATE.items()))
def test_state_event_is_stored_with_mapped_state(
    world: World, sender: APIClient, event_type: str, state: str
) -> None:
    event = make_event(event_type, alarm_code="E-204")

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 201
    assert response.json() == {"event_id": event["event_id"], "status": "created"}
    ingested = IngestedEvent.objects.get(event_id=event["event_id"])
    assert ingested.machine == world.machine_a
    assert ingested.event_type == event_type
    state_event = MachineStateEvent.objects.get(event_id=event["event_id"])
    assert state_event.state == state
    assert state_event.machine == world.machine_a
    assert state_event.alarm_code == "E-204"
    assert state_event.source == "event_api"
    assert state_event.timestamp == ingested.timestamp
    assert not ProductionEvent.objects.exists()


def test_production_count_creates_production_event(world: World, sender: APIClient) -> None:
    event = make_event("production_count_updated", count=18420, rejected=12)

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 201
    production = ProductionEvent.objects.get(event_id=event["event_id"])
    assert (production.count, production.rejected) == (18420, 12)
    assert production.machine == world.machine_a
    assert not MachineStateEvent.objects.exists()


def test_production_count_without_rejected_stores_null(world: World, sender: APIClient) -> None:
    event = make_event("production_count_updated", count=100)

    sender.post(EVENTS_URL, event, format="json")

    assert ProductionEvent.objects.get(event_id=event["event_id"]).rejected is None


@pytest.mark.parametrize("event_type", ["sensor_reconnected", "quality_defect_detected"])
def test_raw_only_event_types_are_stored_only_as_ingested(
    world: World, sender: APIClient, event_type: str
) -> None:
    event = make_event(event_type, payload={"defect_code": "Q02"})

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 201
    assert IngestedEvent.objects.get(event_id=event["event_id"]).payload == {"defect_code": "Q02"}
    assert not MachineStateEvent.objects.exists()
    assert not ProductionEvent.objects.exists()


def test_ingested_event_keeps_everything_received(world: World, sender: APIClient) -> None:
    event = make_event(
        "machine_stopped", alarm_code="E-204", count=18420, rejected=12, payload={"temp": 41.5}
    )

    sender.post(EVENTS_URL, event, format="json")

    ingested = IngestedEvent.objects.get(event_id=event["event_id"])
    assert ingested.alarm_code == "E-204"
    assert (ingested.count, ingested.rejected) == (18420, 12)
    assert ingested.payload == {"temp": 41.5}
    assert ingested.received_at >= ingested.timestamp
    assert ingested.api_key.line == world.line_a


def test_timestamp_with_offset_is_stored_in_utc(world: World, sender: APIClient) -> None:
    event = make_event(timestamp="2026-01-15T11:05:00+01:00")

    sender.post(EVENTS_URL, event, format="json")

    stored = MachineStateEvent.objects.get(event_id=event["event_id"]).timestamp
    assert stored == datetime(2026, 1, 15, 10, 5, tzinfo=UTC)
    assert stored.utcoffset() == timedelta(0)


def test_old_events_are_accepted(world: World, sender: APIClient) -> None:
    event = make_event(at=timezone.now() - timedelta(days=30))

    assert sender.post(EVENTS_URL, event, format="json").status_code == 201


# --- Duplicates ------------------------------------------------------------------------


def test_same_event_id_twice_is_stored_once(world: World, sender: APIClient) -> None:
    event = make_event("machine_stopped")

    first = sender.post(EVENTS_URL, event, format="json")
    second = sender.post(EVENTS_URL, event, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == {"event_id": event["event_id"], "status": "duplicate"}
    assert IngestedEvent.objects.filter(event_id=event["event_id"]).count() == 1
    assert MachineStateEvent.objects.filter(event_id=event["event_id"]).count() == 1


def test_duplicate_with_different_content_does_not_overwrite(
    world: World, sender: APIClient
) -> None:
    event = make_event("machine_stopped")
    sender.post(EVENTS_URL, event, format="json")

    changed = {**event, "event_type": "machine_started", "machine_external_id": "NOPE"}
    response = sender.post(EVENTS_URL, changed, format="json")

    assert response.json()["status"] == "duplicate"
    assert MachineStateEvent.objects.get(event_id=event["event_id"]).state == "stopped"


def test_event_id_is_normalized_before_duplicate_check(world: World, sender: APIClient) -> None:
    event = make_event()
    sender.post(EVENTS_URL, event, format="json")

    upper = {**event, "event_id": event["event_id"].upper()}

    assert sender.post(EVENTS_URL, upper, format="json").json()["status"] == "duplicate"


# --- Line restriction ------------------------------------------------------------------


def test_key_cannot_send_events_for_machine_on_another_line(
    world: World, sender: APIClient
) -> None:
    create_machine(world.line_b, "M77", 2)  # exists, but on line B
    event = make_event(machine="M77")

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "rejected"
    assert "machine_external_id" in body["errors"]
    assert not IngestedEvent.objects.exists()


def test_unknown_machine_and_other_line_machine_get_same_message(
    world: World, sender: APIClient
) -> None:
    create_machine(world.line_b, "M77", 2)

    other_line = sender.post(EVENTS_URL, make_event(machine="M77"), format="json").json()
    missing = sender.post(EVENTS_URL, make_event(machine="M78"), format="json").json()

    assert other_line["errors"]["machine_external_id"] == [
        "No machine 'M77' on this API key's line."
    ]
    assert missing["errors"]["machine_external_id"] == ["No machine 'M78' on this API key's line."]


# --- Validation ------------------------------------------------------------------------


def future(seconds: int) -> str:
    return (timezone.now() + timedelta(seconds=seconds)).isoformat()


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"event_type": "machine_exploded"}, "event_type"),
        ({"timestamp": "2026-10-12T10:05:00"}, "timestamp"),  # naive
        ({"timestamp": "yesterday"}, "timestamp"),
        ({"timestamp": 1760263500}, "timestamp"),  # number, not ISO string
        ({"event_type": "production_count_updated", "count": -1}, "count"),
        ({"event_type": "production_count_updated", "count": 1.5}, "count"),
        ({"event_type": "production_count_updated", "count": "10"}, "count"),
        ({"event_type": "production_count_updated", "count": True}, "count"),
        ({"event_type": "production_count_updated"}, "count"),  # missing count
        ({"count": 10, "rejected": -3}, "rejected"),
        ({"machine_external_id": "M99"}, "machine_external_id"),
        ({"payload": ["not", "an", "object"]}, "payload"),
        ({"alarm_code": "E" * 51}, "alarm_code"),
        ({"event_id": "not-a-uuid"}, "event_id"),
        ({"event_id": 12345}, "event_id"),
    ],
)
def test_invalid_event_is_rejected_with_reason(
    world: World, sender: APIClient, overrides: dict[str, object], field: str
) -> None:
    event = {**make_event(), **overrides}

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "rejected"
    assert field in body["errors"], body
    assert all(isinstance(msg, str) and msg for msg in body["errors"][field])
    assert not IngestedEvent.objects.exists()


def test_timestamp_more_than_five_minutes_ahead_is_rejected(
    world: World, sender: APIClient
) -> None:
    response = sender.post(EVENTS_URL, make_event(timestamp=future(301)), format="json")

    assert response.status_code == 400
    assert "future" in response.json()["errors"]["timestamp"][0]


def test_timestamp_slightly_ahead_is_accepted(world: World, sender: APIClient) -> None:
    response = sender.post(EVENTS_URL, make_event(timestamp=future(240)), format="json")

    assert response.status_code == 201


@pytest.mark.parametrize("missing", ["event_id", "machine_external_id", "event_type", "timestamp"])
def test_missing_required_field_is_rejected(world: World, sender: APIClient, missing: str) -> None:
    event = make_event()
    del event[missing]

    response = sender.post(EVENTS_URL, event, format="json")

    assert response.status_code == 400
    assert missing in response.json()["errors"]


def test_body_must_be_an_object(world: World, sender: APIClient) -> None:
    response = sender.post(EVENTS_URL, [make_event()], format="json")

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"


def test_non_json_body_is_refused(world: World, sender: APIClient) -> None:
    response = sender.post(EVENTS_URL, "event_id=1", content_type="text/plain")

    assert response.status_code == 415


# --- Batch -----------------------------------------------------------------------------


def test_valid_batch_stores_every_event(world: World, sender: APIClient) -> None:
    events = [
        make_event("machine_started"),
        make_event("production_count_updated", count=10, rejected=0),
        make_event("machine_stopped", alarm_code="E-204"),
    ]

    response = sender.post(BATCH_URL, events, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"created": 3, "duplicate": 0, "rejected": 0}
    assert [r["status"] for r in body["results"]] == ["created"] * 3
    assert [r["index"] for r in body["results"]] == [0, 1, 2]
    assert IngestedEvent.objects.count() == 3
    assert MachineStateEvent.objects.count() == 2
    assert ProductionEvent.objects.count() == 1


def test_mixed_batch_returns_per_event_results(world: World, sender: APIClient) -> None:
    create_machine(world.line_b, "M77", 2)
    already_stored = make_event("machine_started")
    sender.post(EVENTS_URL, already_stored, format="json")
    repeated_in_batch = make_event("machine_blocked")

    events = [
        make_event("machine_stopped"),  # 0 created
        already_stored,  # 1 duplicate (stored before)
        make_event("machine_exploded"),  # 2 rejected: unknown type
        repeated_in_batch,  # 3 created
        repeated_in_batch,  # 4 duplicate (earlier in the same batch)
        make_event(machine="M77"),  # 5 rejected: other line's machine
        "not an object",  # 6 rejected
        make_event("production_count_updated", count=-5),  # 7 rejected: negative count
    ]

    response = sender.post(BATCH_URL, events, format="json")

    assert response.status_code == 200
    body = response.json()
    assert [r["status"] for r in body["results"]] == [
        "created",
        "duplicate",
        "rejected",
        "created",
        "duplicate",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert body["summary"] == {"created": 2, "duplicate": 2, "rejected": 4}
    assert "event_type" in body["results"][2]["errors"]
    assert "machine_external_id" in body["results"][5]["errors"]
    assert "count" in body["results"][7]["errors"]
    assert body["results"][6]["event_id"] is None
    assert "errors" not in body["results"][0]
    assert IngestedEvent.objects.count() == 3  # 1 before + 2 created


@pytest.mark.parametrize("body", [[], {"events": []}, "text"])
def test_batch_body_must_be_a_non_empty_list(world: World, sender: APIClient, body: object) -> None:
    response = sender.post(BATCH_URL, body, format="json")

    assert response.status_code == 400


def test_batch_larger_than_500_is_refused(world: World, sender: APIClient) -> None:
    events = [make_event() for _ in range(501)]

    response = sender.post(BATCH_URL, events, format="json")

    assert response.status_code == 400
    assert not IngestedEvent.objects.exists()


def test_batch_of_exactly_500_is_accepted(world: World, sender: APIClient) -> None:
    base = timezone.now() - timedelta(hours=1)
    events = [
        make_event("production_count_updated", count=i, at=base + timedelta(seconds=i))
        for i in range(500)
    ]

    response = sender.post(BATCH_URL, events, format="json")

    assert response.json()["summary"]["created"] == 500


def test_batch_requires_api_key(world: World) -> None:
    assert APIClient().post(BATCH_URL, [make_event()], format="json").status_code == 401


def test_event_ids_are_unique_across_lines(
    world: World, key_client: Callable[[str | None], APIClient], line_a_key: str
) -> None:
    """The same event_id from another line's key is a duplicate, never stored twice."""
    _, line_b_key = create_line_api_key(world.line_b, "Line B sender")
    event_id = str(uuid.uuid4())

    key_client(line_a_key).post(EVENTS_URL, make_event(event_id=event_id), format="json")
    response = key_client(line_b_key).post(EVENTS_URL, make_event(event_id=event_id), format="json")

    assert response.json()["status"] == "duplicate"
    assert IngestedEvent.objects.get(event_id=event_id).machine == world.machine_a
