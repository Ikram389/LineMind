"""OEE: the one place where Availability, Performance, Quality and OEE are calculated.

Definitions (docs/PRODUCT.md §4):
    Planned production time = shift time - breaks - planned stops
    Run time                = planned production time - unplanned downtime
    Availability            = run time / planned production time
    Performance             = ideal production time / run time
                              (ideal production time = sum of ideal cycle time x count,
                               i.e. ideal cycle time x total count for a single product)
    Quality                 = good count / total count
    OEE                     = Availability x Performance x Quality

Everything here is a pure function over `LineData` (loaded by oee_data.py).
Times are exact (Fraction seconds) and every overlap is resolved with TimeSet
operations, so no second is ever counted twice. Results are rounded only at
the very end.

Counting rules:
- Counters are cumulative; production is the difference between consecutive
  readings of the counting machine, credited to the later reading's timestamp.
- A reading counts if its timestamp is in (window start, window end] and inside
  planned production time (end-inclusive, see TimeSet.contains_end_inclusive).
- A counter that goes down was reset: the new value counts from zero (warning).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from apps.organizations.oee_settings import NO_DATA_EXCLUDED
from apps.production.services.timeset import TimeSet

FAULT_CATEGORIES = frozenset({"breakdown", "blocked", "starved"})
LOW_COVERAGE = Fraction(9, 10)
ZERO = Fraction(0)


# --- Input data ----------------------------------------------------------------------


@dataclass(frozen=True)
class DowntimeSpan:
    start: datetime
    end: datetime  # ongoing stops are closed at "now" by the loader
    category: str
    is_changeover: bool = False


@dataclass(frozen=True)
class Reading:
    timestamp: datetime
    count: int
    rejected: int | None


@dataclass(frozen=True)
class OrderSpan:
    start: datetime
    end: datetime
    sku: str
    name: str
    ideal_cycle_time: Fraction  # seconds

    def covers(self, moment: datetime) -> bool:
        return self.start < moment <= self.end


@dataclass(frozen=True)
class LineData:
    shift_time: TimeSet
    breaks: TimeSet
    downtime: tuple[DowntimeSpan, ...]
    readings: tuple[Reading, ...]  # sorted; starts with the last reading before the range
    orders: tuple[OrderSpan, ...]
    fallback_cycle_time: Fraction | None  # 3600 / slowest machine speed
    first_seen: datetime | None  # counting machine's first and last event ever
    last_seen: datetime | None
    stale_after_seconds: int
    settings: dict[str, Any]
    now: datetime


# --- Inputs (additive, so buckets can be summed) ---------------------------------------


@dataclass
class OEEInputs:
    shift_seconds: Fraction = ZERO
    break_seconds: Fraction = ZERO
    planned_stop_seconds: Fraction = ZERO
    changeover_seconds: Fraction = ZERO
    no_data_seconds: Fraction = ZERO
    excluded_seconds: Fraction = ZERO  # removed from shift time (union of the above, per settings)
    planned_production_seconds: Fraction = ZERO
    unplanned_downtime_seconds: Fraction = ZERO
    run_seconds: Fraction = ZERO
    total_count: int = 0
    rejected_count: int = 0
    ideal_production_seconds: Fraction = ZERO
    coverage_base_seconds: Fraction = ZERO
    covered_seconds: Fraction = ZERO
    unassigned_planned_seconds: Fraction = ZERO
    unassigned_count: int = 0
    counter_resets: int = 0
    readings_without_rejects: int = 0
    readings_counted: int = 0
    computed_until: datetime | None = None
    range_in_future: bool = False
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    downtime_by_category_seconds: dict[str, Fraction] = field(default_factory=dict)

    @property
    def good_count(self) -> int:
        return self.total_count - self.rejected_count

    def __add__(self, other: OEEInputs) -> OEEInputs:
        result = OEEInputs()
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(other, f.name)
            if f.name == "products":
                merged = {sku: dict(v) for sku, v in a.items()}
                for sku, item in b.items():
                    if sku in merged:
                        merged[sku]["count"] += item["count"]
                    else:
                        merged[sku] = dict(item)
                setattr(result, f.name, merged)
            elif f.name == "downtime_by_category_seconds":
                setattr(result, f.name, {k: a.get(k, ZERO) + b.get(k, ZERO) for k in {*a, *b}})
            elif f.name == "computed_until":
                setattr(result, f.name, max((x for x in (a, b) if x is not None), default=None))
            elif f.name == "range_in_future":
                setattr(result, f.name, a or b)
            else:
                setattr(result, f.name, a + b)
        return result


def sum_inputs(items: Sequence[OEEInputs]) -> OEEInputs:
    total = OEEInputs()
    for item in items:
        total = total + item
    return total


def _spans(data: LineData, keep: Any) -> TimeSet:
    return TimeSet.of((d.start, d.end) for d in data.downtime if keep(d))


def missing_data(data: LineData, start: datetime, end: datetime) -> TimeSet:
    """Time with no data at all: before the first event, or after the data went stale."""
    if data.first_seen is None or data.last_seen is None:
        return TimeSet.of([(start, end)])
    stale_from = data.last_seen + timedelta(seconds=data.stale_after_seconds)
    return TimeSet.of([(start, min(end, data.first_seen)), (max(start, stale_from), end)])


def compute_inputs(data: LineData, start: datetime, end: datetime) -> OEEInputs:
    """All OEE inputs for the time window [start, end) (never beyond `now`)."""
    settings = data.settings
    end_eff = min(end, data.now)
    inputs = OEEInputs(computed_until=end_eff, range_in_future=end > data.now)
    if end_eff <= start:
        return inputs

    shift = data.shift_time.clip(start, end_eff)
    breaks = data.breaks & shift
    changeovers = _spans(data, lambda d: d.is_changeover) & shift
    planned_stops = _spans(data, lambda d: d.category == "planned" and not d.is_changeover) & shift
    faults = _spans(data, lambda d: d.category in FAULT_CATEGORIES and not d.is_changeover) & shift
    no_data = (
        _spans(data, lambda d: d.category == "no_data" and not d.is_changeover)
        | missing_data(data, start, end_eff)
    ) & shift

    # 1. What is removed from shift time (planned production time = shift - excluded).
    excluded = TimeSet()
    if settings["planned_stops_excluded"]:
        excluded = excluded | breaks | planned_stops
    if settings["changeovers_are_planned"]:
        excluded = excluded | changeovers
    no_data_excluded = settings["no_data_handling"] == NO_DATA_EXCLUDED
    coverage_base = shift - excluded  # planned time before removing no-data time
    if no_data_excluded:
        excluded = excluded | no_data
    planned = shift - excluded

    # 2. Unplanned downtime, only inside planned time, each second once.
    down = faults
    if not settings["changeovers_are_planned"]:
        down = down | changeovers
    if not no_data_excluded:
        down = down | no_data
    if not settings["planned_stops_excluded"]:
        down = down | planned_stops
    down = down & planned
    run = planned - down

    inputs.shift_seconds = shift.seconds()
    inputs.break_seconds = breaks.seconds()
    inputs.planned_stop_seconds = planned_stops.seconds()
    inputs.changeover_seconds = changeovers.seconds()
    inputs.no_data_seconds = no_data.seconds()
    inputs.excluded_seconds = excluded.seconds()
    inputs.planned_production_seconds = planned.seconds()
    inputs.unplanned_downtime_seconds = down.seconds()
    inputs.run_seconds = run.seconds()
    inputs.coverage_base_seconds = coverage_base.seconds()
    inputs.covered_seconds = (coverage_base - no_data).seconds()
    inputs.downtime_by_category_seconds = {
        category: (_spans(data, lambda d, c=category: d.category == c) & down).seconds()
        for category in sorted({d.category for d in data.downtime})
    }
    inputs.downtime_by_category_seconds = {
        k: v for k, v in inputs.downtime_by_category_seconds.items() if v
    }

    # 3. Production in planned time, and the time it ideally takes.
    orders = TimeSet.of((o.start, o.end) for o in data.orders)
    inputs.unassigned_planned_seconds = (planned - orders).seconds()
    _count(data, start, end_eff, planned, inputs)
    return inputs


def _count(
    data: LineData, start: datetime, end: datetime, planned: TimeSet, inputs: OEEInputs
) -> None:
    previous: Reading | None = None
    for reading in data.readings:
        counts = (
            previous is not None
            and start < reading.timestamp <= end
            and planned.contains_end_inclusive(reading.timestamp)
        )
        if counts:
            assert previous is not None
            produced = reading.count - previous.count
            if produced < 0:  # counter reset: the new value counts from zero
                produced = reading.count
                inputs.counter_resets += 1
            if reading.rejected is None or previous.rejected is None:
                rejected = 0
                inputs.readings_without_rejects += 1
            else:
                rejected = reading.rejected - previous.rejected
                if rejected < 0:
                    rejected = reading.rejected
            inputs.total_count += produced
            inputs.rejected_count += rejected
            inputs.readings_counted += 1

            order = next((o for o in data.orders if o.covers(reading.timestamp)), None)
            if order is not None:
                cycle_time = order.ideal_cycle_time
                key, name = order.sku, order.name
            else:
                cycle_time = data.fallback_cycle_time or ZERO
                key, name = "", "No product assigned (line nominal speed)"
                inputs.unassigned_count += produced
            inputs.ideal_production_seconds += cycle_time * produced
            product = inputs.products.setdefault(
                key, {"sku": key or None, "name": name, "ideal_cycle_time": cycle_time, "count": 0}
            )
            product["count"] += produced
        previous = reading


# --- Results -----------------------------------------------------------------------------


@dataclass
class Ratio:
    value: Fraction | None
    null_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.value is None:
            return {"ratio": None, "percent": None, "null_reason": self.null_reason}
        return {"ratio": round(float(self.value), 6), "percent": percent(self.value)}


def percent(value: Fraction) -> float:
    exact = Decimal(value.numerator) / Decimal(value.denominator) * 100
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass
class OEEResult:
    inputs: OEEInputs
    availability: Ratio
    performance: Ratio
    quality: Ratio
    oee: Ratio
    data_coverage: Ratio
    warnings: list[dict[str, str]]
    null_reason: str | None = None


def calculate(inputs: OEEInputs) -> OEEResult:
    """Availability, Performance, Quality and OEE from (possibly summed) inputs."""
    warnings = _warnings(inputs)
    coverage = (
        Ratio(inputs.covered_seconds / inputs.coverage_base_seconds)
        if inputs.coverage_base_seconds
        else Ratio(None, "no shift time in this range")
    )
    planned = inputs.planned_production_seconds
    if planned == 0:
        reason = "no planned production time in this range"
        null = Ratio(None, reason)
        return OEEResult(inputs, null, null, null, null, coverage, warnings, reason)

    availability = Ratio(inputs.run_seconds / planned)
    if inputs.run_seconds == 0:
        performance = Ratio(None, "no run time: the line never ran")
    else:
        performance = Ratio(inputs.ideal_production_seconds / inputs.run_seconds)
        if performance.value is not None and performance.value > 1:
            warnings.append(
                {
                    "code": "performance_above_100",
                    "message": (
                        f"Performance is {percent(performance.value)}%: more was produced than "
                        "the ideal cycle time allows. The ideal cycle time is probably wrong. "
                        "The value is not capped."
                    ),
                }
            )
    if inputs.total_count == 0:
        quality = Ratio(None, "nothing was produced")
    else:
        quality = Ratio(Fraction(inputs.good_count, inputs.total_count))

    if availability.value == 0 or performance.value is None or quality.value is None:
        oee = Ratio(ZERO)  # nothing good could be or was produced
    else:
        oee = Ratio(availability.value * performance.value * quality.value)
    return OEEResult(inputs, availability, performance, quality, oee, coverage, warnings)


def _warnings(inputs: OEEInputs) -> list[dict[str, str]]:
    warnings = []
    if inputs.range_in_future:
        warnings.append(
            {
                "code": "range_in_future",
                "message": f"The range reaches into the future; computed up to "
                f"{inputs.computed_until.isoformat() if inputs.computed_until else 'now'}.",
            }
        )
    if inputs.counter_resets:
        warnings.append(
            {
                "code": "counter_reset",
                "message": f"The counter went down {inputs.counter_resets} time(s); treated as "
                "a reset (the new value counts from zero).",
            }
        )
    if inputs.readings_without_rejects:
        warnings.append(
            {
                "code": "rejects_not_reported",
                "message": f"{inputs.readings_without_rejects} counter reading(s) had no "
                "rejected count; their rejects were counted as zero.",
            }
        )
    if inputs.unassigned_planned_seconds:
        warnings.append(
            {
                "code": "no_product_assigned",
                "message": f"{float(inputs.unassigned_planned_seconds):.0f} s of planned time "
                "had no production order; the line's nominal speed (slowest machine) was used "
                "as the ideal cycle time.",
            }
        )
    if inputs.planned_production_seconds and inputs.readings_counted == 0:
        warnings.append(
            {
                "code": "no_counting_data",
                "message": "No counter readings from the counting machine in planned time.",
            }
        )
    if (
        inputs.coverage_base_seconds
        and inputs.covered_seconds / inputs.coverage_base_seconds < LOW_COVERAGE
    ):
        coverage = percent(inputs.covered_seconds / inputs.coverage_base_seconds)
        warnings.append(
            {
                "code": "low_data_coverage",
                "message": f"Only {coverage}% of planned time has data from the counting machine.",
            }
        )
    return warnings


def result_to_dict(result: OEEResult) -> dict[str, Any]:
    i = result.inputs

    def secs(value: Fraction) -> float:
        return round(float(value), 3)

    return {
        "availability": result.availability.as_dict(),
        "performance": result.performance.as_dict(),
        "quality": result.quality.as_dict(),
        "oee": result.oee.as_dict(),
        "data_coverage": result.data_coverage.as_dict(),
        "null_reason": result.null_reason,
        "warnings": result.warnings,
        "inputs": {
            "shift_seconds": secs(i.shift_seconds),
            "break_seconds": secs(i.break_seconds),
            "planned_stop_seconds": secs(i.planned_stop_seconds),
            "changeover_seconds": secs(i.changeover_seconds),
            "no_data_seconds": secs(i.no_data_seconds),
            "excluded_from_planned_seconds": secs(i.excluded_seconds),
            "planned_production_seconds": secs(i.planned_production_seconds),
            "unplanned_downtime_seconds": secs(i.unplanned_downtime_seconds),
            "unplanned_downtime_by_category_seconds": {
                k: secs(v) for k, v in sorted(i.downtime_by_category_seconds.items())
            },
            "run_seconds": secs(i.run_seconds),
            "total_count": i.total_count,
            "rejected_count": i.rejected_count,
            "good_count": i.good_count,
            "ideal_production_seconds": secs(i.ideal_production_seconds),
            "products": [
                {
                    "sku": p["sku"],
                    "name": p["name"],
                    "ideal_cycle_time_seconds": float(p["ideal_cycle_time"]),
                    "count": p["count"],
                }
                for p in i.products.values()
            ],
            "computed_until": i.computed_until.isoformat() if i.computed_until else None,
        },
    }
