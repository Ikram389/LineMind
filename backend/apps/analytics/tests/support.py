"""Build LineData by hand for pure OEE tests (no database)."""

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Any

from apps.analytics.services.oee import DowntimeSpan, LineData, OrderSpan, Reading
from apps.organizations.oee_settings import with_defaults
from apps.production.services.timeset import TimeSet

T0 = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def make_data(
    shifts: list[tuple[float, float]] | None = None,
    breaks: list[tuple[float, float]] | None = None,
    downtime: list[tuple[float, float, str] | tuple[float, float, str, bool]] | None = None,
    readings: list[tuple[float, int, int | None]] | None = None,
    orders: list[tuple[float, float, str, Fraction]] | None = None,
    fallback: Fraction | None = Fraction(3, 5),
    first_seen: float | None = 0,
    last_seen: float | None = None,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> LineData:
    """All times in minutes after T0 (2026-10-05 06:00 UTC)."""
    shifts = shifts if shifts is not None else [(0, 480)]
    readings = readings or []
    if last_seen is None:
        last_seen = max([m for m, _, _ in readings], default=shifts[-1][1] if shifts else 0)
    return LineData(
        shift_time=TimeSet.of((at(s), at(e)) for s, e in shifts),
        breaks=TimeSet.of((at(s), at(e)) for s, e in breaks or []),
        downtime=tuple(
            DowntimeSpan(at(d[0]), at(d[1]), d[2], d[3] if len(d) > 3 else False)
            for d in downtime or []
        ),
        readings=tuple(Reading(at(m), count, rejected) for m, count, rejected in readings),
        orders=tuple(
            OrderSpan(at(s), at(e), sku, f"Product {sku}", cycle)
            for s, e, sku, cycle in orders or []
        ),
        fallback_cycle_time=fallback,
        first_seen=at(first_seen) if first_seen is not None else None,
        last_seen=at(last_seen) if last_seen is not None else None,
        stale_after_seconds=60,
        settings=with_defaults(settings or {}),
        now=now or at(100_000),
    )


def whole_order(
    cycle: Fraction = Fraction(3, 5), sku: str = "W050"
) -> list[tuple[float, float, str, Fraction]]:
    return [(-1000, 100_000, sku, cycle)]
