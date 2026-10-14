"""Event ingestion: the only code that turns incoming events into stored observations.

For each event:
1. Check it's a JSON object with a valid UUID `event_id`.
2. If that event_id is already stored -> "duplicate" (nothing else is checked or
   changed; the first version always wins, so sender retries are safe).
3. Validate everything else (type, timestamp, machine on the key's line, counts).
4. Store IngestedEvent, plus MachineStateEvent or ProductionEvent depending on
   the type (see event_types.py), in one savepoint.
After a request's events are stored, downtime is re-derived for the affected
machines and time window (apps/downtime/services/derivation.py), and live
messages are queued for after the commit (apps/live/broadcast.py), once per request.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from apps.downtime.services.derivation import rebuild_after_ingestion
from apps.live.broadcast import StoredEvent, queue_after_ingestion
from apps.production.event_types import EVENT_TYPE_TO_STATE, PRODUCTION_EVENT_TYPES, EventType
from apps.production.models import (
    IngestedEvent,
    LineApiKey,
    MachineStateEvent,
    ProductionEvent,
)
from apps.production.serializers import IncomingEventSerializer
from apps.quality.services.live import queue_quality_updates
from apps.quality.services.processing import process_after_ingestion

logger = logging.getLogger(__name__)

Status = Literal["created", "duplicate", "rejected"]


@dataclass(frozen=True)
class IngestResult:
    status: Status
    event_id: str | None
    errors: dict[str, list[str]] = field(default_factory=dict)
    # A newly stored event; used to re-derive downtime and to send live messages.
    stored: StoredEvent | None = field(default=None, compare=False)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"event_id": self.event_id, "status": self.status}
        if self.errors:
            result["errors"] = self.errors
        return result


def ingest_event(
    api_key: LineApiKey, data: object, received_at: datetime | None = None
) -> IngestResult:
    """Validate and store one event sent with `api_key`, then update downtime."""
    result = _ingest_one(api_key, data, received_at or timezone.now())
    _after_store([result.stored] if result.stored else [])
    return result


def ingest_batch(api_key: LineApiKey, events: Sequence[object]) -> list[IngestResult]:
    """Ingest each event independently; one bad event never affects the others."""
    received_at = timezone.now()
    results = [_ingest_one(api_key, event, received_at) for event in events]
    _after_store([r.stored for r in results if r.stored])
    return results


def _after_store(stored: list[StoredEvent]) -> None:
    # Queued first so that, after commit, machine state messages go out before incident ones.
    queue_after_ingestion(stored)
    rebuild_after_ingestion([(event.machine_id, event.timestamp) for event in stored])
    # After the downtime rebuild, so defect context sees up-to-date incidents.
    defect_ids = [event.event_id for event in stored if event.kind == "defect"]
    if defect_ids:
        queue_quality_updates(process_after_ingestion(defect_ids))


def _ingest_one(api_key: LineApiKey, data: object, received_at: datetime) -> IngestResult:
    if not isinstance(data, dict):
        return _rejected(api_key, None, {"non_field_errors": ["An event must be a JSON object."]})

    raw_event_id = data.get("event_id")
    if not isinstance(raw_event_id, str):
        errors = {"event_id": ["Is required and must be a UUID string."]}
        return _rejected(api_key, None, errors)
    try:
        event_id = serializers.UUIDField().run_validation(raw_event_id)
    except serializers.ValidationError as exc:
        return _rejected(api_key, raw_event_id, {"event_id": _messages(exc.detail)})
    event_id_text = str(event_id)

    if IngestedEvent.objects.filter(event_id=event_id).exists():
        return IngestResult("duplicate", event_id_text)

    serializer = IncomingEventSerializer(
        data=data, context={"line": api_key.line, "now": received_at}
    )
    if not serializer.is_valid():
        errors = {name: _messages(detail) for name, detail in serializer.errors.items()}
        return _rejected(api_key, event_id_text, errors)

    validated = serializer.validated_data
    try:
        with transaction.atomic():
            _store(api_key, validated, received_at)
    except IntegrityError:
        # Another request stored the same event_id at the same moment.
        if IngestedEvent.objects.filter(event_id=event_id).exists():
            return IngestResult("duplicate", event_id_text)
        raise

    machine = validated["machine"]
    event_type = validated["event_type"]
    kind = (
        "state"
        if event_type in EVENT_TYPE_TO_STATE
        else "count"
        if event_type in PRODUCTION_EVENT_TYPES
        else "defect"
        if event_type == EventType.QUALITY_DEFECT_DETECTED
        else "other"
    )
    return IngestResult(
        "created",
        event_id_text,
        stored=StoredEvent(
            machine.pk, machine.line_id, validated["event_id"], validated["timestamp"], kind
        ),
    )


def _store(api_key: LineApiKey, event: dict[str, Any], received_at: datetime) -> None:
    event_type = event["event_type"]
    common = {
        "event_id": event["event_id"],
        "machine": event["machine"],
        "timestamp": event["timestamp"],
        "received_at": received_at,
    }

    IngestedEvent.objects.create(
        **common,
        api_key=api_key,
        event_type=event_type,
        alarm_code=event.get("alarm_code"),
        count=event.get("count"),
        rejected=event.get("rejected"),
        payload=event.get("payload") or {},
    )

    state = EVENT_TYPE_TO_STATE.get(event_type)
    if state is not None:
        MachineStateEvent.objects.create(**common, state=state, alarm_code=event.get("alarm_code"))
    elif event_type in PRODUCTION_EVENT_TYPES:
        ProductionEvent.objects.create(
            **common, count=event["count"], rejected=event.get("rejected")
        )


def _rejected(
    api_key: LineApiKey, event_id: str | None, errors: dict[str, list[str]]
) -> IngestResult:
    logger.warning(
        "Rejected event %s from API key %s (line %s): %s",
        event_id,
        api_key.prefix,
        api_key.line_id,
        errors,
    )
    return IngestResult("rejected", event_id, errors)


def _messages(detail: Any) -> list[str]:
    """Flatten DRF error details into a list of plain strings."""
    if isinstance(detail, dict):
        return [msg for value in detail.values() for msg in _messages(value)]
    if isinstance(detail, list):
        return [msg for item in detail for msg in _messages(item)]
    return [str(detail)]
