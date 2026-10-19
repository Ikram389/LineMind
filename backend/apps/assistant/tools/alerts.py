"""Alerts tool: the alerts the user may see (the same scope as the Alerts page)."""

from __future__ import annotations

from typing import Any

from apps.assistant.tools.core import (
    ChoiceParam,
    InstantParam,
    IntParam,
    Source,
    Tool,
    ToolContext,
    ToolResult,
    alert_link,
    check_range,
    local,
    metric,
)
from apps.notifications.models import Alert, AlertStatus
from apps.notifications.services.messages import render_message
from apps.organizations.tenancy import scope_to_user

MAX_ROWS = 10


class GetAlerts(Tool):
    name = "get_alerts"
    description = (
        "Alerts (open, unresolved, resolved or all), optionally for one line and for alerts "
        "opened in a range. Newest first."
    )
    params = (
        IntParam("line_id", "Optional line id.", required=False),
        ChoiceParam(
            "status",
            "unresolved = open or acknowledged.",
            required=False,
            choices=("open", "unresolved", "resolved", "all"),
            default="unresolved",
        ),
        InstantParam("start", "Optional: opened from.", required=False),
        InstantParam("end", "Optional: opened before.", required=False),
    )

    def check(self, args: dict[str, Any]) -> None:
        if "start" in args and "end" in args:
            check_range(args["start"], args["end"])

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        alerts = scope_to_user(
            Alert.objects.select_related("factory", "line", "machine"), ctx.user, "factory"
        )
        if "line_id" in args:
            alerts = alerts.filter(line=ctx.line(args["line_id"]))
        status = args["status"]
        if status == "unresolved":
            alerts = alerts.exclude(status=AlertStatus.RESOLVED)
        elif status != "all":
            alerts = alerts.filter(status=status)
        if "start" in args:
            alerts = alerts.filter(opened_at__gte=args["start"])
        if "end" in args:
            alerts = alerts.filter(opened_at__lt=args["end"])
        alerts = alerts.order_by("-opened_at", "-id")
        total = alerts.count()
        rows = list(alerts[:MAX_ROWS])
        data = {
            "status": status,
            "alert_count": total,
            "alerts": [
                {
                    "alert_id": a.pk,
                    "severity": a.severity,
                    "status": a.status,
                    "message": render_message(a.message_key, a.message_values),
                    "line": a.line.name if a.line else None,
                    "machine": a.machine.name if a.machine else None,
                    "opened_at": local(a.opened_at, a.factory.timezone),
                    "problem_since": local(a.condition_since, a.factory.timezone),
                }
                for a in rows
            ],
        }
        sources = [
            Source("alert", a.pk, f"Alert #{a.pk} · {a.severity}", alert_link(a.pk))
            for a in rows[:5]
        ]
        warnings = [] if total else ["No alerts match."]
        return ToolResult(
            data, sources=sources, warnings=warnings, key_metrics=[metric("Alerts", total)]
        )
