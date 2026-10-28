"""Production tools: lines and machines, shifts, live status, OEE, production orders.

Thin wrappers: every number comes from the existing services (line_status, the OEE report,
shifts, orders); these functions only pick fields, round them and add sources.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from apps.analytics.services.oee_data import NoCountingMachineError
from apps.analytics.services.report import TooManyBucketsError, oee_report
from apps.assistant.tools.core import (
    END,
    LINE,
    RANGE_ID,
    START,
    ChoiceParam,
    DateParam,
    RangeSlot,
    Source,
    Tool,
    ToolContext,
    ToolResult,
    downtime_link,
    hours,
    incident_link,
    iso,
    local,
    metric,
    minutes,
    overview_link,
    range_label,
    untrusted,
)
from apps.organizations.models import ProductionLine
from apps.production.services.line_status import get_line_status
from apps.production.services.orders import overlapping_orders
from apps.production.services.shifts import occurrence

MAX_LINES = 20
MAX_BUCKETS = 24
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class ListLines(Tool):
    name = "list_lines"
    description = "The production lines and machines you may see, with their ids."

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        lines = list(ctx.lines().prefetch_related("machines").order_by("factory__name", "name"))
        data = {
            "lines": [
                {
                    "line_id": line.pk,
                    "name": line.name,
                    "factory": line.factory.name,
                    "timezone": line.factory.timezone,
                    "machines": [
                        {"machine_id": m.pk, "code": m.external_id, "name": m.name}
                        for m in sorted(line.machines.all(), key=lambda m: m.position)
                    ],
                }
                for line in lines[:MAX_LINES]
            ],
            "line_count": len(lines),
        }
        sources = [Source("line", line.pk, line.name, overview_link(line.pk)) for line in lines[:5]]
        return ToolResult(data, sources=sources)


class GetShifts(Tool):
    name = "get_shifts"
    description = "The factory's shift definitions (local times) and, for a date, its shifts."
    params = (LINE, DateParam("date", "Optional day, YYYY-MM-DD.", required=False))

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        factory = line.factory
        shifts = list(factory.shifts.filter(is_active=True).prefetch_related("breaks"))
        data: dict[str, Any] = {
            "timezone": factory.timezone,
            "shifts": [
                {
                    "name": s.name,
                    "start": f"{s.start_time:%H:%M}",
                    "end": f"{s.end_time:%H:%M}",
                    "crosses_midnight": s.end_time <= s.start_time,
                    "days": [DAYS[d] for d in sorted(s.days_of_week)],
                }
                for s in shifts
            ],
        }
        if "date" in args:
            day = args["date"]
            tz = ZoneInfo(factory.timezone)
            periods = sorted(
                (occurrence(s, day, tz) for s in shifts if day.weekday() in s.days_of_week),
                key=lambda p: p.start,
            )
            data["on_date"] = [
                {
                    "name": p.shift_name,
                    "start": iso(p.start),
                    "end": iso(p.end),
                    "label": range_label(p.start, p.end, factory.timezone),
                }
                for p in periods
            ]
        return ToolResult(data)


class GetLineStatus(Tool):
    name = "get_line_status"
    description = (
        "The line right now: each machine's state, how long, current alarm, count this "
        "shift, and any ongoing line stop."
    )
    params = (LINE,)

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        status = get_line_status(line, ctx.now)
        zone = line.factory.timezone
        machines = [
            {
                "machine_id": m["id"],
                "name": m["name"],
                "state": m["state"],
                "since": local(m["state_since"], zone),
                "alarm_code": m["alarm_code"],
                "count_this_shift": m["shift_count"],
            }
            for m in status["machines"]
        ]
        states: dict[str, int] = {}
        for m in machines:
            states[m["state"]] = states.get(m["state"], 0) + 1
        data: dict[str, Any] = {
            "line": line.name,
            "time_now": local(ctx.now, zone),
            "machines": machines,
            "machines_by_state": states,
            "machine_count": len(machines),
        }
        sources = [Source("line", line.pk, f"{line.name} (live)", overview_link(line.pk))]
        incident = status["open_incident"]
        if incident:
            first = [m["name"] for m in incident["first_observed_stop"]["machines"]]
            data["ongoing_line_stop"] = {
                "incident_id": incident["incident_id"],
                "since": local(incident["started_at"], zone),
                "first_observed_stop": first,
                "alarm_code": incident["first_observed_stop"]["alarm_code"],
            }
            sources.append(
                Source(
                    "incident",
                    incident["incident_id"],
                    f"Line stop #{incident['incident_id']}",
                    incident_link(
                        line.pk, incident["incident_id"], incident["started_at"], ctx.now
                    ),
                )
            )
        warnings = []
        if states.get("unknown"):
            warnings.append(
                f"{states['unknown']} machine(s) sent no recent data: their state is unknown."
            )
        return ToolResult(data, sources=sources, warnings=warnings)


def percent_or_reason(ratio: dict[str, Any]) -> float | str:
    """A percentage, or "not calculable: <reason>" (never a bare null the model may print)."""
    if ratio.get("percent") is not None:
        return ratio["percent"]
    return f"not calculable: {ratio.get('null_reason') or 'no data'}"


def compact_oee(total: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    inputs = total["inputs"]
    no_data_counted = (settings or {}).get("no_data_handling") != "excluded"
    data = {
        "oee_percent": percent_or_reason(total["oee"]),
        "availability_percent": percent_or_reason(total["availability"]),
        "performance_percent": percent_or_reason(total["performance"]),
        "quality_percent": percent_or_reason(total["quality"]),
        "data_coverage_percent": percent_or_reason(total["data_coverage"]),
        "no_data_minutes": minutes(inputs["no_data_seconds"]),
        "no_data_counted_as_downtime": no_data_counted,
        "good_bottles": inputs["good_count"],
        "total_bottles": inputs["total_count"],
        "rejected_bottles": inputs["rejected_count"],
        "planned_production_minutes": minutes(inputs["planned_production_seconds"]),
        "run_hours": hours(inputs["run_seconds"]),
        "unplanned_downtime_minutes": minutes(inputs["unplanned_downtime_seconds"]),
        "unplanned_downtime_minutes_by_category": {
            k: minutes(v) for k, v in inputs["unplanned_downtime_by_category_seconds"].items()
        },
    }
    if total["null_reason"]:
        data["not_calculable_reason"] = total["null_reason"]
    return data


def no_data_warning(data: dict[str, Any]) -> str | None:
    """Missing machine data is easy to mistake for real stops: say how much there was."""
    minutes_missing = data["no_data_minutes"] or 0
    if not minutes_missing:
        return None
    if data["no_data_counted_as_downtime"]:
        return (
            f"{minutes_missing} min of this time had no data from the machines. This factory "
            "counts it as unplanned downtime, so not all of the downtime is real stops."
        )
    return (
        f"{minutes_missing} min of this time had no data from the machines "
        "(left out of planned time)."
    )


class GetOee(Tool):
    name = "get_oee"
    description = (
        "OEE, availability, performance and quality (%) for a line and range, with good "
        "bottles and downtime. Optional group_by: hour, day or shift."
    )
    ranges = (RangeSlot(),)
    params = (
        LINE,
        RANGE_ID,
        START,
        END,
        ChoiceParam(
            "group_by",
            "Optional breakdown.",
            required=False,
            choices=("none", "hour", "day", "shift"),
        ),
    )

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        start, end = args["start"], args["end"]
        group_by = None if args.get("group_by", "none") == "none" else args["group_by"]
        try:
            report = oee_report(line, start, end, group_by, ctx.now)
        except NoCountingMachineError as exc:
            return ToolResult({"error": "no_data", "message": str(exc)}, error="no_data")
        except TooManyBucketsError:
            return ToolResult(
                {"error": "invalid_range", "message": "Too many groups: use a shorter range."},
                error="invalid_range",
            )
        total = report["total"]
        data: dict[str, Any] = {
            "line": line.name,
            "range": range_label(start, min(end, ctx.now), line.factory.timezone),
            **compact_oee(total, report["settings"]),
        }
        if group_by:
            buckets = report["buckets"]
            data["by_" + group_by] = [
                {
                    "label": b["label"],
                    "oee_percent": percent_or_reason(b["oee"]),
                    "availability_percent": percent_or_reason(b["availability"]),
                    "performance_percent": percent_or_reason(b["performance"]),
                    "quality_percent": percent_or_reason(b["quality"]),
                }
                for b in buckets[-MAX_BUCKETS:]
            ]
            if len(buckets) > MAX_BUCKETS:
                data["truncated"] = f"Only the last {MAX_BUCKETS} of {len(buckets)} groups."
        warnings = [w["message"] for w in total["warnings"]]
        missing = no_data_warning(data)
        if missing:
            warnings.append(missing)
        sources = [
            Source("line", line.pk, f"OEE · {line.name}", overview_link(line.pk)),
            Source(
                "downtime",
                None,
                f"Downtime · {line.name}",
                downtime_link(line.pk, start, min(end, ctx.now)),
            ),
        ]
        key = [
            metric("OEE", data["oee_percent"], "%"),
            metric("Availability", data["availability_percent"], "%"),
            metric("Performance", data["performance_percent"], "%"),
            metric("Quality", data["quality_percent"], "%"),
            metric("Good bottles", data["good_bottles"]),
        ]
        return ToolResult(data, sources=sources, warnings=warnings, key_metrics=key)


class GetProductionOrders(Tool):
    name = "get_production_orders"
    description = (
        "Production orders (which product, when) and the changeovers between products in a "
        "range. Each changeover gives before and after range ids for compare_periods."
    )
    ranges = (RangeSlot(),)
    params = (LINE, RANGE_ID, START, END)

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line: ProductionLine = ctx.line(args["line_id"])
        start, end = args["start"], args["end"]
        zone = line.factory.timezone
        orders = list(
            overlapping_orders(line, start, end)
            .select_related("product")
            .order_by("effective_from")
        )
        data: dict[str, Any] = {
            "orders": [
                {
                    "order_id": o.pk,
                    "product_sku": o.product.sku,
                    "product_name": untrusted(o.product.name),
                    "start": local(o.effective_from, zone),
                    "end": local(o.effective_to, zone),
                    "status": o.status,
                    "planned_quantity": o.planned_quantity,
                }
                for o in orders[:15]
            ],
            "changeovers": [],
        }
        for previous, current in zip(orders, orders[1:], strict=False):
            if previous.product_id == current.product_id:
                continue
            at = current.effective_from
            after_end = min(current.effective_to, ctx.now)
            data["changeovers"].append(
                {
                    "at": local(at, zone),
                    "from_product": previous.product.sku,
                    "to_product": current.product.sku,
                    "before_range_id": ctx.ranges.add(
                        previous.effective_from,
                        at,
                        f"Before the changeover, {range_label(previous.effective_from, at, zone)}",
                    ).range_id,
                    "after_range_id": ctx.ranges.add(
                        at, after_end, f"After the changeover, {range_label(at, after_end, zone)}"
                    ).range_id
                    if after_end > at
                    else None,
                }
            )
        if data["changeovers"]:
            data["last_changeover"] = data["changeovers"][-1]
        warnings = [] if orders else ["No production orders in this range."]
        sources = [Source("line", line.pk, f"Orders · {line.name}", overview_link(line.pk))]
        return ToolResult(data, sources=sources, warnings=warnings)
