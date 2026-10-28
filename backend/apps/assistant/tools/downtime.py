"""Downtime tools: summary and Pareto (line or machine view), recurring stops, incidents.

All numbers come from apps/downtime/services/analysis.py (the step 8 functions behind the
Downtime page) and the incident serializers. Wording: "first observed stop".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Prefetch, Q

from apps.assistant.tools.core import (
    END,
    LINE,
    RANGE_ID,
    START,
    ArgumentError,
    ChoiceParam,
    IntParam,
    RangeSlot,
    Source,
    Tool,
    ToolContext,
    ToolResult,
    downtime_link,
    incident_link,
    local,
    metric,
    minutes,
    pct,
    range_label,
    untrusted,
)
from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.downtime.serializers import IncidentDetailSerializer, IncidentSerializer
from apps.downtime.services.analysis import (
    EVENT_SELECT,
    LINE_VIEW,
    MACHINE_VIEW,
    AnalysisFilters,
    pareto,
    recurring,
    select_entries,
    summary,
)
from apps.downtime.services.durations import duration_seconds
from apps.organizations.models import ProductionLine
from apps.organizations.tenancy import scope_to_user

MAX_GROUPS = 8
MAX_ROWS = 10
REPORTS = ("summary", "by_machine", "by_reason", "by_category", "by_alarm")
GROUP_OF = {
    "by_machine": "machine",
    "by_reason": "reason",
    "by_category": "category",
    "by_alarm": "alarm_code",
}
LOSS_NOTE = "Lost bottles are estimates: stop duration x nominal speed."
VIEW = ChoiceParam(
    "view",
    "line (default): each line stop once, attributed to its first observed stop. machine: "
    "every machine's own downtime, including blocked and starved time (larger totals).",
    required=False,
    choices=(LINE_VIEW, MACHINE_VIEW),
    default=LINE_VIEW,
)


def _future_warning(end: datetime, now: datetime) -> list[str]:
    return ["The range reaches into the future: counted until now."] if end > now else []


def _estimate(loss: dict[str, Any]) -> dict[str, Any]:
    return {"bottles": loss["units"], "is_estimate": True}


class GetDowntime(Tool):
    name = "get_downtime"
    description = (
        "Downtime of a line in a range: summary (total minutes, stops, longest stop, "
        "unclassified stops) or a Pareto by machine, reason, category or alarm."
    )
    ranges = (RangeSlot(),)
    params = (
        LINE,
        RANGE_ID,
        START,
        END,
        ChoiceParam(
            "report", "What to return.", required=False, choices=REPORTS, default="summary"
        ),
        VIEW,
        IntParam("machine_id", "Optional: only this machine.", required=False),
    )

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        machine = ctx.machine(line, args["machine_id"]) if "machine_id" in args else None
        start, end, view = args["start"], args["end"], args["view"]
        zone = line.factory.timezone
        f = AnalysisFilters(
            start=start, end=end, now=ctx.now, view=view, machine_id=machine.pk if machine else None
        )
        entries = select_entries([line], f)
        link = downtime_link(line.pk, start, min(end, ctx.now), view=view, machine=f.machine_id)
        label = f"Downtime · {line.name}" + (f" · {machine.name}" if machine else "")
        sources = [Source("downtime", None, label, link)]
        warnings = _future_warning(end, ctx.now)
        data: dict[str, Any] = {
            "line": line.name,
            "range": range_label(start, min(end, ctx.now), zone),
            "view": view,
        }

        if args["report"] == "summary":
            s = summary(entries, view)
            longest = s["longest"]
            data.update(
                {
                    "view_note": s["view_note"],
                    "total_downtime_minutes": minutes(s["total_seconds"]),
                    "stops": s["stops"],
                    "unclassified_stops": s["unclassified"],
                    "secondary_breakdowns": s["secondary_breakdowns"],
                    "estimated_lost_bottles": _estimate(s["estimated_lost_units"]),
                    "longest_stop": (
                        {
                            "machine": longest["machine"]["name"],
                            "started_at": local(longest["started_at"], zone),
                            "duration_minutes": minutes(longest["duration_seconds"]),
                            "category": longest["category"],
                            "reason": untrusted(longest["reason"]["name"])
                            if longest["reason"]
                            else None,
                            "incident_id": longest["incident"],
                        }
                        if longest
                        else None
                    ),
                }
            )
            if longest and longest["incident"]:
                sources.append(
                    Source(
                        "incident",
                        longest["incident"],
                        f"Longest line stop #{longest['incident']}",
                        incident_link(line.pk, longest["incident"], start, min(end, ctx.now)),
                    )
                )
            key = [
                metric("Downtime", data["total_downtime_minutes"], "min"),
                metric("Stops", data["stops"]),
            ]
            if not entries:
                warnings.append("No downtime in this range.")
        else:
            group_by = GROUP_OF[args["report"]]
            p = pareto(entries, group_by, view)
            groups = [
                {
                    "label": untrusted(g["label"]) if group_by == "reason" else g["label"],
                    "downtime_minutes": minutes(g["total_seconds"]),
                    "stops": g["occurrences"],
                    "share_percent": pct(g["share"]),
                    "estimated_lost_bottles": _estimate(g["estimated_lost_units"]),
                }
                for g in p["groups"][:MAX_GROUPS]
            ]
            data.update(
                {
                    "view_note": p["view_note"],
                    "total_downtime_minutes": minutes(p["total_seconds"]),
                    "total_stops": p["total_occurrences"],
                    "groups": groups,
                }
            )
            if len(p["groups"]) > MAX_GROUPS:
                data["more_groups"] = len(p["groups"]) - MAX_GROUPS
            key = [metric("Downtime", data["total_downtime_minutes"], "min")]
            if groups:
                top = groups[0]
                key.append(metric(f"Top: {top['label']}", top["downtime_minutes"], "min"))
            else:
                warnings.append("No downtime in this range.")
        warnings.append(LOSS_NOTE)
        return ToolResult(data, sources=sources, warnings=warnings, key_metrics=key)


class GetRecurringStops(Tool):
    name = "get_recurring_stops"
    description = (
        "Breakdowns that repeat on the same machine for the same reason or alarm, in a range "
        "(at least the factory's threshold, usually 3)."
    )
    ranges = (RangeSlot(),)
    params = (LINE, RANGE_ID, START, END)

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        line = ctx.line(args["line_id"])
        start, end = args["start"], args["end"]
        zone = line.factory.timezone
        f = AnalysisFilters(start=start, end=end, now=ctx.now, view=MACHINE_VIEW)
        result = recurring([line], f)
        shown = min(end, ctx.now)
        items, sources = [], []
        for item in result["items"][:MAX_ROWS]:
            reason = item["reason"]
            items.append(
                {
                    "machine": item["machine"]["name"],
                    "machine_id": item["machine"]["id"],
                    "reason": untrusted(reason["name"]) if reason else None,
                    "reason_code": reason["code"] if reason else None,
                    "alarm_code": item["alarm_code"],
                    "stops": item["count"],
                    "downtime_minutes": minutes(item["total_seconds"]),
                    "first_occurrence": local(item["first_occurrence"], zone),
                    "last_occurrence": local(item["last_occurrence"], zone),
                }
            )
            filters = {"reason": reason["code"]} if reason else {"alarm": item["alarm_code"]}
            sources.append(
                Source(
                    "downtime",
                    None,
                    f"{item['machine']['name']} · {filters.get('reason') or filters.get('alarm')}",
                    downtime_link(
                        line.pk,
                        start,
                        shown,
                        view=MACHINE_VIEW,
                        machine=item["machine"]["id"],
                        **filters,
                    ),
                )
            )
        data = {
            "line": line.name,
            "range": range_label(start, shown, zone),
            "threshold": result["threshold"],
            "recurring": items,
        }
        warnings = [] if items else ["No recurring breakdowns in this range."]
        key = [metric(f"{i['machine']} repeats", i["stops"]) for i in items[:3]]
        return ToolResult(data, sources=sources, warnings=warnings, key_metrics=key)


class GetIncidents(Tool):
    name = "get_incidents"
    description = (
        "Line stops (incidents) in a range, longest or latest first, or one incident in "
        "detail with incident_id: first observed stop, affected machines, reasons."
    )
    params = (
        IntParam("line_id", "The line id (needed for a list).", required=False),
        RANGE_ID,
        START,
        END,
        IntParam("incident_id", "Optional: one incident in detail.", required=False),
        ChoiceParam(
            "sort", "For a list.", required=False, choices=("longest", "latest"), default="longest"
        ),
    )

    ranges = (RangeSlot(),)

    def range_required(self, args: dict[str, Any], slot: RangeSlot) -> bool:
        return "incident_id" not in args  # a list needs a range, one incident does not

    def check(self, args: dict[str, Any]) -> None:
        if "incident_id" not in args and "line_id" not in args:
            raise ArgumentError("Give incident_id, or line_id with a range_id.")
        super().check(args)

    def _queryset(self, ctx: ToolContext) -> Any:
        return scope_to_user(
            LineStopIncident.objects.select_related(
                "line__factory", "first_machine"
            ).prefetch_related(
                Prefetch("events", queryset=DowntimeEvent.objects.select_related(*EVENT_SELECT))
            ),
            ctx.user,
            "line__factory",
        )

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if "incident_id" in args:
            incident = self._queryset(ctx).filter(pk=args["incident_id"]).first()
            if incident is None:
                return ToolResult(
                    {
                        "error": "not_found",
                        "message": f"No incident {args['incident_id']} is available to you.",
                    },
                    error="not_found",
                )
            return self._detail(ctx, incident)
        line = ctx.line(args["line_id"])
        return self._list(ctx, line, args["start"], args["end"], args["sort"])

    def _summary(self, ctx: ToolContext, incident: LineStopIncident) -> dict[str, Any]:
        zone = incident.line.factory.timezone
        body = IncidentSerializer(incident, context={"now": ctx.now}).data
        first = body["first_observed_stop"]
        firsts = [e for e in incident.events.all() if e.is_first_stop]
        return {
            "incident_id": incident.pk,
            "started_at": local(incident.started_at, zone),
            "ended_at": local(incident.ended_at, zone) if incident.ended_at else "ongoing",
            "duration_minutes": minutes(body["duration_seconds"]),
            "origin": incident.origin,
            "first_observed_stop": first["machine"]["name"] if first["machine"] else None,
            "simultaneous_first_stops": [m["name"] for m in first["simultaneous"]],
            "alarm_code": firsts[0].alarm_code if firsts else None,
            "machines_affected": body["event_count"],
            "estimated_lost_bottles": {
                "bottles": body["estimated_loss"]["units"],
                "is_estimate": True,
            },
        }

    def _source(self, ctx: ToolContext, incident: LineStopIncident) -> Source:
        end = incident.ended_at or ctx.now
        zone = incident.line.factory.timezone
        return Source(
            "incident",
            incident.pk,
            f"Line stop #{incident.pk} · {local(incident.started_at, zone)}",
            incident_link(incident.line_id, incident.pk, incident.started_at, end),
        )

    def _list(
        self, ctx: ToolContext, line: ProductionLine, start: datetime, end: datetime, sort: str
    ) -> ToolResult:
        incidents = list(
            self._queryset(ctx)
            .filter(line=line, started_at__lt=end)
            .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))
            .order_by("-started_at")[:500]
        )
        if sort == "longest":
            incidents.sort(key=lambda i: -duration_seconds(i.started_at, i.ended_at, ctx.now))
        shown = incidents[:MAX_ROWS]
        data = {
            "line": line.name,
            "range": range_label(start, min(end, ctx.now), line.factory.timezone),
            "incident_count": len(incidents),
            "sorted_by": sort,
            "incidents": [self._summary(ctx, i) for i in shown],
        }
        warnings = ["Lost bottles are estimates: duration x line nominal speed."]
        if not incidents:
            warnings = ["No line stops in this range."]
        key = [metric("Line stops", len(incidents))]
        if shown:
            key.append(
                metric(f"#{shown[0].pk} duration", data["incidents"][0]["duration_minutes"], "min")
            )
        return ToolResult(
            data,
            sources=[self._source(ctx, i) for i in shown[:5]],
            warnings=warnings,
            key_metrics=key,
        )

    def _detail(self, ctx: ToolContext, incident: LineStopIncident) -> ToolResult:
        detail = IncidentDetailSerializer(
            incident, context={"now": ctx.now, "range": (None, None)}
        ).data
        data = self._summary(ctx, incident)
        data["line"] = incident.line.name
        data["machines"] = [
            {
                "machine": e["machine"]["name"],
                "category": e["category"],
                "role": e["role_in_incident"],
                "seconds_after_first_stop": e["delay_seconds"],
                "duration_minutes": minutes(e["duration_seconds"]),
                "alarm_code": e["alarm_code"],
                "reason": untrusted(e["classification"]["reason"]["name"])
                if e["classification"]
                else None,
                "comment": untrusted(e["classification"]["comment"])
                if e["classification"]
                else None,
            }
            for e in detail["events"][:12]
        ]
        warnings = [
            "The first observed stop is the first machine seen stopping, not a proven cause.",
            "Lost bottles are estimates: duration x line nominal speed.",
        ]
        key = [metric("Duration", data["duration_minutes"], "min")]
        return ToolResult(
            data, sources=[self._source(ctx, incident)], warnings=warnings, key_metrics=key
        )
