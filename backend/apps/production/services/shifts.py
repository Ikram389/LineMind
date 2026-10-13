"""Concrete shift periods, computed on the fly from Shift definitions (nothing is stored).

- Shift times are local wall-clock times in the factory's timezone.
- end_time <= start_time means the shift ends the next day (e.g. 22:00-06:00).
- A shift occurrence belongs to the weekday it starts on.
- On daylight-saving change days the shift keeps its wall-clock times, so it
  really lasts one hour less or more. A wall-clock time that does not exist or
  exists twice resolves with Python's default (fold=0): the earlier offset.
- Breaks are placed relative to their shift's start, so a 02:00 break in a
  22:00 shift falls on the next calendar day.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apps.organizations.models import Factory
from apps.production.models import Shift

DAY = 86_400


@dataclass(frozen=True)
class ShiftPeriod:
    shift_id: int
    shift_name: str
    local_date: date  # the date the shift starts on, in factory time
    start: datetime  # UTC
    end: datetime  # UTC
    breaks: tuple[tuple[datetime, datetime], ...]  # UTC

    @property
    def label(self) -> str:
        return f"{self.shift_name} {self.local_date.isoformat()}"


def _seconds_after(reference: time, moment: time) -> int:
    """Seconds from `reference` forward to `moment` on a 24-hour clock (0 to 86,399)."""
    ref = reference.hour * 3600 + reference.minute * 60 + reference.second
    mom = moment.hour * 3600 + moment.minute * 60 + moment.second
    return (mom - ref) % DAY


def shift_length_seconds(start: time, end: time) -> int:
    """Wall-clock length of a shift; a shift ending at or before its start ends next day."""
    return _seconds_after(start, end) or DAY


def break_fits_in_shift(shift_start: time, shift_end: time, start: time, end: time) -> bool:
    offset_start = _seconds_after(shift_start, start)
    offset_end = _seconds_after(shift_start, end)
    return 0 <= offset_start < offset_end <= shift_length_seconds(shift_start, shift_end)


def _to_utc(local_naive: datetime, tz: ZoneInfo) -> datetime:
    return local_naive.replace(tzinfo=tz).astimezone(UTC)


def occurrence(shift: Shift, local_date: date, tz: ZoneInfo) -> ShiftPeriod:
    """The occurrence of `shift` that starts on `local_date` (factory time)."""
    local_start = datetime.combine(local_date, shift.start_time)
    local_end = local_start + timedelta(
        seconds=shift_length_seconds(shift.start_time, shift.end_time)
    )
    breaks = []
    for shift_break in shift.breaks.all():
        b_start = local_start + timedelta(
            seconds=_seconds_after(shift.start_time, shift_break.start_time)
        )
        b_end = local_start + timedelta(
            seconds=_seconds_after(shift.start_time, shift_break.end_time)
        )
        breaks.append((_to_utc(b_start, tz), _to_utc(b_end, tz)))
    return ShiftPeriod(
        shift_id=shift.pk,
        shift_name=shift.name,
        local_date=local_date,
        start=_to_utc(local_start, tz),
        end=_to_utc(local_end, tz),
        breaks=tuple(sorted(breaks)),
    )


def shift_periods(
    factory: Factory,
    start: datetime,
    end: datetime,
    shifts: Iterable[Shift] | None = None,
) -> list[ShiftPeriod]:
    """Every shift occurrence of the factory that overlaps [start, end), sorted by start.

    Occurrences are not clipped; callers clip to their own range.
    """
    tz = ZoneInfo(factory.timezone)
    if shifts is None:
        shifts = factory.shifts.filter(is_active=True).prefetch_related("breaks")
    # Start one day early: a night shift that began yesterday evening may reach into range.
    first_day = start.astimezone(tz).date() - timedelta(days=1)
    last_day = end.astimezone(tz).date()

    periods = []
    for shift in shifts:
        if not shift.is_active:
            continue
        day = first_day
        while day <= last_day:
            if day.weekday() in shift.days_of_week:
                period = occurrence(shift, day, tz)
                if period.start < end and period.end > start:
                    periods.append(period)
            day += timedelta(days=1)
    return sorted(periods, key=lambda p: (p.start, p.shift_id))
