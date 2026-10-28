"""Time ranges in Python, so the model never works out dates itself.

"today", "the week of 12 Oct", "5 to 9 Oct", "September", "the Night shift on 12 Oct"
become exact UTC instants, computed in the factory's timezone from its calendar and shift
definitions (a night shift crosses midnight and belongs to the day it starts). Ranges that
are still going end at "now". Each phrase accepts only its own arguments: anything else is
refused with a clear message, never silently ignored. Every resolved range is registered in
the question's RangeBook and gets a range_id the data tools accept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.assistant.tools.core import (
    LINE,
    MAX_RANGE,
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

# Each phrase and the arguments it takes (besides phrase and line_id).
ACCEPTS: dict[str, tuple[str, ...]] = {
    "today": (),
    "yesterday": (),
    "this_week": (),
    "last_week": (),
    "last_7_days": (),
    "this_month": (),
    "last_month": (),
    "current_shift": (),
    "previous_shift": (),
    "date": ("date",),
    "week_containing_date": ("date",),
    "month_containing_date": ("date",),
    "shift_on_date": ("date", "shift_name"),
    "date_range": ("start_date", "end_date"),
}
PHRASES = tuple(ACCEPTS)
OPTIONAL_ARGS = ("date", "shift_name", "start_date", "end_date")
NAMES = {
    "today": "Today",
    "yesterday": "Yesterday",
    "this_week": "This week",
    "last_week": "Last week",
    "this_month": "This month",
    "last_month": "Last month",
}


def accepted_summary() -> str:
    groups: dict[tuple[str, ...], list[str]] = {}
    for phrase, args in ACCEPTS.items():
        groups.setdefault(args, []).append(phrase)
    parts = []
    for args, phrases in groups.items():
        takes = " and ".join(args) if args else "nothing else"
        parts.append(f"{', '.join(phrases)}: {takes}")
    return "; ".join(parts) + "."


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


def _days(first: date, last: date) -> str:
    """'Mon 12 Oct 2026' or 'Mon 12 Oct – Sun 18 Oct 2026' (inclusive local days)."""
    if first == last:
        return f"{first:%a %d %b %Y}"
    if first.year == last.year:
        return f"{first:%a %d %b} – {last:%a %d %b %Y}"
    return f"{first:%a %d %b %Y} – {last:%a %d %b %Y}"


def _finish(
    start: datetime,
    end: datetime,
    name: str,
    zone: str,
    now: datetime,
    days: tuple[date, date] | None = None,
) -> ResolvedRange:
    """Clip to now and label. `days`: the range is whole local days (no repeated date)."""
    if start >= now:
        raise NoSuchPeriod(f"{name} has not started yet, so there is no data for it.")
    ongoing = end > now
    end = min(end, now)
    if ongoing:
        label = f"{name} (so far), {range_label(start, end, zone)}"
    elif days is not None:
        label = f"{name}, {_days(*days)} ({zone})" if name else f"{_days(*days)} ({zone})"
    else:
        label = f"{name}, {range_label(start, end, zone)}"
    return ResolvedRange(start, end, label, zone, ongoing)


def find_shift(factory: Factory, name: str) -> Shift:
    shifts = list(factory.shifts.filter(is_active=True).prefetch_related("breaks"))
    for shift in shifts:
        if shift.name.casefold() == name.casefold():
            return shift
    known = ", ".join(s.name for s in shifts) or "none defined"
    raise ArgumentError(f"Unknown shift {name!r}. The shifts are: {known}.")


def _whole_days(
    first: date, last: date, name: str, tz: ZoneInfo, zone: str, now: datetime
) -> ResolvedRange:
    """[first 00:00, last + 1 day 00:00) in local time: both days included."""
    start, end = _midnight(first, tz), _midnight(last + timedelta(days=1), tz)
    return _finish(start, end, name, zone, now, days=(first, last))


def resolve_range(
    factory: Factory,
    now: datetime,
    phrase: str,
    day: date | None = None,
    shift_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ResolvedRange:
    zone = factory.timezone
    tz = ZoneInfo(zone)
    today = now.astimezone(tz).date()

    if phrase == "today":
        return _whole_days(today, today, "Today", tz, zone, now)
    if phrase == "yesterday":
        y = today - timedelta(days=1)
        return _whole_days(y, y, "Yesterday", tz, zone, now)
    if phrase in ("this_week", "last_week"):
        monday = today - timedelta(days=today.weekday())
        if phrase == "last_week":
            monday -= timedelta(days=7)
        return _whole_days(monday, monday + timedelta(days=6), NAMES[phrase], tz, zone, now)
    if phrase == "last_7_days":
        return _finish(now - timedelta(days=7), now, "Last 7 days", zone, now)
    if phrase in ("this_month", "last_month"):
        first = today.replace(day=1)
        if phrase == "last_month":
            first = (first - timedelta(days=1)).replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return _whole_days(first, last, NAMES[phrase], tz, zone, now)
    if phrase == "date":
        assert day is not None
        return _whole_days(day, day, "", tz, zone, now)
    if phrase == "week_containing_date":
        assert day is not None
        monday = day - timedelta(days=day.weekday())
        return _whole_days(monday, monday + timedelta(days=6), "Week", tz, zone, now)
    if phrase == "month_containing_date":
        assert day is not None
        first = day.replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return _whole_days(first, last, f"{first:%B %Y}", tz, zone, now)
    if phrase == "date_range":
        assert start_date is not None and end_date is not None
        return _whole_days(start_date, end_date, "", tz, zone, now)
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
        "Turn a period into exact times in the factory's timezone and shifts, and get its "
        "range_id for the other tools. Phrases: today, yesterday, this_week, last_week, "
        "last_7_days, this_month, last_month, current_shift, previous_shift (nothing else); "
        "date, week_containing_date, month_containing_date (date); shift_on_date (date, "
        "shift_name); date_range (start_date, end_date, both days included)."
    )
    params = (
        ChoiceParam("phrase", "The period.", choices=PHRASES),
        LINE,
        DateParam("date", "A day, YYYY-MM-DD (see which phrases take it).", required=False),
        TextParam("shift_name", "For shift_on_date: the shift name, e.g. Morning.", required=False),
        DateParam("start_date", "For date_range: the first day, YYYY-MM-DD.", required=False),
        DateParam(
            "end_date", "For date_range: the last day (included), YYYY-MM-DD.", required=False
        ),
    )

    def check(self, args: dict[str, Any]) -> None:
        phrase = args["phrase"]
        accepts = ACCEPTS[phrase]
        given = {name for name in OPTIONAL_ARGS if name in args}
        extra = sorted(given - set(accepts))
        missing = [name for name in accepts if name not in args]
        if extra or missing:
            problem = (
                f"phrase={phrase} does not take {', '.join(extra)}"
                if extra
                else f"phrase={phrase} needs {', '.join(missing)}"
            )
            raise ArgumentError(f"{problem}. Each phrase takes: {accepted_summary()}")
        if phrase == "date_range":
            if args["end_date"] < args["start_date"]:
                raise ArgumentError("end_date must be on or after start_date.")
            if args["end_date"] - args["start_date"] >= MAX_RANGE:
                raise ArgumentError("The range may be at most 92 days.")

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        try:
            resolved = resolve_range(
                line.factory,
                ctx.now,
                args["phrase"],
                day=args.get("date"),
                shift_name=args.get("shift_name"),
                start_date=args.get("start_date"),
                end_date=args.get("end_date"),
            )
        except NoSuchPeriod as exc:
            return ToolResult({"error": "no_data", "message": str(exc)}, error="no_data")
        known = ctx.ranges.add(resolved.start, resolved.end, resolved.label)
        data = {"range_id": known.range_id, **resolved.as_dict()}
        warnings = ["The period is not over: it is counted until now."] if resolved.ongoing else []
        return ToolResult(data, warnings=warnings, resolved_range={**data, "line_id": line.pk})
