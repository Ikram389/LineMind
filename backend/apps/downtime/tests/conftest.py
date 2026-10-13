"""Fixtures for downtime tests (shared ones are in backend/conftest.py)."""

import random
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from apps.downtime.default_reasons import ensure_default_reasons
from apps.downtime.tests.support import Bottling, create_bottling_line, read_fixture
from apps.production.services.ingestion import ingest_batch, ingest_event
from tests.helpers import World


@pytest.fixture
def bottling(world: World) -> Bottling:
    """A six-machine bottling line (6,000/h each) in Demo Beverages' *Plant B*.

    world.users["limited_operator"] only has Plant A, so cannot see it.
    """
    ensure_default_reasons(world.factory_b)
    return create_bottling_line(world.factory_b, "Bottling Line")


@pytest.fixture
def load(bottling: Bottling) -> Callable[..., None]:
    """load(name, shuffle_seed=None, batch_size=500): send a fixture through ingest_batch."""

    def _load(name: str, shuffle_seed: int | None = None, batch_size: int = 500) -> None:
        events = read_fixture(name)
        if shuffle_seed is not None:
            random.Random(shuffle_seed).shuffle(events)
        for i in range(0, len(events), batch_size):
            results = ingest_batch(bottling.api_key, events[i : i + batch_size])
            assert {r.status for r in results} == {"created"}, [
                r.errors for r in results if r.status != "created"
            ][:3]

    return _load


@pytest.fixture
def send(bottling: Bottling) -> Callable[..., str]:
    """send(machine, event_type, at, **extra): ingest one hand-made event."""

    def _send(machine: str, event_type: str, at: datetime, **extra: Any) -> str:
        event_id = str(uuid.uuid4())
        result = ingest_event(
            bottling.api_key,
            {
                "event_id": event_id,
                "machine_external_id": machine,
                "event_type": event_type,
                "timestamp": at.isoformat(),
                **extra,
            },
        )
        assert result.status == "created", result.errors
        return event_id

    return _send
