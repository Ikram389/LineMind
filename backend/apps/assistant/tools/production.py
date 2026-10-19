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
    START,
    ChoiceParam,
    DateParam,
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


def compact_oee(total: dict[str, Any]) -> dict[str, Any]:
    inputs = total["inputs"]
    return {
        "oee_percent": total["oee"]["percent"],
        "availability_percent": total["availability"]["percent"],
        "performance_percent": total["performance"]["percent"],
        "quality_percent": total["quality"]["percent"],
        "data_coverage_percent": total["data_coverage"]["percent"],
        "not_calculable_reason": total["null_reason"],
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


class GetOee(Tool):
    name = "get_oee"
    description = (
        "OEE, availability, performance and quality (%) for a line and range, with good "
        "bottles and downtime. Optional group_by: hour, day or shift."
    )
    params = (
        LINE,
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
            **compact_oee(total),
        }
        if group_by:
            buckets = report["buckets"]
            data["by_" + group_by] = [
                {
                    "label": b["label"],
                    "oee_percent": b["oee"]["percent"],
                    "availability_percent": b["availability"]["percent"],
                    "performance_percent": b["performance"]["percent"],
                    "quality_percent": b["quality"]["percent"],
                }
                for b in buckets[-MAX_BUCKETS:]
            ]
            if len(buckets) > MAX_BUCKETS:
                data["truncated"] = f"Only the last {MAX_BUCKETS} of {len(buckets)} groups."
        warnings = [w["message"] for w in total["warnings"]]
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
        "range. Each changeover gives ready-made before and after ranges for compare_periods."
    )
    params = (LINE, START, END)

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
                    "before_range": {"start": iso(previous.effective_from), "end": iso(at)},
                    "after_range": {"start": iso(at), "end": iso(after_end)}
                    if after_end > at
                    else None,
                }
            )
        if data["changeovers"]:
            data["last_changeover"] = data["changeovers"][-1]
        warnings = [] if orders else ["No production orders in this range."]
        sources = [Source("line", line.pk, f"Orders · {line.name}", overview_link(line.pk))]
        return ToolResult(data, sources=sources, warnings=warnings)
