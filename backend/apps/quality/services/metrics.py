"""Quality metrics: the one place where defect counts, rates, Pareto and trend are computed.

Rules (docs/PRODUCT.md §6):
- A result counts as a defect under its *effective* defect type: the corrected type
  when its current review says "reclassified", otherwise the detected type.
- A result whose current review says "false_reject" is not a defect. It is still
  shown, and counted separately as a false reject. Raw results are never changed.
- Inspected volume comes from machine counters, never from stored good bottles:
  a station inspects what its machine processed. The line's defect rate divides by
  the line total count (LineCounts in production/services/counters.py: counting
  machine output + upstream rejects), so each bottle is counted once.
- Rates of a group are always computed from summed counts, never by averaging rates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Case, CharField, Count, F, IntegerField, Q, QuerySet, Value, When

from apps.analytics.services.buckets import day_buckets, hour_buckets, shift_buckets
from apps.organizations.models import Factory, Machine, ProductionLine
from apps.production.models import Product
from apps.production.services.counters import (
    Keep,
    LineCounts,
    line_counts_by_bucket,
    machine_counts_by_bucket,
)
from apps.production.services.orders import active_orders
from apps.production.services.shifts import shift_periods
from apps.quality.models import DefectType, InspectionResult, InspectionStation, Severity, Verdict

GROUP_BY = ("defect_type", "station", "machine", "product")
UNKNOWN_TYPE_LABEL = "Unknown defect type"
NO_STATION_LABEL = "No inspection station"
NO_PRODUCT_LABEL = "No product assigned"


@dataclass(frozen=True)
class QualityFilters:
    start: datetime
    end: datetime
    station_id: int | None = None
    machine_id: int | None = None
    defect_type: str | None = None  # effective code, or "unknown"
    severity: str | None = None
    product_id: int | None = None
    reviewed: bool | None = None
    verdict: str | None = None


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 6) if whole else None


# --- Selecting results -----------------------------------------------------------------


def _order_spans(
    lines: Sequence[ProductionLine], start: datetime, end: datetime
) -> list[tuple[int, datetime, datetime, int]]:
    """(line id, from, to, product id) of every order overlapping the range."""
    spans = []
    for line in lines:
        for order in active_orders(line).filter(effective_from__lt=end, effective_to__gte=start):
            spans.append((line.pk, order.effective_from, order.effective_to, order.product_id))
    return spans


def annotate_results(
    queryset: QuerySet[InspectionResult],
    lines: Sequence[ProductionLine],
    start: datetime,
    end: datetime,
) -> QuerySet[InspectionResult]:
    """Adds effective_type_id, effective_severity, verdict and product_id."""
    reclassified = Q(current_review__verdict=Verdict.RECLASSIFIED)
    whens = [
        When(line_id=line_id, timestamp__gt=t0, timestamp__lte=t1, then=Value(product_id))
        for line_id, t0, t1, product_id in _order_spans(lines, start, end)
    ]
    return queryset.annotate(
        effective_type_id=Case(
            When(reclassified, then=F("current_review__corrected_defect_type_id")),
            default=F("defect_type_id"),
            output_field=IntegerField(),
        ),
        effective_severity=Case(
            When(reclassified, then=F("current_review__corrected_defect_type__severity")),
            default=F("defect_type__severity"),
            output_field=CharField(),
        ),
        verdict=F("current_review__verdict"),
        product_id=Case(*whens, default=Value(None), output_field=IntegerField())
        if whens
        else Value(None, output_field=IntegerField()),
    )


def select_results(
    lines: Sequence[ProductionLine], f: QualityFilters
) -> QuerySet[InspectionResult]:
    """Every result in the range matching the filters, false rejects included."""
    queryset = annotate_results(
        InspectionResult.objects.filter(
            line__in=lines, timestamp__gte=f.start, timestamp__lt=f.end
        ),
        lines,
        f.start,
        f.end,
    )
    if f.station_id is not None:
        queryset = queryset.filter(station_id=f.station_id)
    if f.machine_id is not None:
        queryset = queryset.filter(machine_id=f.machine_id)
    if f.defect_type == "unknown":
        queryset = queryset.filter(effective_type_id__isnull=True)
    elif f.defect_type:
        codes = DefectType.objects.filter(code=f.defect_type).values_list("pk", flat=True)
        queryset = queryset.filter(effective_type_id__in=list(codes))
    if f.severity:
        queryset = queryset.filter(effective_severity=f.severity)
    if f.product_id is not None:
        queryset = queryset.filter(product_id=f.product_id)
    if f.reviewed is not None:
        queryset = queryset.filter(current_review__isnull=not f.reviewed)
    if f.verdict:
        queryset = queryset.filter(current_review__verdict=f.verdict)
    return queryset


def counted(queryset: QuerySet[InspectionResult]) -> QuerySet[InspectionResult]:
    """Results that count as defects: everything except reviewed false rejects."""
    return queryset.filter(
        Q(current_review__isnull=True) | ~Q(current_review__verdict=Verdict.FALSE_REJECT)
    )


# --- Counter-based volumes ------------------------------------------------------------


def _product_keep(lines: Sequence[ProductionLine], f: QualityFilters) -> dict[int, Keep | None]:
    """With a product filter, volumes only count while that product was running."""
    if f.product_id is None:
        return {line.pk: None for line in lines}
    spans: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for line_id, t0, t1, product_id in _order_spans(lines, f.start, f.end):
        if product_id == f.product_id:
            spans[line_id].append((t0, t1))

    def keep_for(line_id: int) -> Keep:
        return lambda moment: any(t0 < moment <= t1 for t0, t1 in spans[line_id])

    return {line.pk: keep_for(line.pk) for line in lines}


def line_totals(
    lines: Sequence[ProductionLine], f: QualityFilters, buckets: Sequence[tuple[datetime, datetime]]
) -> list[LineCounts]:
    keep = _product_keep(lines, f)
    totals = [LineCounts() for _ in buckets]
    for line in lines:
        for index, counts in enumerate(line_counts_by_bucket(line, buckets, keep[line.pk])):
            current = totals[index]
            totals[index] = LineCounts(
                current.output + counts.output,
                current.output_rejected + counts.output_rejected,
                current.upstream_rejected + counts.upstream_rejected,
            )
    return totals


# --- Summary --------------------------------------------------------------------------


def _station_dict(station: InspectionStation) -> dict[str, Any]:
    return {
        "id": station.pk,
        "name": station.name,
        "machine": {
            "id": station.machine_id,
            "external_id": station.machine.external_id,
            "name": station.machine.name,
        },
        "is_active": station.is_active,
    }


def summary(lines: Sequence[ProductionLine], f: QualityFilters) -> dict[str, Any]:
    results = select_results(lines, f)
    defects = counted(results)
    defect_count = defects.count()

    by_station = dict(
        defects.order_by()
        .values_list("station_id")
        .annotate(n=Count("id"))
        .values_list("station_id", "n")
    )
    station_ids = set(by_station) - {None}
    active = InspectionStation.objects.filter(line__in=lines, is_active=True)
    if f.station_id is not None:
        active = active.filter(pk=f.station_id)
    if f.machine_id is not None:
        active = active.filter(machine_id=f.machine_id)
    station_ids |= set(active.values_list("pk", flat=True))
    stations = InspectionStation.objects.select_related("machine").filter(pk__in=station_ids)
    keep = _product_keep(lines, f)
    inspected_by_station = []
    for station in sorted(stations, key=lambda s: (s.line_id, s.machine.position, s.pk)):
        inspected, _ = machine_counts_by_bucket(
            station.machine, [(f.start, f.end)], keep.get(station.line_id)
        )[0]
        found = by_station.get(station.pk, 0)
        inspected_by_station.append(
            {
                "station": _station_dict(station),
                "inspected": inspected,
                "defects": found,
                "defect_rate": rate(found, inspected),
            }
        )

    total = line_totals(lines, f, [(f.start, f.end)])[0]
    severities = dict(
        defects.order_by()
        .values_list("effective_severity")
        .annotate(n=Count("id"))
        .values_list("effective_severity", "n")
    )
    with_warnings = results.exclude(warnings=[])
    return {
        "inspected_by_station": inspected_by_station,
        "defects_without_station": by_station.get(None, 0),
        "line_total_count": total.total,
        "line_counts": {
            "counting_machine_output": total.output,
            "counting_machine_rejected": total.output_rejected,
            "upstream_rejected": total.upstream_rejected,
        },
        "defects": defect_count,
        "defect_rate": rate(defect_count, total.total),
        "defects_by_severity": {
            **{s.value: severities.get(s.value, 0) for s in Severity},
            "unknown": severities.get(None, 0),
        },
        "false_rejects": results.filter(current_review__verdict=Verdict.FALSE_REJECT).count(),
        "unreviewed": results.filter(current_review__isnull=True).count(),
        "results_with_warnings": with_warnings.count(),
        "warnings": sorted(
            {w for ws in with_warnings.values_list("warnings", flat=True)[:500] for w in ws}
        )[:20],
    }


# --- Pareto ---------------------------------------------------------------------------


def _labels(group_by: str, keys: set[Any]) -> dict[Any, dict[str, Any]]:
    keys = keys - {None}
    if group_by == "defect_type":
        return {
            t.pk: {"label": f"{t.code} · {t.name}", "code": t.code, "severity": t.severity}
            for t in DefectType.objects.filter(pk__in=keys)
        }
    if group_by == "station":
        return {s.pk: {"label": s.name} for s in InspectionStation.objects.filter(pk__in=keys)}
    if group_by == "machine":
        return {
            m.pk: {"label": m.name, "external_id": m.external_id}
            for m in Machine.objects.filter(pk__in=keys)
        }
    return {
        p.pk: {"label": f"{p.sku} · {p.name}", "sku": p.sku}
        for p in Product.objects.filter(pk__in=keys)
    }


EMPTY_LABEL = {
    "defect_type": UNKNOWN_TYPE_LABEL,
    "station": NO_STATION_LABEL,
    "machine": "Unknown machine",
    "product": NO_PRODUCT_LABEL,
}
FIELD = {
    "defect_type": "effective_type_id",
    "station": "station_id",
    "machine": "machine_id",
    "product": "product_id",
}


def pareto(lines: Sequence[ProductionLine], f: QualityFilters, group_by: str) -> dict[str, Any]:
    results = select_results(lines, f)
    field = FIELD[group_by]
    # order_by(): no sorting while grouping (the default timestamp order would break GROUP BY).
    rows = list(
        counted(results)
        .order_by()
        .values_list(field)
        .annotate(n=Count("id"))
        .values_list(field, "n")
    )
    labels = _labels(group_by, {key for key, _ in rows})
    total = sum(n for _, n in rows)
    groups = []
    for key, n in rows:
        extra = labels.get(key, {"label": EMPTY_LABEL[group_by]})
        groups.append(
            {
                "key": f"{group_by}:{key}" if key is not None else f"{group_by}:none",
                "id": key,
                **extra,
                "count": n,
            }
        )
    groups.sort(key=lambda g: (-g["count"], g["label"]))
    cumulative = 0
    for group in groups:
        cumulative += group["count"]
        group["share"] = rate(group["count"], total)
        group["cumulative_share"] = rate(cumulative, total)
    if groups:
        groups[-1]["cumulative_share"] = 1.0
    return {
        "group_by": group_by,
        "total": total,
        "false_rejects_excluded": results.filter(
            current_review__verdict=Verdict.FALSE_REJECT
        ).count(),
        "groups": groups,
    }


# --- Trend ----------------------------------------------------------------------------


TREND_GROUP_BY = ("hour", "shift", "day")


def trend_buckets(factory: Factory, start: datetime, end: datetime, group_by: str) -> list[Any]:
    """Trend buckets in the factory's timezone (hours, days) or its shift occurrences."""
    zone = ZoneInfo(factory.timezone)
    if group_by == "hour":
        return hour_buckets(start, end, zone)
    if group_by == "day":
        return day_buckets(start, end, zone)
    return shift_buckets(start, end, shift_periods(factory, start, end))


def trend(
    lines: Sequence[ProductionLine], f: QualityFilters, buckets: Sequence[Any]
) -> dict[str, Any]:
    """Defects and line total count per bucket; the total row comes from the sums."""
    edges = [(b.start, b.end) for b in buckets]
    totals = line_totals(lines, f, edges)
    times = sorted(counted(select_results(lines, f)).values_list("timestamp", flat=True))
    defects = [0] * len(edges)
    cursor = 0
    for index, (start, end) in enumerate(edges):
        while cursor < len(times) and times[cursor] < start:
            cursor += 1
        while cursor < len(times) and times[cursor] < end:
            defects[index] += 1
            cursor += 1
    rows = [
        {
            "start": b.start,
            "end": b.end,
            "label": b.label,
            "defects": n,
            "total_count": counts.total,
            "defect_rate": rate(n, counts.total),
        }
        for b, n, counts in zip(buckets, defects, totals, strict=True)
    ]
    defect_sum = sum(defects)
    count_sum = sum(c.total for c in totals)
    return {
        "buckets": rows,
        "total": {
            "defects": defect_sum,
            "total_count": count_sum,
            "defect_rate": rate(defect_sum, count_sum),
        },
    }
