"""Estimated production losses. Never measured, so always labelled as estimates (rule 6)."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from apps.downtime.services.durations import duration_seconds


def estimated_loss(
    started_at: datetime,
    ended_at: datetime | None,
    speed_per_hour: int,
    now: datetime,
    basis: str,
) -> dict[str, Any]:
    """units = duration x nominal speed, rounded to whole units."""
    seconds = Decimal(str(duration_seconds(started_at, ended_at, now)))
    units = (seconds * speed_per_hour / 3600).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return {"units": int(units), "is_estimate": True, "basis": basis}


def machine_loss(
    started_at: datetime, ended_at: datetime | None, speed_per_hour: int, now: datetime
) -> dict[str, Any]:
    return estimated_loss(
        started_at,
        ended_at,
        speed_per_hour,
        now,
        f"duration x machine nominal speed ({speed_per_hour}/h)",
    )


def incident_loss(
    started_at: datetime, ended_at: datetime | None, line_speed_per_hour: int, now: datetime
) -> dict[str, Any]:
    return estimated_loss(
        started_at,
        ended_at,
        line_speed_per_hour,
        now,
        f"duration x line nominal speed, slowest machine ({line_speed_per_hour}/h)",
    )
