"""Live messages: sent after commit, only for current changes, throttled counts, incidents."""

import asyncio
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.live import broadcast
from apps.live.broadcast import line_group
from apps.production.services.ingestion import ingest_batch
from tests.lines import Bottling


async def _drain(layer: Any, channel: str) -> list[dict[str, Any]]:
    messages = []
    while True:
        try:
            event = await asyncio.wait_for(layer.receive(channel), timeout=0.05)
        except TimeoutError:
            return messages
        messages.append(event["message"])


@pytest.fixture
def listen(bottling: Bottling) -> Iterator[Callable[[], list[dict[str, Any]]]]:
    """listen() returns the live messages sent to the bottling line so far."""
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(line_group(bottling.line.id), channel)
    yield lambda: async_to_sync(_drain)(layer, channel)
    async_to_sync(layer.flush)()


def types(messages: list[dict[str, Any]]) -> list[str]:
    return [m["type"] for m in messages]


def test_state_change_is_sent_after_commit(
    send: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        send("M05", "machine_stopped", timezone.now() - timedelta(seconds=5), alarm_code="E-204")
        assert listen() == []  # nothing before the commit

    for callback in callbacks:
        callback()
    messages = listen()
    assert "machine_state_changed" in types(messages)
    state = next(m for m in messages if m["type"] == "machine_state_changed")
    assert (state["data"]["external_id"], state["data"]["state"]) == ("M05", "stopped")


def test_rolled_back_change_sends_nothing(
    bottling: Bottling,
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                broadcast.queue_incident_message("incident_opened", bottling.line.id, {"x": 1})
                raise RuntimeError("roll back")
        except RuntimeError:
            pass

    assert listen() == []


def test_late_event_does_not_announce_a_state_change(
    send: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    now = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        send("M05", "machine_stopped", now - timedelta(seconds=5))
    listen()

    with django_capture_on_commit_callbacks(execute=True):
        send("M05", "machine_blocked", now - timedelta(seconds=20))  # older than the current state

    assert "machine_state_changed" not in types(listen())


def test_counts_are_throttled_per_machine(
    bottling: Bottling,
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(broadcast, "COUNT_THROTTLE_SECONDS", 1)
    now = timezone.now()

    def counts(offsets: list[int], start: int) -> list[dict[str, Any]]:
        return [
            {
                "event_id": f"00000000-0000-4000-8000-{start + i:012d}",
                "machine_external_id": "M06",
                "event_type": "production_count_updated",
                "timestamp": (now - timedelta(seconds=30 - offset)).isoformat(),
                "count": 100 * (offset + 1),
                "rejected": 0,
            }
            for i, offset in enumerate(offsets)
        ]

    with django_capture_on_commit_callbacks(execute=True):
        ingest_batch(bottling.api_key, counts([0, 1, 2, 3, 4], start=1))
    first = [m for m in listen() if m["type"] == "count_updated"]
    assert len(first) == 1  # one message for the whole batch: the newest count
    assert first[0]["data"]["count"] == 500

    with django_capture_on_commit_callbacks(execute=True):
        ingest_batch(bottling.api_key, counts([5], start=10))
    assert [m for m in listen() if m["type"] == "count_updated"] == []  # within the throttle

    time.sleep(1.1)
    with django_capture_on_commit_callbacks(execute=True):
        ingest_batch(bottling.api_key, counts([6], start=20))
    again = [m for m in listen() if m["type"] == "count_updated"]
    assert [m["data"]["count"] for m in again] == [700]


def test_incident_opened_updated_and_closed(
    send: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    base = timezone.now() - timedelta(seconds=50)

    def step(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        with django_capture_on_commit_callbacks(execute=True):
            send(*args, **kwargs)
        return [m for m in listen() if m["type"].startswith("incident_")]

    opened = step("M05", "machine_stopped", base, alarm_code="E-204")
    updated = step("M04", "machine_blocked", base + timedelta(seconds=3))
    still_open = step("M05", "machine_started", base + timedelta(seconds=30))
    closed = step("M04", "machine_started", base + timedelta(seconds=31))

    assert types(opened) == ["incident_opened"]
    first = opened[0]["data"]["first_observed_stop"]
    assert [m["external_id"] for m in first["machines"]] == ["M05"]
    assert first["alarm_code"] == "E-204"
    assert types(updated) == ["incident_updated"]
    assert [m["external_id"] for m in updated[0]["data"]["affected_machines"]] == ["M05", "M04"]
    assert types(still_open) == []  # M04 still blocked: same incident, same members
    assert types(closed) == ["incident_closed"]
    assert closed[0]["data"]["incident_id"] == opened[0]["data"]["incident_id"]
    assert closed[0]["data"]["duration_seconds"] == pytest.approx(31, abs=0.01)


def test_backfilled_incident_that_already_ended_sends_no_incident_message(
    load: Callable[..., None],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        load("labeler_jam", batch_size=1000)

    assert [m for m in listen() if m["type"].startswith("incident_")] == []
