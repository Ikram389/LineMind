"""Pure OEE calculation (no database): definitions, settings, counting rules, warnings."""

from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest

from apps.analytics.services.buckets import hour_buckets
from apps.analytics.services.oee import calculate, compute_inputs, percent, sum_inputs
from apps.analytics.tests.support import at, make_data, whole_order
from apps.production.services.timeset import TimeSet

UTC_ZONE = ZoneInfo("UTC")


def codes(result: object) -> set[str]:
    return {w["code"] for w in result.warnings}  # type: ignore[attr-defined]


def run(data: object, start: float = 0, end: float = 480) -> object:
    return calculate(compute_inputs(data, at(start), at(end)))  # type: ignore[arg-type]


# --- PRODUCT.md §4 reference case ------------------------------------------------------


def test_product_md_reference_case() -> None:
    """480 min shift, 30 min break, 50 min unplanned downtime, 0.6 s, 36,000 total, 720 rejected."""
    data = make_data(
        shifts=[(0, 480)],
        breaks=[(240, 270)],
        downtime=[(100, 150, "breakdown")],
        readings=[(0, 0, 0), (480, 36_000, 720)],
        orders=whole_order(Fraction(3, 5)),
    )

    result = run(data)
    i = result.inputs

    assert i.planned_production_seconds == 450 * 60
    assert i.unplanned_downtime_seconds == 50 * 60
    assert i.run_seconds == 400 * 60
    assert (i.total_count, i.rejected_count, i.good_count) == (36_000, 720, 35_280)
    assert result.availability.value == Fraction(8, 9)
    assert result.performance.value == Fraction(9, 10)
    assert result.quality.value == Fraction(49, 50)
    assert result.oee.value == Fraction(8, 9) * Fraction(9, 10) * Fraction(49, 50)
    assert [
        percent(r.value)
        for r in (result.availability, result.performance, result.quality, result.oee)
    ] == [
        88.89,
        90.00,
        98.00,
        78.40,
    ]
    assert result.warnings == []


# --- Planned time and downtime ---------------------------------------------------------


def test_planned_stop_reduces_planned_time_not_availability() -> None:
    data = make_data(
        shifts=[(0, 60)],
        downtime=[(10, 20, "planned")],
        readings=[(0, 0, 0), (60, 5000, 0)],
        orders=whole_order(),
    )

    result = run(data, 0, 60)

    assert result.inputs.planned_production_seconds == 50 * 60
    assert result.inputs.unplanned_downtime_seconds == 0
    assert result.availability.value == 1


def test_overlapping_downtime_is_counted_once() -> None:
    data = make_data(
        shifts=[(0, 60)],
        breaks=[(40, 50)],
        downtime=[
            (10, 20, "breakdown"),
            (15, 25, "no_data"),  # overlaps the breakdown
            (12, 18, "starved"),  # inside the breakdown
            (45, 55, "breakdown"),  # half inside the break
        ],
        readings=[(0, 0, 0), (60, 1000, 0)],
        orders=whole_order(),
    )

    i = run(data, 0, 60).inputs

    assert i.planned_production_seconds == 50 * 60  # break removed
    assert i.unplanned_downtime_seconds == (15 + 5) * 60  # [10,25) + [50,55)
    assert i.run_seconds == 30 * 60


@pytest.mark.parametrize(
    ("handling", "planned_min", "unplanned_min"), [("downtime", 60, 10), ("exclude", 50, 0)]
)
def test_no_data_setting(handling: str, planned_min: int, unplanned_min: int) -> None:
    data = make_data(
        shifts=[(0, 60)],
        downtime=[(20, 30, "no_data")],
        readings=[(0, 0, 0), (60, 4000, 0)],
        orders=whole_order(),
        settings={"no_data_handling": handling},
    )

    result = run(data, 0, 60)

    assert result.inputs.planned_production_seconds == planned_min * 60
    assert result.inputs.unplanned_downtime_seconds == unplanned_min * 60
    assert percent(result.data_coverage.value) == pytest.approx(83.33)
    assert "low_data_coverage" in codes(result)


@pytest.mark.parametrize(
    ("planned", "planned_min", "unplanned_min"), [(False, 60, 10), (True, 50, 0)]
)
def test_changeover_setting(planned: bool, planned_min: int, unplanned_min: int) -> None:
    data = make_data(
        shifts=[(0, 60)],
        downtime=[(20, 30, "breakdown", True)],  # classified with an is_changeover reason
        readings=[(0, 0, 0), (60, 4000, 0)],
        orders=whole_order(),
        settings={"changeovers_are_planned": planned},
    )

    i = run(data, 0, 60).inputs

    assert i.planned_production_seconds == planned_min * 60
    assert i.unplanned_downtime_seconds == unplanned_min * 60


def test_planned_stops_not_excluded_count_as_downtime() -> None:
    data = make_data(
        shifts=[(0, 60)],
        breaks=[(40, 50)],
        downtime=[(10, 20, "planned")],
        readings=[(0, 0, 0), (60, 4000, 0)],
        orders=whole_order(),
        settings={"planned_stops_excluded": False},
    )

    i = run(data, 0, 60).inputs

    assert i.planned_production_seconds == 60 * 60  # break stays in planned time
    assert i.unplanned_downtime_seconds == 10 * 60  # the planned stop counts as downtime


# --- Counting --------------------------------------------------------------------------


def test_counter_reset_counts_new_value_from_zero() -> None:
    data = make_data(
        shifts=[(0, 60)],
        readings=[(0, 0, 0), (10, 100, 1), (20, 200, 2), (30, 50, 0), (40, 150, 3)],
        orders=whole_order(),
    )

    result = run(data, 0, 60)

    assert result.inputs.total_count == 100 + 100 + 50 + 100
    assert result.inputs.rejected_count == 1 + 1 + 0 + 3
    assert result.inputs.counter_resets == 1
    assert "counter_reset" in codes(result)


def test_first_reading_is_only_a_baseline() -> None:
    data = make_data(
        shifts=[(0, 60)], readings=[(5, 18_420, 12), (60, 18_920, 12)], orders=whole_order()
    )

    assert run(data, 0, 60).inputs.total_count == 500


def test_readings_outside_planned_time_are_not_counted() -> None:
    data = make_data(
        shifts=[(0, 60)],
        breaks=[(20, 30)],
        readings=[(0, 0, 0), (20, 100, 0), (25, 150, 0), (30, 200, 0), (60, 300, 0)],
        orders=whole_order(),
    )

    # 20 (end of planned segment) counts; 25 and 30 fall in the break; 60 counts.
    assert run(data, 0, 60).inputs.total_count == 100 + 100


def test_performance_above_100_warns_and_is_not_capped() -> None:
    data = make_data(
        shifts=[(0, 60)],
        readings=[(0, 0, 0), (60, 6000, 0)],
        orders=whole_order(Fraction(9, 10)),  # wrong: the line really runs at 0.6 s
    )

    result = run(data, 0, 60)

    assert result.performance.value == Fraction(3, 2)
    assert percent(result.performance.value) == 150.0
    assert "performance_above_100" in codes(result)


def test_exactly_100_percent_gives_no_warning() -> None:
    data = make_data(shifts=[(0, 60)], readings=[(0, 0, 0), (60, 6000, 0)], orders=whole_order())

    result = run(data, 0, 60)

    assert result.performance.value == 1
    assert "performance_above_100" not in codes(result)


def test_no_product_uses_line_speed_and_warns() -> None:
    data = make_data(
        shifts=[(0, 60)],
        readings=[(0, 0, 0), (60, 6000, 0)],
        orders=[(0, 30, "W050", Fraction(3, 5))],  # second half has no order
        fallback=Fraction(3, 5),
    )

    result = run(data, 0, 60)

    assert result.inputs.unassigned_planned_seconds == 30 * 60
    assert "no_product_assigned" in codes(result)
    assert result.performance.value == 1


def test_two_products_sum_their_ideal_times() -> None:
    data = make_data(
        shifts=[(0, 60)],
        readings=[(0, 0, 0), (30, 3000, 0), (60, 5000, 0)],
        orders=[(0, 30, "W050", Fraction(3, 5)), (30, 60, "W150", Fraction(9, 10))],
    )

    i = run(data, 0, 60).inputs

    assert i.ideal_production_seconds == 3000 * Fraction(3, 5) + 2000 * Fraction(9, 10)
    assert {p["sku"]: p["count"] for p in i.products.values()} == {"W050": 3000, "W150": 2000}


def test_missing_rejects_warn() -> None:
    data = make_data(shifts=[(0, 60)], readings=[(0, 0, 0), (60, 100, None)], orders=whole_order())

    assert "rejects_not_reported" in codes(run(data, 0, 60))


# --- Edge cases ------------------------------------------------------------------------


def test_zero_planned_time_returns_nulls_with_reason() -> None:
    data = make_data(shifts=[], readings=[(0, 0, 0), (60, 100, 0)])

    result = run(data, 0, 60)

    assert result.availability.value is None
    assert result.oee.value is None
    assert result.null_reason == "no planned production time in this range"


def test_line_that_never_ran_has_oee_zero() -> None:
    data = make_data(
        shifts=[(0, 60)], downtime=[(0, 60, "breakdown")], readings=[(0, 0, 0), (60, 0, 0)]
    )

    result = run(data, 0, 60)

    assert result.availability.value == 0
    assert result.performance.value is None
    assert result.oee.value == 0


def test_time_without_any_data_is_no_data() -> None:
    data = make_data(
        shifts=[(0, 60)], readings=[(30, 0, 0), (60, 3000, 0)], first_seen=30, orders=whole_order()
    )

    result = run(data, 0, 60)

    assert result.inputs.no_data_seconds == 30 * 60
    assert result.inputs.unplanned_downtime_seconds == 30 * 60
    assert "low_data_coverage" in codes(result)


def test_range_in_future_is_cut_at_now() -> None:
    data = make_data(
        shifts=[(0, 60)], readings=[(0, 0, 0), (30, 3000, 0)], now=at(30), orders=whole_order()
    )

    result = run(data, 0, 60)

    assert result.inputs.computed_until == at(30)
    assert result.inputs.planned_production_seconds == 30 * 60
    assert "range_in_future" in codes(result)


def test_hourly_buckets_sum_to_the_whole_range() -> None:
    data = make_data(
        shifts=[(0, 480)],
        breaks=[(240, 270)],
        downtime=[(100, 150, "breakdown"), (290, 300, "no_data"), (59, 61, "starved")],
        readings=[(m, m * 100, m) for m in range(0, 481, 10)],
        orders=[(0, 200, "W050", Fraction(3, 5)), (200, 600, "W150", Fraction(9, 10))],
    )
    buckets = hour_buckets(at(0), at(480), UTC_ZONE)
    parts = [compute_inputs(data, b.start, b.end) for b in buckets]

    whole = compute_inputs(data, at(0), at(480))
    summed = sum_inputs(parts)

    for name in (
        "planned_production_seconds",
        "unplanned_downtime_seconds",
        "run_seconds",
        "total_count",
        "rejected_count",
        "ideal_production_seconds",
        "covered_seconds",
    ):
        assert getattr(summed, name) == getattr(whole, name), name
    assert calculate(summed).oee.value == calculate(whole).oee.value


def test_timeset_operations() -> None:
    a = TimeSet.of([(at(0), at(10)), (at(5), at(20)), (at(30), at(40))])
    b = TimeSet.of([(at(15), at(35))])

    assert a.intervals == ((at(0), at(20)), (at(30), at(40)))
    assert (a & b).seconds() == 10 * 60
    assert (a - b).seconds() == 20 * 60
    assert (a | b).seconds() == 40 * 60
    assert a.contains_end_inclusive(at(20)) and not a.contains_end_inclusive(at(0))
