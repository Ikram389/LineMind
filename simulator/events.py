"""Events as sent to the LineMind event API (docs/PRODUCT.md §13).

- event_id is derived from (scenario, seed, start time, sequence number), so a
  run can be reproduced exactly and re-sending it is recognised as duplicates.
- Timestamps are UTC and strictly increasing per machine: if two events of the
  same machine fall on the same instant, the later one is moved 1 ms forward.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from machines import MachineState

# Fixed namespace so event ids are stable across machines and Python versions.
EVENT_ID_NAMESPACE = uuid.UUID("6f0e0b9a-2c1f-4c55-9a43-2f1d6c8b7e10")
TIE_BREAK = timedelta(milliseconds=1)

# State -> event type sent when a machine enters that state.
STATE_EVENT_TYPES: dict[MachineState, str] = {
    MachineState.RUNNING: "machine_started",
    MachineState.STOPPED: "machine_stopped",
    MachineState.BLOCKED: "machine_blocked",
    MachineState.STARVED: "machine_starved",
    MachineState.PLANNED_STOP: "planned_stop_started",
}
PLANNED_STOP_ENDED = "planned_stop_ended"


@dataclass(frozen=True)
class Event:
    event_id: str
    machine_external_id: str
    event_type: str
    timestamp: datetime
    alarm_code: str | None = None
    count: int | None = None
    rejected: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """The JSON object expected by POST /api/v1/events/."""
        data: dict[str, Any] = {
            "event_id": self.event_id,
            "machine_external_id": self.machine_external_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }
        if self.alarm_code is not None:
            data["alarm_code"] = self.alarm_code
        if self.count is not None:
            data["count"] = self.count
        if self.rejected is not None:
            data["rejected"] = self.rejected
        if self.payload:
            data["payload"] = self.payload
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Event:
        return cls(
            event_id=data["event_id"],
            machine_external_id=data["machine_external_id"],
            event_type=data["event_type"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            alarm_code=data.get("alarm_code"),
            count=data.get("count"),
            rejected=data.get("rejected"),
            payload=data.get("payload") or {},
        )


class EventFactory:
    """Creates events with reproducible ids and strictly increasing per-machine timestamps."""

    def __init__(self, run_key: str) -> None:
        self._namespace = uuid.uuid5(EVENT_ID_NAMESPACE, run_key)
        self._sequence = 0
        self._last_timestamp: dict[str, datetime] = {}

    def create(self, machine: str, event_type: str, at: datetime, **fields: Any) -> Event:
        timestamp = at.astimezone(UTC)
        previous = self._last_timestamp.get(machine)
        if previous is not None and timestamp <= previous:
            timestamp = previous + TIE_BREAK
        self._last_timestamp[machine] = timestamp
        self._sequence += 1
        event_id = str(uuid.uuid5(self._namespace, str(self._sequence)))
        return Event(event_id, machine, event_type, timestamp, **fields)
