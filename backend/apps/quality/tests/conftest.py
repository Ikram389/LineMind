from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from apps.quality.defaults import ensure_default_defect_types, ensure_demo_stations
from apps.quality.models import DefectType
from tests.helpers import World
from tests.lines import Bottling


@pytest.fixture
def catalogue(world: World, bottling: Bottling) -> dict[str, DefectType]:
    """Q01-Q06 for both organizations, and the demo stations on the bottling line
    (M01, M03, M04, M05, M06; M02 has none)."""
    ensure_default_defect_types(world.other_org)
    types = ensure_default_defect_types(world.demo_org)
    ensure_demo_stations(bottling.line, types)
    return types


@pytest.fixture
def defect(send: Callable[..., str]) -> Callable[..., str]:
    """defect(machine, code, at, confidence=0.9): ingest one quality_defect_detected event."""

    def _defect(machine: str, code: Any, at: datetime, confidence: Any = 0.9) -> str:
        payload: dict[str, Any] = {"defect_code": code}
        if confidence is not None:
            payload["confidence"] = confidence
        return send(machine, "quality_defect_detected", at, payload=payload)

    return _defect
