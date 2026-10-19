"""Dates and differences are computed in Python, never by the model."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import pytest

from apps.assistant.providers.base import RawToolCall
from apps.assistant.services.tool_runner import run_tool
from apps.assistant.tools.compare import difference
from apps.assistant.tools.core import ArgumentError, ToolContext, iso, minutes
from apps.assistant.tools.time_ranges import NoSuchPeriod, resolve_range
from apps.downtime.services.analysis import AnalysisFilters, select_entries, summary
from apps.organizations.models import Factory
from apps.production.models import Shift
from tests.lines import Bottling

from .conftest import JAM_END, JAM_START

# Saturday 17 Oct 2026, 13:05 in Algiers (UTC+1, no daylight saving).
NOW = datetime(2026, 10, 17, 12, 5, tzinfo=UTC)


@pytest.fixture
def algiers(bottling: Bottling) -> Factory:
    factory = bottling.line.factory
    factory.timezone = "Africa/Algiers"
    factory.save()
    for name, start, end in (("Morning", 6, 14), ("Afternoon", 14, 22), ("Night", 22, 6)):
        Shift.objects.create(factory=factory, name=name, start_time=time(start), end_time=time(end))
    return factory


def span(r: object) -> tuple[str, str]:
    return iso(r.start), iso(r.end)  # type: ignore[attr-defined]


def test_calendar_phrases_use_the_factory_timezone(algiers: Factory) -> None:
    assert span(resolve_range(algiers, NOW, "today")) == (
        "2026-10-16T23:00:00Z",
        "2026-10-17T12:05:00Z",
    )
    assert span(resolve_range(algiers, NOW, "yesterday")) == (
        "2026-10-15T23:00:00Z",
        "2026-10-16T23:00:00Z",
    )
    # Week starts Monday 12 Oct, local midnight.
    assert span(resolve_range(algiers, NOW, "this_week")) == (
        "2026-10-11T23:00:00Z",
        "2026-10-17T12:05:00Z",
    )
    assert span(resolve_range(algiers, NOW, "last_week")) == (
        "2026-10-04T23:00:00Z",
        "2026-10-11T23:00:00Z",
    )
    assert span(resolve_range(algiers, NOW, "last_month")) == (
        "2026-08-31T23:00:00Z",
        "2026-09-30T23:00:00Z",
    )
    today = resolve_range(algiers, NOW, "today")
    assert today.ongoing and "so far" in today.label and "Africa/Algiers" in today.label


def test_shifts_including_a_night_shift_crossing_midnight(algiers: Factory) -> None:
    current = resolve_range(algiers, NOW, "current_shift")
    assert span(current) == ("2026-10-17T05:00:00Z", "2026-10-17T12:05:00Z")
    assert current.label.startswith("Morning shift (so far)")

    previous = resolve_range(algiers, NOW, "previous_shift")
    # The Night shift that started Friday 16 Oct at 22:00 local and ended Saturday 06:00.
    assert span(previous) == ("2026-10-16T21:00:00Z", "2026-10-17T05:00:00Z")

    night = resolve_range(algiers, NOW, "shift_on_date", date(2026, 10, 12), "night")
    assert span(night) == ("2026-10-12T21:00:00Z", "2026-10-13T05:00:00Z")
    assert not night.ongoing


def test_periods_that_have_not_started_or_do_not_exist(algiers: Factory) -> None:
    with pytest.raises(NoSuchPeriod):
        resolve_range(algiers, NOW, "date", date(2026, 10, 20))
    with pytest.raises(ArgumentError, match="Morning, Afternoon, Night"):
        resolve_range(algiers, NOW, "shift_on_date", date(2026, 10, 12), "Weekend")
    late = NOW.replace(hour=23)  # Saturday 00:05 local next day? no: 23:05 UTC = 00:05 Sunday
    assert resolve_range(algiers, late, "current_shift").label.startswith("Night shift")


def test_the_tool_reports_the_resolved_range(
    bottling: Bottling, algiers: Factory, world: object
) -> None:
    user = world.users["production_supervisor"]  # type: ignore[attr-defined]
    ctx = ToolContext(user, user.membership.organization, NOW)
    args = {
        "phrase": "shift_on_date",
        "line_id": bottling.line.pk,
        "date": "2026-10-12",
        "shift_name": "Night",
    }
    outcome = run_tool(RawToolCall("t", "resolve_time_range", json.dumps(args)), ctx)
    assert outcome.result is not None
    assert outcome.result.resolved_range == {
        **outcome.result.data,
        "line_id": bottling.line.pk,
    }
    assert outcome.result.data["start"] == "2026-10-12T21:00:00Z"

    missing = run_tool(
        RawToolCall("t", "resolve_time_range", json.dumps({**args, "shift_name": None})), ctx
    )
    assert not missing.valid and "shift_name is required" in missing.error


def test_difference_is_exact() -> None:
    assert difference(194, 21) == {
        "difference": -173.0,
        "change_percent": -89.2,
        "direction": "lower",
    }
    assert difference(0.1, 0.3) == {
        "difference": 0.2,
        "change_percent": 200.0,
        "direction": "higher",
    }
    assert difference(0, 5) == {"difference": 5.0, "change_percent": None, "direction": "higher"}
    assert difference(None, 5)["direction"] == "unknown"
    assert difference(78.4, 78.4)["direction"] == "unchanged"


def test_compare_periods_uses_the_services(
    bottling: Bottling, load: Callable[..., None], world: object
) -> None:
    load("labeler_jam")
    user = world.users["production_supervisor"]  # type: ignore[attr-defined]
    ctx = ToolContext(user, user.membership.organization, JAM_END + timedelta(hours=1))
    before = (JAM_START - timedelta(hours=1), JAM_START)
    args = {
        "metric": "downtime_minutes",
        "line_id": bottling.line.pk,
        "range_a": {"start": iso(before[0]), "end": iso(before[1])},
        "range_b": {"start": iso(JAM_START), "end": iso(JAM_END)},
    }
    outcome = run_tool(RawToolCall("t", "compare_periods", json.dumps(args)), ctx)
    assert outcome.result is not None
    data = outcome.result.data
    expected = summary(
        select_entries([bottling.line], AnalysisFilters(start=JAM_START, end=JAM_END, now=ctx.now)),
        "line",
    )
    assert data["b"]["value"] == minutes(expected["total_seconds"]) > 0
    assert data["a"]["value"] == 0
    assert data["difference"] == data["b"]["value"]
    assert data["change_percent"] is None  # zero base
    assert "Range A is zero: no percentage change." in outcome.result.warnings
