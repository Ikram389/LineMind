"""Where events go. The simulation only talks to the small `EventSink` interface.

- FileSink: writes JSON Lines (no backend needed).
- HttpSink: queues events in a file, then sends them in batches to
  POST /api/v1/events/batch/ with retries and exponential backoff.

A future real-machine connector can produce the same `Event` objects and use
the same sinks.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Protocol

import httpx

from event_queue import EventQueue
from events import Event

logger = logging.getLogger(__name__)

BATCH_PATH = "/api/v1/events/batch/"
MAX_BATCH_SIZE = 500  # backend limit (EVENT_BATCH_MAX_SIZE)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class SendSummary:
    submitted: int = 0
    created: int = 0
    duplicate: int = 0
    rejected: int = 0
    rejection_reasons: Counter[str] = field(default_factory=Counter)
    written: int = 0  # FileSink only
    unsent: int = 0  # still in the queue at the end


class SendError(RuntimeError):
    """Sending cannot continue (e.g. invalid API key). Unsent events stay queued."""


class EventSink(Protocol):
    def submit(self, events: Sequence[Event]) -> None:
        """Accept new events (must not lose them)."""
        ...

    def poll(self) -> None:
        """Try to deliver pending events if it's a good moment; never blocks for long."""
        ...

    def close(self, drain_timeout: float) -> SendSummary:
        """Deliver what's left (waiting at most `drain_timeout` seconds) and report."""
        ...


class FileSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: IO[str] = self.path.open("w", encoding="utf-8")
        self.summary = SendSummary()

    def submit(self, events: Sequence[Event]) -> None:
        for event in events:
            self._file.write(json.dumps(event.to_json()) + "\n")
        self.summary.submitted += len(events)
        self.summary.written += len(events)

    def poll(self) -> None:
        self._file.flush()

    def close(self, drain_timeout: float = 0) -> SendSummary:
        self._file.close()
        return self.summary


class HttpSink:
    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        queue: EventQueue,
        *,
        batch_size: int = MAX_BATCH_SIZE,
        flush_interval: float = 1.0,
        min_backoff: float = 1.0,
        max_backoff: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.queue = queue
        self.batch_size = min(batch_size, MAX_BATCH_SIZE)
        self.flush_interval = flush_interval
        self._last_flush = clock()
        self.min_backoff = min_backoff
        self.max_backoff = max_backoff
        self.clock = clock
        self.sleep = sleep
        self.summary = SendSummary()
        self._headers = {"Authorization": f"Api-Key {api_key}"}
        self._failures = 0
        self._next_attempt = 0.0
        pending = len(queue)
        if pending:
            logger.info(
                "Found %d unsent event(s) from a previous run; sending them first.", pending
            )

    def submit(self, events: Sequence[Event]) -> None:
        self.queue.put(events)  # saved to disk before any send attempt
        self.summary.submitted += len(events)

    def poll(self) -> None:
        """Send when a full batch is waiting or `flush_interval` seconds have passed."""
        now = self.clock()
        if now < self._next_attempt:
            return
        pending = len(self.queue)
        if not pending:
            return
        if pending < self.batch_size and now - self._last_flush < self.flush_interval:
            return
        self._last_flush = now
        while len(self.queue) and self._send_one_batch():
            pass

    def close(self, drain_timeout: float = 300.0) -> SendSummary:
        deadline = self.clock() + drain_timeout
        while len(self.queue):
            now = self.clock()
            if now >= deadline:
                break
            if now < self._next_attempt:
                self.sleep(min(self._next_attempt, deadline) - now)
                continue
            self._send_one_batch()
        self.summary.unsent = len(self.queue)
        if self.summary.unsent:
            logger.warning(
                "%d event(s) could not be sent; they are kept in %s and will be sent next run.",
                self.summary.unsent,
                self.queue.path,
            )
        return self.summary

    # --- internals ---------------------------------------------------------------------

    def _send_one_batch(self) -> bool:
        """Send the oldest batch. Returns True if the backend answered for it."""
        rows = self.queue.peek(self.batch_size)
        if not rows:
            return False
        try:
            response = self.client.post(
                BATCH_PATH, json=[body for _, body in rows], headers=self._headers
            )
        except httpx.TransportError as exc:
            self._schedule_retry(f"backend unreachable ({type(exc).__name__})")
            return False

        if response.status_code in (401, 403):
            raise SendError(
                f"The backend refused the API key (HTTP {response.status_code}). "
                "Check SIMULATOR_API_KEY. Unsent events are kept in the queue."
            )
        if response.status_code in RETRYABLE_STATUS:
            self._schedule_retry(f"HTTP {response.status_code}")
            return False
        if response.status_code != 200:
            raise SendError(
                f"Unexpected answer from the backend: HTTP {response.status_code} "
                f"{response.text[:300]}"
            )

        self._record_results(rows, response.json())
        self.queue.ack([seq for seq, _ in rows])
        self._failures = 0
        self._next_attempt = 0.0
        return True

    def _record_results(
        self, rows: list[tuple[int, dict[str, object]]], body: dict[str, object]
    ) -> None:
        results = body.get("results")
        if not isinstance(results, list) or len(results) != len(rows):
            raise SendError("The backend's batch answer does not match the batch sent.")
        for (_, event), result in zip(rows, results, strict=True):
            status = result.get("status")
            if status == "created":
                self.summary.created += 1
            elif status == "duplicate":
                self.summary.duplicate += 1
            else:
                self.summary.rejected += 1
                errors = result.get("errors") or {}
                for field_name, messages in errors.items():
                    for message in messages:
                        self.summary.rejection_reasons[f"{field_name}: {message}"] += 1
                logger.warning(
                    "Rejected %s %s at %s: %s",
                    event.get("machine_external_id"),
                    event.get("event_type"),
                    event.get("timestamp"),
                    errors,
                )

    def _schedule_retry(self, reason: str) -> None:
        self._failures += 1
        delay = min(self.min_backoff * 2 ** (self._failures - 1), self.max_backoff)
        self._next_attempt = self.clock() + delay
        logger.warning(
            "Send failed: %s. %d event(s) queued; retrying in %.0f s.",
            reason,
            len(self.queue),
            delay,
        )

    @property
    def current_backoff(self) -> float:
        """Seconds until the next attempt (0 if one may happen now)."""
        return max(0.0, self._next_attempt - self.clock())
