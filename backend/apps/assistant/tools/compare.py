"""compare_periods: one metric over two ranges, with the difference computed here.

The model never subtracts or divides. Each value comes from the same service as its
screen: the OEE report, the downtime analysis or the quality summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from apps.analytics.services.oee_data import NoCountingMachineError
from apps.analytics.services.report import oee_report
from apps.assistant.tools.core import (
    LINE,
    ChoiceParam,
    IntParam,
    RangeParam,
    RangeSlot,
    Source,
    TextParam,
    Tool,
    ToolContext,
    ToolResult,
    check_range,
    downtime_link,
    metric,
    minutes,
    overview_link,
    pct,
    quality_link,
    range_label,
)
from apps.downtime.services.analysis import (
    LINE_VIEW,
    MACHINE_VIEW,
    AnalysisFilters,
    select_entries,
    summary,
)
from apps.organizations.models import Machine, ProductionLine
from apps.quality.services.metrics import QualityFilters
from apps.quality.services.metrics import summary as quality_summary

METRICS = {
    "oee": "%",
    "availability": "%",
    "performance": "%",
    "quality": "%",
    "downtime_minutes": "min",
    "stop_count": "stops",
    "defect_count": "defects",
    "defect_rate": "%",
}


@dataclass
class Measured:
    value: float | None
    warnings: list[str]
    source: Source


def _round(value: Decimal, digits: int) -> float:
    return float(value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def difference(a: float | None, b: float | None) -> dict[str, Any]:
    """b − a and the relative change, exactly (Decimal), rounded at the end."""
    if a is None or b is None:
        return {"difference": None, "change_percent": None, "direction": "unknown"}
    da, db = Decimal(str(a)), Decimal(str(b))
    diff = db - da
    change = None if da == 0 else _round(diff / da * 100, 1)
    direction = "higher" if diff > 0 else "lower" if diff < 0 else "unchanged"
    return {"difference": _round(diff, 2), "change_percent": change, "direction": direction}


def measure(
    metric_name: str,
    line: ProductionLine,
    machine: Machine | None,
    defect_type: str | None,
    start: datetime,
    end: datetime,
    now: datetime,
) -> Measured:
    shown = min(end, now)
    if metric_name in ("oee", "availability", "performance", "quality"):
        try:
            total = oee_report(line, start, end, None, now)["total"]
        except NoCountingMachineError as exc:
            return Measured(
                None, [str(exc)], Source("line", line.pk, line.name, overview_link(line.pk))
            )
        return Measured(
            total[metric_name]["percent"],
            [w["message"] for w in total["warnings"]],
            Source("line", line.pk, f"OEE · {line.name}", overview_link(line.pk)),
        )
    if metric_name in ("downtime_minutes", "stop_count"):
        if machine is not None:  # the machine's own breakdowns (as in maintenance effectiveness)
            f = AnalysisFilters(
                start=start,
                end=end,
                now=now,
                view=MACHINE_VIEW,
                machine_id=machine.pk,
                categories=frozenset({"breakdown"}),
            )
        else:
            f = AnalysisFilters(start=start, end=end, now=now, view=LINE_VIEW)
        s = summary(select_entries([line], f), f.view)
        value = minutes(s["total_seconds"]) if metric_name == "downtime_minutes" else s["stops"]
        link = downtime_link(
            line.pk, start, shown, view=f.view, machine=machine.pk if machine else None
        )
        return Measured(value, [], Source("downtime", None, f"Downtime · {line.name}", link))
    q = quality_summary([line], QualityFilters(start=start, end=end, defect_type=defect_type))
    value = q["defects"] if metric_name == "defect_count" else pct(q["defect_rate"], 2)
    link = quality_link(line.pk, start, shown, defect_type=defect_type)
    return Measured(value, [], Source("quality", None, f"Quality · {line.name}", link))


class ComparePeriods(Tool):
    name = "compare_periods"
    description = (
        "Compare one metric between two ranges (A = earlier, B = later). Returns both values "
        "and the difference, computed exactly. Use it for any before/after or this/last "
        "question instead of calculating yourself."
    )
    params = (
        ChoiceParam("metric", "The metric.", choices=tuple(METRICS)),
        LINE,
        TextParam(
            "range_a_id",
            "range_id of the first (earlier) range. Preferred.",
            required=False,
            max_length=40,
        ),
        TextParam(
            "range_b_id",
            "range_id of the second (later) range. Preferred.",
            required=False,
            max_length=40,
        ),
        RangeParam("range_a", "Only if exactly a range returned by LineMind.", required=False),
        RangeParam("range_b", "Only if exactly a range returned by LineMind.", required=False),
        IntParam(
            "machine_id",
            "Optional, for downtime_minutes and stop_count: only this machine's breakdowns.",
            required=False,
        ),
        TextParam(
            "defect_type",
            "Optional, for defect_count and defect_rate: a defect type code, e.g. Q03.",
            required=False,
            max_length=20,
        ),
    )

    ranges = (RangeSlot("range_a_id", "range_a"), RangeSlot("range_b_id", "range_b"))

    def check(self, args: dict[str, Any]) -> None:
        for key in ("range_a", "range_b"):
            if key in args:
                check_range(*args[key])

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        machine = ctx.machine(line, args["machine_id"]) if "machine_id" in args else None
        name, unit, zone = args["metric"], METRICS[args["metric"]], line.factory.timezone
        defect_type = args.get("defect_type")
        sides = {}
        warnings: list[str] = []
        sources: list[Source] = []
        for key in ("range_a", "range_b"):
            start, end = args[key]
            measured = measure(name, line, machine, defect_type, start, end, ctx.now)
            sides[key] = {
                "range": range_label(start, min(end, ctx.now), zone),
                "value": measured.value,
            }
            warnings += [w for w in measured.warnings if w not in warnings]
            sources.append(
                Source(
                    measured.source.type,
                    measured.source.id,
                    f"{measured.source.label} · {key[-1].upper()}",
                    measured.source.link,
                )
            )
            if end > ctx.now:
                warnings.append(
                    f"Range {key[-1].upper()} reaches into the future: counted until now."
                )
        a, b = sides["range_a"]["value"], sides["range_b"]["value"]
        data: dict[str, Any] = {
            "metric": name,
            "unit": unit,
            "line": line.name,
            "a": sides["range_a"],
            "b": sides["range_b"],
            **difference(a, b),
        }
        if machine is not None and name in ("downtime_minutes", "stop_count"):
            data["basis"] = f"Breakdowns of {machine.name} only (machine view)."
        if defect_type:
            data["defect_type"] = defect_type
        if a is None or b is None:
            warnings.append("A value could not be calculated: no comparison is possible.")
        elif data["change_percent"] is None:
            warnings.append("Range A is zero: no percentage change.")
        key = [
            metric(f"{name} A", a, unit),
            metric(f"{name} B", b, unit),
            metric("Difference", data["difference"], unit),
        ]
        return ToolResult(data, sources=sources, warnings=warnings, key_metrics=key)
