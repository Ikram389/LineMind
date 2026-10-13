"""Split a range into buckets: local clock hours, local days, or shift occurrences.

Buckets never overlap, so their inputs can be summed into the range total.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apps.production.services.shifts import ShiftPeriod

GROUP_BY = ("hour", "day", "shift")


@dataclass(frozen=True)
class Bucket:
    start: datetime
    end: datetime
    label: str


def hour_buckets(start: datetime, end: datetime, tz: ZoneInfo) -> list[Bucket]:
    local = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    cursor = local.astimezone(UTC)
    buckets = []
    while cursor < end:
        nxt = cursor + timedelta(hours=1)
        label = cursor.astimezone(tz).strftime("%Y-%m-%d %H:00")
        buckets.append(Bucket(max(cursor, start), min(nxt, end), label))
        cursor = nxt
    return buckets


def day_buckets(start: datetime, end: datetime, tz: ZoneInfo) -> list[Bucket]:
    day = start.astimezone(tz).date()
    buckets = []
    while True:
        day_start = datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz).astimezone(UTC)
        if day_start >= end:
            break
        buckets.append(Bucket(max(day_start, start), min(day_end, end), day.isoformat()))
        day += timedelta(days=1)
    return buckets


def shift_buckets(start: datetime, end: datetime, periods: Sequence[ShiftPeriod]) -> list[Bucket]:
    """One bucket per shift occurrence; overlapping occurrences never share time."""
    buckets = []
    covered_until = start
    for period in sorted(periods, key=lambda p: (p.start, p.shift_id)):
        bucket_start = max(period.start, start, covered_until)
        bucket_end = min(period.end, end)
        if bucket_end > bucket_start:
            buckets.append(Bucket(bucket_start, bucket_end, period.label))
            covered_until = bucket_end
    return buckets
