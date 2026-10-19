"""Maintenance tool: actions the user may see, and one action's before/after effectiveness
(apps/maintenance/services/effectiveness.py: an observation, never proof)."""

from __future__ import annotations

from typing import Any

from apps.assistant.tools.core import (
    ChoiceParam,
    IntParam,
    Source,
    Tool,
    ToolContext,
    ToolResult,
    action_link,
    local,
    metric,
    minutes,
    range_label,
    untrusted,
)
from apps.maintenance.models import OPEN_STATUSES, MaintenanceAction
from apps.maintenance.services.effectiveness import effectiveness
from apps.organizations.tenancy import scope_to_user

MAX_ROWS = 10
STATUSES = ("open", "done", "verified", "cancelled", "all")


def _window(window: dict[str, Any] | None, zone: str) -> dict[str, Any] | None:
    if window is None:
        return None
    return {
        "range": range_label(window["start"], window["end"], zone),
        "stops": window["occurrences"],
        "downtime_minutes": minutes(window["downtime_seconds"]),
        "run_hours": window["run_hours"],
        "stops_per_10_run_hours": window["occurrences_per_10h"],
        "downtime_minutes_per_10_run_hours": window["downtime_minutes_per_10h"],
    }


class GetMaintenance(Tool):
    name = "get_maintenance"
    description = (
        "Maintenance actions (open, done, verified, cancelled or all), optionally for one "
        "line; or one action with action_id, including its before/after effectiveness."
    )
    params = (
        IntParam("line_id", "Optional line id.", required=False),
        ChoiceParam("status", "Which actions.", required=False, choices=STATUSES, default="open"),
        IntParam("action_id", "Optional: one action in detail.", required=False),
    )

    def _actions(self, ctx: ToolContext) -> Any:
        return scope_to_user(
            MaintenanceAction.objects.select_related("factory", "line", "machine", "assignee"),
            ctx.user,
            "factory",
        )

    def _row(self, action: MaintenanceAction) -> dict[str, Any]:
        zone = action.factory.timezone
        return {
            "action_id": action.pk,
            "title": untrusted(action.title),
            "line": action.line.name,
            "machine": action.machine.name,
            "status": action.status,
            "priority": action.priority,
            "due_date": action.due_date.isoformat() if action.due_date else None,
            "completed_at": local(action.completed_at, zone),
            "fixed_at": local(action.fixed_at, zone),
        }

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if "action_id" in args:
            action = self._actions(ctx).filter(pk=args["action_id"]).first()
            if action is None:
                return ToolResult(
                    {
                        "error": "not_found",
                        "message": f"No action {args['action_id']} is available to you.",
                    },
                    error="not_found",
                )
            return self._detail(ctx, action)

        actions = self._actions(ctx)
        if "line_id" in args:
            actions = actions.filter(line=ctx.line(args["line_id"]))
        status = args["status"]
        if status == "open":
            actions = actions.filter(status__in=OPEN_STATUSES)
        elif status != "all":
            actions = actions.filter(status=status)
        actions = actions.order_by("-created_at", "-id")
        total = actions.count()
        rows = list(actions[:MAX_ROWS])
        data = {"status": status, "action_count": total, "actions": [self._row(a) for a in rows]}
        sources = [
            Source("maintenance_action", a.pk, f"Action #{a.pk}", action_link(a.pk))
            for a in rows[:5]
        ]
        warnings = [] if total else ["No maintenance actions match."]
        return ToolResult(
            data, sources=sources, warnings=warnings, key_metrics=[metric("Actions", total)]
        )

    def _detail(self, ctx: ToolContext, action: MaintenanceAction) -> ToolResult:
        zone = action.factory.timezone
        result = effectiveness(action, now=ctx.now)
        data = self._row(action)
        data["problem"] = untrusted(action.problem)
        signature = result.get("signature")
        data["effectiveness"] = {
            "status": result["status"],
            "reason": result.get("reason"),
            "missing_run_hours": result.get("missing_run_hours"),
            "window_days": result["window_days"],
            "recurring_problem": signature,
            "before": _window(result.get("before"), zone),
            "after": _window(result.get("after"), zone),
        }
        warnings = [
            "Effectiveness compares stops per 10 run hours before and after the fix "
            "(±20% margin). It is an observation, not proof that the repair caused the change."
        ]
        key: list[dict[str, Any]] = []
        before, after = data["effectiveness"]["before"], data["effectiveness"]["after"]
        if before:
            key.append(metric("Stops / 10 run h before", before["stops_per_10_run_hours"]))
        if after:
            key.append(metric("Stops / 10 run h after", after["stops_per_10_run_hours"]))
        sources = [
            Source("maintenance_action", action.pk, f"Action #{action.pk}", action_link(action.pk))
        ]
        return ToolResult(data, sources=sources, warnings=warnings, key_metrics=key)
