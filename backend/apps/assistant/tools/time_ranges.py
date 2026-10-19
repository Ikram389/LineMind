"""Time ranges in Python, so the model never works out dates itself.

"today", "last week", "the Night shift on 12 Oct" become exact UTC instants, computed in
the factory's timezone from its shift definitions (a night shift crosses midnight and
belongs to the day it starts). Ranges that are still going end at "now".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.assistant.tools.core import (
    LINE,
    ArgumentError,
    ChoiceParam,
    DateParam,
    TextParam,
    Tool,
    ToolContext,
    ToolResult,
    iso,
    range_label,
)
from apps.organizations.models import Factory
from apps.production.models import Shift
from apps.production.services.shifts import current_shift, occurrence, shift_periods

PHRASES = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "last_7_days",
    "this_month",
    "last_month",
    "current_shift",
    "previous_shift",
    "shift_on_date",
    "date",
)
NAMES = {
    "today": "Today",
    "yesterday": "Yesterday",
    "this_week": "This week",
    "last_week": "Last week",
    "last_7_days": "Last 7 days",
    "this_month": "This month",
    "last_month": "Last month",
    "date": "Day",
}


class NoSuchPeriod(LookupError):
    """The period exists in words but has no data time (not started, no shift running)."""


@dataclass(frozen=True)
class ResolvedRange:
    start: datetime
    end: datetime
    label: str
    timezone: str
    ongoing: bool  # the period has not ended: it is counted until now

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": iso(self.start),
            "end": iso(self.end),
            "label": self.label,
            "timezone": self.timezone,
            "ongoing": self.ongoing,
        }


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz)


def _finish(start: datetime, end: datetime, name: str, zone: str, now: datetime) -> ResolvedRange:
    if start >= now:
        raise NoSuchPeriod(f"{name} has not started yet, so there is no data for it.")
    ongoing = end > now
    end = min(end, now)
    suffix = " (so far)" if ongoing else ""
    return ResolvedRange(
        start, end, f"{name}{suffix}, {range_label(start, end, zone)}", zone, ongoing
    )


def find_shift(factory: Factory, name: str) -> Shift:
    shifts = list(factory.shifts.filter(is_active=True).prefetch_related("breaks"))
    for shift in shifts:
        if shift.name.casefold() == name.casefold():
            return shift
    known = ", ".join(s.name for s in shifts) or "none defined"
    raise ArgumentError(f"Unknown shift {name!r}. The shifts are: {known}.")


def resolve_range(
    factory: Factory,
    now: datetime,
    phrase: str,
    day: date | None = None,
    shift_name: str | None = None,
) -> ResolvedRange:
    zone = factory.timezone
    tz = ZoneInfo(zone)
    today = now.astimezone(tz).date()

    if phrase == "today":
        return _finish(
            _midnight(today, tz), _midnight(today + timedelta(days=1), tz), "Today", zone, now
        )
    if phrase == "yesterday":
        y = today - timedelta(days=1)
        return _finish(_midnight(y, tz), _midnight(today, tz), "Yesterday", zone, now)
    if phrase in ("this_week", "last_week"):
        monday = today - timedelta(days=today.weekday())
        if phrase == "last_week":
            monday -= timedelta(days=7)
        start = _midnight(monday, tz)
        return _finish(start, _midnight(monday + timedelta(days=7), tz), NAMES[phrase], zone, now)
    if phrase == "last_7_days":
        return _finish(now - timedelta(days=7), now, "Last 7 days", zone, now)
    if phrase in ("this_month", "last_month"):
        first = today.replace(day=1)
        if phrase == "last_month":
            first = (first - timedelta(days=1)).replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
        return _finish(_midnight(first, tz), _midnight(following, tz), NAMES[phrase], zone, now)
    if phrase == "date":
        assert day is not None
        name = f"{day:%a %d %b %Y}"
        return _finish(_midnight(day, tz), _midnight(day + timedelta(days=1), tz), name, zone, now)
    if phrase == "current_shift":
        period = current_shift(factory, now)
        if period is None:
            raise NoSuchPeriod("No shift is running now.")
        return _finish(period.start, period.end, f"{period.shift_name} shift", zone, now)
    if phrase == "previous_shift":
        ended = [p for p in shift_periods(factory, now - timedelta(days=3), now) if p.end <= now]
        if not ended:
            raise NoSuchPeriod("No shift has ended in the last three days.")
        period = ended[-1]
        return _finish(period.start, period.end, f"{period.shift_name} shift", zone, now)
    # shift_on_date
    assert day is not None and shift_name is not None
    shift = find_shift(factory, shift_name)
    period = occurrence(shift, day, tz)
    return _finish(period.start, period.end, f"{shift.name} shift", zone, now)


class ResolveTimeRange(Tool):
    name = "resolve_time_range"
    description = (
        "Turn a period into exact start and end times, in the factory's timezone and shifts. "
        "Call this first whenever the question mentions a period (today, yesterday, this "
        "week, a shift on a date...). Use its start and end in the other tools."
    )
    params = (
        ChoiceParam("phrase", "The period.", choices=PHRASES),
        LINE,
        DateParam("date", "For shift_on_date and date: the day, YYYY-MM-DD.", required=False),
        TextParam("shift_name", "For shift_on_date: the shift name, e.g. Morning.", required=False),
    )

    def check(self, args: dict[str, Any]) -> None:
        if args["phrase"] in ("shift_on_date", "date") and "date" not in args:
            raise ArgumentError(f"date is required for phrase={args['phrase']}.")
        if args["phrase"] == "shift_on_date" and "shift_name" not in args:
            raise ArgumentError("shift_name is required for phrase=shift_on_date.")

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        try:
            resolved = resolve_range(
                line.factory, ctx.now, args["phrase"], args.get("date"), args.get("shift_name")
            )
        except NoSuchPeriod as exc:
            return ToolResult({"error": "no_data", "message": str(exc)}, error="no_data")
        data = resolved.as_dict()
        warnings = ["The period is not over: it is counted until now."] if resolved.ongoing else []
        return ToolResult(data, warnings=warnings, resolved_range={**data, "line_id": line.pk})
