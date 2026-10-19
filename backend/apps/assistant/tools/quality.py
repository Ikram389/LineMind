"""Quality tool: summary, Pareto and trend, from apps/quality/services/metrics.py."""

from __future__ import annotations

from typing import Any

from apps.assistant.tools.core import (
    END,
    LINE,
    START,
    ChoiceParam,
    Source,
    TextParam,
    Tool,
    ToolContext,
    ToolResult,
    metric,
    pct,
    quality_link,
    range_label,
)
from apps.quality.services.metrics import (
    TREND_GROUP_BY,
    QualityFilters,
    pareto,
    summary,
    trend,
    trend_buckets,
)

REPORTS = ("summary", "by_defect_type", "by_station", "by_machine", "by_product", "trend")
MAX_GROUPS = 8
MAX_BUCKETS = 24


class GetQuality(Tool):
    name = "get_quality"
    description = (
        "Defects of a line in a range: summary (defects, defect rate, unreviewed), a Pareto "
        "by defect type, station, machine or product, or a trend by hour, shift or day."
    )
    params = (
        LINE,
        START,
        END,
        ChoiceParam(
            "report", "What to return.", required=False, choices=REPORTS, default="summary"
        ),
        ChoiceParam(
            "trend_by", "For report=trend.", required=False, choices=TREND_GROUP_BY, default="hour"
        ),
        TextParam(
            "defect_type", "Optional defect type code, e.g. Q03.", required=False, max_length=20
        ),
    )

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        start, end = args["start"], args["end"]
        code = args.get("defect_type")
        f = QualityFilters(start=start, end=end, defect_type=code)
        shown = min(end, ctx.now)
        data: dict[str, Any] = {
            "line": line.name,
            "range": range_label(start, shown, line.factory.timezone),
            "defect_type": code,
        }
        source = Source(
            "quality",
            None,
            f"Quality · {line.name}" + (f" · {code}" if code else ""),
            quality_link(line.pk, start, shown, defect_type=code),
        )
        warnings: list[str] = []
        report = args["report"]

        if report == "summary":
            s = summary([line], f)
            data.update(
                {
                    "defects": s["defects"],
                    "defect_rate_percent": pct(s["defect_rate"], 2),
                    "bottles_inspected_on_line": s["line_total_count"],
                    "unreviewed_results": s["unreviewed"],
                    "false_rejects": s["false_rejects"],
                    "defects_by_severity": s["defects_by_severity"],
                    "stations": [
                        {
                            "station": st["station"]["name"],
                            "inspected": st["inspected"],
                            "defects": st["defects"],
                            "defect_rate_percent": pct(st["defect_rate"], 2),
                        }
                        for st in s["inspected_by_station"][:6]
                    ],
                }
            )
            warnings += s["warnings"][:5]
            key = [
                metric("Defects", data["defects"]),
                metric("Defect rate", data["defect_rate_percent"], "%"),
                metric("Not reviewed", data["unreviewed_results"]),
            ]
        elif report == "trend":
            buckets = trend_buckets(line.factory, start, shown, args["trend_by"])
            t = trend([line], f, buckets)
            rows = t["buckets"]
            data["by_" + args["trend_by"]] = [
                {
                    "label": b["label"],
                    "defects": b["defects"],
                    "bottles": b["total_count"],
                    "defect_rate_percent": pct(b["defect_rate"], 2),
                }
                for b in rows[-MAX_BUCKETS:]
            ]
            if len(rows) > MAX_BUCKETS:
                data["truncated"] = f"Only the last {MAX_BUCKETS} of {len(rows)} groups."
            data["total"] = {
                "defects": t["total"]["defects"],
                "bottles": t["total"]["total_count"],
                "defect_rate_percent": pct(t["total"]["defect_rate"], 2),
            }
            key = [
                metric("Defects", data["total"]["defects"]),
                metric("Defect rate", data["total"]["defect_rate_percent"], "%"),
            ]
        else:
            group_by = report.removeprefix("by_")
            p = pareto([line], f, group_by)
            data.update(
                {
                    "total_defects": p["total"],
                    "false_rejects_excluded": p["false_rejects_excluded"],
                    "groups": [
                        {
                            "label": g["label"],
                            **({"code": g["code"]} if "code" in g else {}),
                            "defects": g["count"],
                            "share_percent": pct(g["share"]),
                        }
                        for g in p["groups"][:MAX_GROUPS]
                    ],
                }
            )
            key = [metric("Defects", p["total"])]
            if data["groups"]:
                top = data["groups"][0]
                key.append(metric(f"Top: {top['label']}", top["defects"]))
        if end > ctx.now:
            warnings.append("The range reaches into the future: counted until now.")
        return ToolResult(data, sources=[source], warnings=warnings, key_metrics=key)
