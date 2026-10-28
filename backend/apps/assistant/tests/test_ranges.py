"""Time ranges the model cannot invent: new phrases in the factory's timezone, refused
argument combinations, and data tools that only accept ranges LineMind resolved."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time

import pytest

from apps.assistant.providers.base import RawToolCall
from apps.assistant.services.tool_runner import run_tool
from apps.assistant.tools import TOOLS
from apps.assistant.tools.core import ToolContext, iso
from apps.assistant.tools.time_ranges import ResolvedRange, resolve_range
from apps.organizations.models import Factory
from apps.production.models import Shift
from tests.helpers import World
from tests.lines import Bottling

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


def span(r: ResolvedRange) -> tuple[str, str]:
    return iso(r.start), iso(r.end)


def ctx_for(world: World, now: datetime = NOW) -> ToolContext:
    user = world.users["production_supervisor"]
    return ToolContext(user, user.membership.organization, now)


def call(ctx: ToolContext, name: str, bottling: Bottling, **args: object) -> object:
    return run_tool(RawToolCall("t", name, json.dumps({"line_id": bottling.line.pk, **args})), ctx)


# --- New phrases ------------------------------------------------------------------------


def test_week_containing_a_date(algiers: Factory) -> None:
    week = resolve_range(algiers, NOW, "week_containing_date", day=date(2026, 10, 7))  # Wednesday
    # Monday 5 Oct 00:00 in Algiers is Sunday 4 Oct 23:00 UTC; the week ends the next Monday.
    assert span(week) == ("2026-10-04T23:00:00Z", "2026-10-11T23:00:00Z")
    assert week.label == "Week, Mon 05 Oct – Sun 11 Oct 2026 (Africa/Algiers)"
    current = resolve_range(algiers, NOW, "week_containing_date", day=date(2026, 10, 17))
    assert span(current) == ("2026-10-11T23:00:00Z", "2026-10-17T12:05:00Z")  # cut at now
    assert current.ongoing and "(so far)" in current.label


def test_date_range_includes_both_local_days(algiers: Factory) -> None:
    r = resolve_range(
        algiers, NOW, "date_range", start_date=date(2026, 10, 5), end_date=date(2026, 10, 9)
    )
    assert span(r) == ("2026-10-04T23:00:00Z", "2026-10-09T23:00:00Z")
    assert r.label == "Mon 05 Oct – Fri 09 Oct 2026 (Africa/Algiers)"
    one_day = resolve_range(
        algiers, NOW, "date_range", start_date=date(2026, 10, 5), end_date=date(2026, 10, 5)
    )
    assert span(one_day) == ("2026-10-04T23:00:00Z", "2026-10-05T23:00:00Z")


def test_month_containing_a_date(algiers: Factory) -> None:
    september = resolve_range(algiers, NOW, "month_containing_date", day=date(2026, 9, 15))
    assert span(september) == ("2026-08-31T23:00:00Z", "2026-09-30T23:00:00Z")
    assert september.label == "September 2026, Tue 01 Sep – Wed 30 Sep 2026 (Africa/Algiers)"
    february = resolve_range(algiers, NOW, "month_containing_date", day=date(2026, 2, 3))
    assert span(february) == ("2026-01-31T23:00:00Z", "2026-02-28T23:00:00Z")


def test_whole_day_labels_do_not_repeat_the_date(algiers: Factory) -> None:
    day = resolve_range(algiers, NOW, "date", day=date(2026, 10, 12))
    assert day.label == "Mon 12 Oct 2026 (Africa/Algiers)"
    assert (
        resolve_range(algiers, NOW, "yesterday").label
        == "Yesterday, Fri 16 Oct 2026 (Africa/Algiers)"
    )


# --- Refused combinations ----------------------------------------------------------------


@pytest.mark.parametrize(
    "args, message",
    [
        ({"phrase": "this_week", "date": "2026-10-12"}, "phrase=this_week does not take date"),
        ({"phrase": "today", "shift_name": "Night"}, "phrase=today does not take shift_name"),
        ({"phrase": "date"}, "phrase=date needs date"),
        (
            {"phrase": "week_containing_date", "start_date": "2026-10-05"},
            "does not take start_date",
        ),
        ({"phrase": "date_range", "start_date": "2026-10-05"}, "phrase=date_range needs end_date"),
        (
            {
                "phrase": "date_range",
                "date": "2026-10-05",
                "start_date": "2026-10-05",
                "end_date": "2026-10-09",
            },
            "phrase=date_range does not take date",
        ),
        ({"phrase": "shift_on_date", "date": "2026-10-12"}, "needs shift_name"),
        (
            {"phrase": "date_range", "start_date": "2026-10-09", "end_date": "2026-10-05"},
            "on or after start_date",
        ),
        (
            {"phrase": "date_range", "start_date": "2026-01-01", "end_date": "2026-06-30"},
            "at most 92 days",
        ),
    ],
)
def test_invalid_combinations_are_refused_not_ignored(
    bottling: Bottling, algiers: Factory, world: World, args: dict[str, str], message: str
) -> None:
    ctx = ctx_for(world)
    outcome = call(ctx, "resolve_time_range", bottling, **args)
    assert not outcome.valid  # type: ignore[attr-defined]
    error = outcome.error  # type: ignore[attr-defined]
    assert message in error
    if "does not take" in message or "needs" in message:
        # The error lists what every phrase accepts, so the model can correct itself.
        assert "week_containing_date, month_containing_date: date" in error
        assert "date_range: start_date and end_date" in error
    assert ctx.ranges.entries == {}  # nothing was resolved


# --- Data tools only accept resolved ranges ----------------------------------------------


def test_resolved_ranges_get_an_id_the_data_tools_accept(
    bottling: Bottling, algiers: Factory, world: World, load: Callable[..., None]
) -> None:
    load("labeler_jam")  # Mon 12 Oct 2026
    ctx = ctx_for(world)
    week = call(
        ctx, "resolve_time_range", bottling, phrase="week_containing_date", date="2026-10-12"
    )
    data = week.result.data  # type: ignore[attr-defined]
    by_id = call(ctx, "get_downtime", bottling, range_id=data["range_id"])
    assert by_id.valid and by_id.result.data["stops"] > 0  # type: ignore[attr-defined]
    exact = call(ctx, "get_downtime", bottling, start=data["start"], end=data["end"])
    assert exact.valid  # type: ignore[attr-defined]
    assert exact.clean_args["start"] == by_id.clean_args["start"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "args",
    [
        {"start": "2026-10-12T00:00:00Z", "end": "2026-10-19T00:00:00Z"},  # UTC midnights, made up
        {
            "start": "2026-10-11T23:00:00Z",
            "end": "2026-10-18T23:00:00Z",
        },  # right, but never resolved
        {"range_id": "r7"},
        {"start": "2026-10-11T23:00:00Z"},
        {},
    ],
)
def test_self_made_timestamps_are_rejected(
    bottling: Bottling, algiers: Factory, world: World, args: dict[str, str]
) -> None:
    outcome = call(ctx_for(world), "get_downtime", bottling, **args)
    assert not outcome.valid  # type: ignore[attr-defined]
    assert "resolve_time_range" in outcome.error  # type: ignore[attr-defined]


def test_range_ids_do_not_carry_over_to_another_question(
    bottling: Bottling, algiers: Factory, world: World
) -> None:
    first = call(ctx_for(world), "resolve_time_range", bottling, phrase="yesterday")
    rid = first.result.data["range_id"]  # type: ignore[attr-defined]
    outcome = call(ctx_for(world), "get_downtime", bottling, range_id=rid)  # a new question
    assert not outcome.valid and "Unknown range_id" in outcome.error  # type: ignore[attr-defined]


def test_every_tool_with_a_time_range_only_accepts_resolved_ranges() -> None:
    for tool in TOOLS:
        names = {p.name for p in tool.params}
        if {"start", "end", "range_a", "range_b"} & names:
            assert tool.ranges, f"{tool.name} takes a time range but does not check it"
            assert "range_id" in names or {"range_a_id", "range_b_id"} <= names, tool.name
