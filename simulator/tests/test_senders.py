"""Sending: file queue, batches, retries with the same event_id, backoff, results."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from event_queue import EventQueue
from events import Event
from senders import FileSink, HttpSink, SendError
from simulation import Simulation
from tests.helpers import make_scenario


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def some_events(n_seconds: int = 60) -> list[Event]:
    return Simulation(make_scenario(duration=n_seconds)).run_all()


def backend(
    handler: Callable[[list[dict[str, object]]], httpx.Response],
    requests: list[list[dict[str, object]]],
) -> httpx.Client:
    """An httpx client whose 'backend' is `handler`; every batch sent is recorded."""

    def transport(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)
        requests.append(batch)
        return handler(batch)

    return httpx.Client(base_url="http://backend", transport=httpx.MockTransport(transport))


def all_created(batch: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "summary": {"created": len(batch), "duplicate": 0, "rejected": 0},
            "results": [
                {"index": i, "event_id": e["event_id"], "status": "created"}
                for i, e in enumerate(batch)
            ],
        },
    )


def make_sink(tmp_path: Path, client: httpx.Client, clock: FakeClock, **kwargs: object) -> HttpSink:
    return HttpSink(
        client,
        "lm_test_key",
        EventQueue(tmp_path / "queue.sqlite"),
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )


# --- Queue -----------------------------------------------------------------------------


def test_queue_survives_restart(tmp_path: Path) -> None:
    events = some_events()
    queue = EventQueue(tmp_path / "queue.sqlite")
    queue.put(events)
    queue.close()

    reopened = EventQueue(tmp_path / "queue.sqlite")

    assert len(reopened) == len(events)
    assert [body["event_id"] for _, body in reopened.peek(1000)] == [e.event_id for e in events]
    assert [body for _, body in reopened.peek(3)] == [e.to_json() for e in events[:3]]


def test_queue_ignores_same_event_twice(tmp_path: Path) -> None:
    events = some_events()
    queue = EventQueue(tmp_path / "queue.sqlite")
    queue.put(events)
    queue.put(events)

    assert len(queue) == len(events)


def test_ack_removes_only_answered_events(tmp_path: Path) -> None:
    queue = EventQueue(tmp_path / "queue.sqlite")
    queue.put(some_events())
    first_three = queue.peek(3)

    queue.ack([seq for seq, _ in first_three])

    remaining_ids = {body["event_id"] for _, body in queue.peek(1000)}
    assert remaining_ids.isdisjoint({body["event_id"] for _, body in first_three})


# --- HTTP sending ----------------------------------------------------------------------


def test_events_are_sent_in_batches_of_at_most_500(tmp_path: Path) -> None:
    requests: list[list[dict[str, object]]] = []
    clock = FakeClock()
    sink = make_sink(tmp_path, backend(all_created, requests), clock)
    events = some_events(1200)  # > 1,000 events

    sink.submit(events)
    summary = sink.close(drain_timeout=10)

    assert all(len(batch) <= 500 for batch in requests)
    assert sum(len(batch) for batch in requests) == len(events)
    assert summary.created == len(events)
    assert summary.unsent == 0


def test_retry_after_connection_error_reuses_event_ids_with_growing_backoff(
    tmp_path: Path,
) -> None:
    requests: list[list[dict[str, object]]] = []
    failures = {"left": 3}

    def flaky(batch: list[dict[str, object]]) -> httpx.Response:
        if failures["left"]:
            failures["left"] -= 1
            raise httpx.ConnectError("backend down")
        return all_created(batch)

    clock = FakeClock()
    sink = make_sink(tmp_path, backend(flaky, requests), clock)
    events = some_events(30)

    sink.submit(events)
    summary = sink.close(drain_timeout=60)

    assert len(requests) == 4  # 3 failures + 1 success, all the same batch
    ids_per_attempt = [[e["event_id"] for e in batch] for batch in requests]
    assert all(ids == ids_per_attempt[0] for ids in ids_per_attempt)
    assert ids_per_attempt[0] == [e.event_id for e in events]
    assert clock.sleeps == [1.0, 2.0, 4.0]  # exponential backoff
    assert summary.created == len(events)


def test_backoff_is_capped(tmp_path: Path) -> None:
    def always_down(batch: list[dict[str, object]]) -> httpx.Response:
        raise httpx.ConnectError("down")

    clock = FakeClock()
    sink = make_sink(tmp_path, backend(always_down, []), clock, max_backoff=8.0)
    sink.submit(some_events(10))

    summary = sink.close(drain_timeout=40)

    assert clock.sleeps[:5] == [1.0, 2.0, 4.0, 8.0, 8.0]
    assert summary.unsent > 0


def test_unsent_events_are_sent_by_the_next_run(tmp_path: Path) -> None:
    def always_down(batch: list[dict[str, object]]) -> httpx.Response:
        return httpx.Response(503)

    events = some_events(30)
    clock = FakeClock()
    first_run = make_sink(tmp_path, backend(always_down, []), clock)
    first_run.submit(events)
    assert first_run.close(drain_timeout=5).unsent == len(events)
    first_run.queue.close()

    requests: list[list[dict[str, object]]] = []
    second_run = make_sink(tmp_path, backend(all_created, requests), FakeClock())
    summary = second_run.close(drain_timeout=5)

    assert [e["event_id"] for e in requests[0]] == [e.event_id for e in events]
    assert summary.created == len(events)
    assert len(second_run.queue) == 0


def test_server_errors_are_retried(tmp_path: Path) -> None:
    answers = iter([httpx.Response(500), httpx.Response(429)])

    def handler(batch: list[dict[str, object]]) -> httpx.Response:
        return next(answers, None) or all_created(batch)

    requests: list[list[dict[str, object]]] = []
    sink = make_sink(tmp_path, backend(handler, requests), FakeClock())
    sink.submit(some_events(10))

    assert sink.close(drain_timeout=30).unsent == 0
    assert len(requests) == 3


@pytest.mark.parametrize("status", [401, 403])
def test_refused_key_stops_and_keeps_queue(tmp_path: Path, status: int) -> None:
    sink = make_sink(tmp_path, backend(lambda b: httpx.Response(status), []), FakeClock())
    events = some_events(10)
    sink.submit(events)

    with pytest.raises(SendError, match="API key"):
        sink.close(drain_timeout=5)
    assert len(sink.queue) == len(events)


def test_duplicates_and_rejections_are_counted_with_reasons(tmp_path: Path) -> None:
    def mixed(batch: list[dict[str, object]]) -> httpx.Response:
        results = []
        for i, event in enumerate(batch):
            if i % 3 == 0:
                results.append({"index": i, "event_id": event["event_id"], "status": "created"})
            elif i % 3 == 1:
                results.append({"index": i, "event_id": event["event_id"], "status": "duplicate"})
            else:
                results.append(
                    {
                        "index": i,
                        "event_id": event["event_id"],
                        "status": "rejected",
                        "errors": {"machine_external_id": ["No machine 'M01' on this line."]},
                    }
                )
        return httpx.Response(200, json={"summary": {}, "results": results})

    sink = make_sink(tmp_path, backend(mixed, []), FakeClock())
    sink.submit(some_events(10)[:9])
    summary = sink.close(drain_timeout=5)

    assert (summary.created, summary.duplicate, summary.rejected) == (3, 3, 3)
    assert summary.rejection_reasons == {"machine_external_id: No machine 'M01' on this line.": 3}
    assert len(sink.queue) == 0  # answered events (even rejected ones) leave the queue


def test_poll_waits_for_full_batch_or_flush_interval(tmp_path: Path) -> None:
    requests: list[list[dict[str, object]]] = []
    clock = FakeClock()
    sink = make_sink(tmp_path, backend(all_created, requests), clock, flush_interval=1.0)

    sink.submit(some_events(10)[:5])
    sink.poll()
    assert requests == []  # too few and too soon

    clock.now += 1.0
    sink.poll()
    assert len(requests) == 1


def test_poll_respects_backoff(tmp_path: Path) -> None:
    requests: list[list[dict[str, object]]] = []

    def down(batch: list[dict[str, object]]) -> httpx.Response:
        return httpx.Response(503)

    clock = FakeClock()
    sink = make_sink(tmp_path, backend(down, requests), clock, flush_interval=0)
    sink.submit(some_events(10))

    sink.poll()
    sink.poll()  # still within the 1 s backoff: no new attempt
    assert len(requests) == 1
    clock.now += 1.0
    sink.poll()
    assert len(requests) == 2


# --- File output -----------------------------------------------------------------------


def test_file_sink_writes_json_lines(tmp_path: Path) -> None:
    events = some_events(30)
    sink = FileSink(tmp_path / "out" / "events.jsonl")

    sink.submit(events)
    summary = sink.close()

    lines = (tmp_path / "out" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert summary.written == len(events) == len(lines)
    assert [json.loads(line) for line in lines] == [e.to_json() for e in events]
