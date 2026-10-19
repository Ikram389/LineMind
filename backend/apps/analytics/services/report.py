"""The OEE report for a line and range: shared by the API endpoint and the AI assistant,
so both always give the same numbers. Calculation stays in oee.py; this only assembles."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apps.analytics.services.buckets import Bucket, day_buckets, hour_buckets, shift_buckets
from apps.analytics.services.oee import calculate, compute_inputs, result_to_dict, sum_inputs
from apps.analytics.services.oee_data import load_line_data
from apps.organizations.models import ProductionLine
from apps.organizations.oee_settings import with_defaults

MAX_BUCKETS = 1000


class TooManyBucketsError(ValueError):
    pass


def make_buckets(
    group_by: str, start: datetime, end: datetime, periods: Any, tz: ZoneInfo
) -> list[Bucket]:
    if end <= start:
        return []
    if group_by == "hour":
        return hour_buckets(start, end, tz)
    if group_by == "day":
        return day_buckets(start, end, tz)
    return shift_buckets(start, end, periods)


def oee_report(
    line: ProductionLine, start: datetime, end: datetime, group_by: str | None, now: datetime
) -> dict[str, Any]:
    """Raises NoCountingMachineError (no counting machine) and TooManyBucketsError.

    With group_by, the total is calculated from the summed inputs of the buckets, never by
    averaging bucket percentages.
    """
    data, periods = load_line_data(line, start, end, now)
    body: dict[str, Any] = {
        "line": {"id": line.id, "name": line.name},
        "counting_machine": line.output_machine().external_id,
        "factory_timezone": line.factory.timezone,
        "range": {"start": start, "end": end},
        "settings": with_defaults(line.factory.oee_settings),
    }
    if group_by is None:
        body["total"] = result_to_dict(calculate(compute_inputs(data, start, end)))
        return body

    buckets = make_buckets(group_by, start, min(end, now), periods, ZoneInfo(line.factory.timezone))
    if len(buckets) > MAX_BUCKETS:
        raise TooManyBucketsError(f"Too many buckets (max {MAX_BUCKETS}).")
    bucket_inputs = [compute_inputs(data, b.start, b.end) for b in buckets]
    total_inputs = sum_inputs(bucket_inputs)
    if end > now:
        total_inputs.range_in_future = True
        total_inputs.computed_until = now
    body["group_by"] = group_by
    body["total"] = result_to_dict(calculate(total_inputs))
    body["buckets"] = [
        {"label": b.label, "start": b.start, "end": b.end, **result_to_dict(calculate(i))}
        for b, i in zip(buckets, bucket_inputs, strict=True)
    ]
    return body
