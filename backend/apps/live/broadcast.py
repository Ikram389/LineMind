"""Live messages to the browsers watching a line (group "line_<id>").

Every message is sent *after* the database transaction commits
(transaction.on_commit), so a browser never sees something that was rolled
back, and a re-fetch from the REST API always agrees with the message.

Envelope: {"type": ..., "line_id": ..., "sent_at": ..., "data": {...}}
Types:
- machine_state_changed  only when an event changed the machine's *current* state
                         (late or backfilled events don't)
- count_updated          newest count per machine per request, at most one per
                         machine every COUNT_THROTTLE_SECONDS (extra ones are dropped)
- incident_opened / incident_updated / incident_closed   only for ongoing incidents
"""

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import Machine
from apps.production.models import MachineStateEvent, ProductionEvent
from apps.production.services.line_status import machine_status
from apps.production.services.shifts import current_shift

logger = logging.getLogger(__name__)

COUNT_THROTTLE_SECONDS = 5


def line_group(line_id: int) -> str:
    return f"line_{line_id}"


def user_group(user_id: int) -> str:
    """One group per user (/ws/me/): their notifications, wherever they are in the app."""
    return f"user_{user_id}"


@dataclass(frozen=True)
class StoredEvent:
    """What the ingestion service tells us about each newly stored event."""

    machine_id: int
    line_id: int
    event_id: UUID
    timestamp: datetime
    kind: str  # "state", "count", "defect" or "other"


def message(message_type: str, line_id: int, data: dict[str, Any]) -> dict[str, Any]:
    envelope = {"type": message_type, "line_id": line_id, "sent_at": timezone.now(), "data": data}
    # Plain JSON values only (ISO date strings), so any channel layer can carry it.
    return json.loads(json.dumps(envelope, cls=DjangoJSONEncoder))


def send_now(line_id: int, payload: dict[str, Any], group: str | None = None) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group or line_group(line_id), {"type": "live.message", "message": payload}
        )
    except Exception:  # live updates must never break ingestion
        logger.exception("Could not send live message %s", payload.get("type"))


def after_commit(callback: Callable[[], None]) -> None:
    transaction.on_commit(callback)


# --- From the ingestion service --------------------------------------------------------


def queue_after_ingestion(stored: Iterable[StoredEvent]) -> None:
    stored = list(stored)
    if stored:
        after_commit(lambda: publish_ingestion(stored))


def publish_ingestion(stored: list[StoredEvent]) -> None:
    now = timezone.now()
    by_machine: dict[int, list[StoredEvent]] = {}
    for event in stored:
        by_machine.setdefault(event.machine_id, []).append(event)

    machines = Machine.objects.select_related("line__factory").filter(pk__in=by_machine)
    shift_starts: dict[int, datetime | None] = {}
    for machine in machines:
        events = by_machine[machine.pk]
        factory = machine.line.factory
        if factory.pk not in shift_starts:
            shift = current_shift(factory, now)
            shift_starts[factory.pk] = shift.start if shift else None

        state_ids = {e.event_id for e in events if e.kind == "state"}
        changed_state = bool(state_ids) and (
            MachineStateEvent.objects.filter(machine=machine)
            .order_by("-timestamp", "-event_id")
            .values_list("event_id", flat=True)
            .first()
            in state_ids
        )
        count_ids = {e.event_id for e in events if e.kind == "count"}
        new_count = bool(count_ids) and (
            ProductionEvent.objects.filter(machine=machine)
            .order_by("-timestamp", "-event_id")
            .values_list("event_id", flat=True)
            .first()
            in count_ids
        )
        if not changed_state and not new_count:
            continue

        status = machine_status(machine, now, shift_starts[factory.pk])
        if changed_state:
            send_now(
                machine.line_id,
                message(
                    "machine_state_changed",
                    machine.line_id,
                    {
                        "machine_id": machine.pk,
                        "external_id": machine.external_id,
                        **{
                            k: status[k]
                            for k in (
                                "state",
                                "reported_state",
                                "state_since",
                                "alarm_code",
                                "last_alarm_code",
                                "last_alarm_at",
                                "is_stale",
                                "last_seen",
                            )
                        },
                    },
                ),
            )
        if new_count and cache.add(f"live:count:{machine.pk}", 1, timeout=COUNT_THROTTLE_SECONDS):
            last = status["last_count"] or {}
            send_now(
                machine.line_id,
                message(
                    "count_updated",
                    machine.line_id,
                    {
                        "machine_id": machine.pk,
                        "external_id": machine.external_id,
                        "count": last.get("count"),
                        "rejected": last.get("rejected"),
                        "timestamp": last.get("timestamp"),
                        "shift_count": status["shift_count"],
                        "shift_rejected": status["shift_rejected"],
                        "last_seen": status["last_seen"],
                    },
                ),
            )


# --- From the downtime services --------------------------------------------------------


def queue_incident_message(message_type: str, line_id: int, data: dict[str, Any]) -> None:
    """Build the message now (inside the transaction), send it after commit."""
    payload = message(message_type, line_id, data)
    after_commit(lambda: send_now(line_id, payload))
