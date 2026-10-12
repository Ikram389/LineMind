"""Helpers for building incoming events in tests."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone


def make_event(
    event_type: str = "machine_started",
    machine: str = "M01",
    at: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "machine_external_id": machine,
        "event_type": event_type,
        "timestamp": (at or timezone.now() - timedelta(seconds=1)).isoformat(),
    }
    event.update(extra)
    return event
