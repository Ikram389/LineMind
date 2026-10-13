"""Concrete shift periods: midnight, weekdays, breaks and daylight saving."""

from datetime import UTC, datetime, time, timedelta

import pytest

from apps.organizations.models import Factory
from apps.production.models import Shift, ShiftBreak
from apps.production.services.shifts import break_fits_in_shift, shift_periods
from tests.helpers import World


def make_shift(
    factory: Factory,
    name: str,
    start: time,
    end: time,
    days: list[int] | None = None,
    breaks: list[tuple[time, time]] | None = None,
) -> Shift:
    shift = Shift.objects.create(
        factory=factory,
        name=name,
        start_time=start,
        end_time=end,
        days_of_week=days if days is not None else [0, 1, 2, 3, 4, 5, 6],
    )
    for b_start, b_end in breaks or []:
        ShiftBreak.objects.create(shift=shift, start_time=b_start, end_time=b_end)
    return shift


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_night_shift_crosses_midnight_in_factory_time(world: World) -> None:
    factory = world.factory_a
    factory.timezone = "Africa/Algiers"  # UTC+1, no daylight saving
    factory.save()
    make_shift(factory, "Night", time(22), time(6), breaks=[(time(2), time(2, 30))])

    # Range: Tuesday 2026-10-13 00:00 to 12:00 UTC.
    periods = shift_periods(factory, utc(2026, 10, 13, 0), utc(2026, 10, 13, 12))

    assert [(p.label, p.start, p.end) for p in periods] == [
        # Started Monday 22:00 Algiers (21:00 UTC), ends Tuesday 06:00 Algiers (05:00 UTC).
        ("Night 2026-10-12", utc(2026, 10, 12, 21), utc(2026, 10, 13, 5)),
    ]
    # The 02:00 break falls on the next calendar day (Tuesday 01:00 UTC).
    assert periods[0].breaks == ((utc(2026, 10, 13, 1), utc(2026, 10, 13, 1, 30)),)


def test_shift_belongs_to_the_weekday_it_starts(world: World) -> None:
    factory = world.factory_a  # UTC
    make_shift(factory, "Night Mon only", time(22), time(6), days=[0])  # Mondays

    periods = shift_periods(factory, utc(2026, 10, 12, 0), utc(2026, 10, 15, 0))  # Mon-Wed

    assert [p.label for p in periods] == ["Night Mon only 2026-10-12"]
    assert periods[0].end == utc(2026, 10, 13, 6)  # ends Tuesday morning


def test_daylight_saving_days_change_shift_length(world: World) -> None:
    factory = world.factory_a
    factory.timezone = "Europe/Paris"
    factory.save()
    make_shift(factory, "Night", time(22), time(6))

    spring = shift_periods(factory, utc(2026, 3, 28, 12), utc(2026, 3, 29, 12))
    autumn = shift_periods(factory, utc(2026, 10, 24, 12), utc(2026, 10, 25, 12))

    spring_night = next(p for p in spring if p.label == "Night 2026-03-28")
    autumn_night = next(p for p in autumn if p.label == "Night 2026-10-24")
    assert spring_night.end - spring_night.start == timedelta(hours=7)  # clocks go forward
    assert autumn_night.end - autumn_night.start == timedelta(hours=9)  # clocks go back


def test_inactive_shifts_are_ignored(world: World) -> None:
    shift = make_shift(world.factory_a, "Morning", time(6), time(14))
    shift.is_active = False
    shift.save()

    assert shift_periods(world.factory_a, utc(2026, 10, 13, 0), utc(2026, 10, 14, 0)) == []


@pytest.mark.parametrize(
    ("shift", "brk", "fits"),
    [
        ((time(6), time(14)), (time(10), time(10, 30)), True),
        ((time(6), time(14)), (time(13, 45), time(14, 15)), False),
        ((time(22), time(6)), (time(2), time(2, 30)), True),
        ((time(22), time(6)), (time(23, 45), time(0, 15)), True),
        ((time(22), time(6)), (time(7), time(7, 30)), False),
    ],
)
def test_break_must_fit_in_shift(
    shift: tuple[time, time], brk: tuple[time, time], fits: bool
) -> None:
    assert break_fits_in_shift(*shift, *brk) is fits
