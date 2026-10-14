"""The six rule types of build step 10a. Each reuses an existing service for its numbers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Max
from rest_framework import serializers

from apps.analytics.services.oee import calculate, compute_inputs, percent
from apps.analytics.services.oee_data import NoCountingMachineError, load_line_data
from apps.downtime.models import DowntimeCategory, DowntimeEvent, LineStopIncident
from apps.downtime.services.analysis import AnalysisFilters, needs_reason_ids, recurring
from apps.notifications.evaluators.base import (
    CLASSIFICATION,
    DOWNTIME,
    INGESTION,
    MAINTENANCE,
    QUALITY,
    EvaluationContext,
    Finding,
    RuleEvaluator,
    Subject,
)
from apps.notifications.models import AlertRule, RuleType
from apps.organizations.models import Machine
from apps.production.models import IngestedEvent
from apps.production.services.counters import line_counts_between, machine_counts_by_bucket
from apps.quality.models import InspectionStation
from apps.quality.services.metrics import QualityFilters, counted, rate, select_results


def _minutes(value: float) -> int:
    return max(1, round(value))


# --- long_stop ---------------------------------------------------------------------------


class LongStopParams(serializers.Serializer):
    minutes = serializers.IntegerField(
        min_value=1,
        max_value=24 * 60,
        required=False,
        allow_null=True,
        default=None,
        help_text="Empty: the factory's escalation threshold.",
    )
    scope = serializers.ChoiceField(choices=["incident", "breakdown"], default="incident")


class LongStop(RuleEvaluator):
    """A line stop (or one machine's breakdown) still going after N minutes."""

    rule_type = RuleType.LONG_STOP
    parameters = LongStopParams
    triggers = frozenset({DOWNTIME})

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        minutes = params["minutes"] or _minutes(rule.factory.escalation_after_seconds / 60)
        cutoff = ctx.now - timedelta(minutes=minutes)
        lines = ctx.lines(rule)
        if params["scope"] == "breakdown":
            events = DowntimeEvent.objects.filter(
                line__in=lines,
                category=DowntimeCategory.BREAKDOWN,
                is_obsolete=False,
                ended_at__isnull=True,
                started_at__lte=cutoff,
            ).select_related("machine", "line")
            if rule.machine_id:
                events = events.filter(machine_id=rule.machine_id)
            return [
                Finding(
                    Subject("downtime_event", e.pk, f"downtime_event:{e.pk}"),
                    e.line_id,
                    e.machine_id,
                    e.started_at,
                    "alert.long_breakdown",
                    {
                        "machine": e.machine.name,
                        "line": e.line.name,
                        "minutes": minutes,
                        "alarm": e.alarm_code or "",
                        "event_id": e.pk,
                    },
                )
                for e in events
            ]
        incidents = LineStopIncident.objects.filter(
            line__in=lines, ended_at__isnull=True, started_at__lte=cutoff
        ).select_related("line", "first_machine")
        if rule.machine_id:
            incidents = incidents.filter(first_machine_id=rule.machine_id)
        findings = []
        for incident in incidents:
            first = (
                incident.events.filter(is_first_stop=True, is_obsolete=False)
                .order_by("started_at", "machine__position")
                .first()
            )
            machine = incident.first_machine
            findings.append(
                Finding(
                    Subject("incident", incident.pk, f"incident:{incident.pk}"),
                    incident.line_id,
                    machine.pk if machine else None,
                    incident.started_at,
                    "alert.long_stop" if machine else "alert.long_stop_unknown",
                    {
                        "machine": machine.name if machine else "",
                        "line": incident.line.name,
                        "minutes": minutes,
                        "alarm": (first.alarm_code or "") if first else "",
                        "incident_id": incident.pk,
                    },
                )
            )
        return findings


# --- recurring_stop ------------------------------------------------------------------------


class RecurringStopParams(serializers.Serializer):
    count = serializers.IntegerField(
        min_value=2,
        max_value=100,
        required=False,
        allow_null=True,
        default=None,
        help_text="Empty: the factory's recurring-stop threshold.",
    )
    window_hours = serializers.IntegerField(min_value=1, max_value=72, default=8)


class RecurringStop(RuleEvaluator):
    """The same machine breaks down for the same reason (or alarm) N times in a window."""

    rule_type = RuleType.RECURRING_STOP
    parameters = RecurringStopParams
    triggers = frozenset({DOWNTIME, CLASSIFICATION})

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        window = timedelta(hours=params["window_hours"])
        filters = AnalysisFilters(start=ctx.now - window, end=ctx.now, now=ctx.now)
        result = recurring(ctx.lines(rule), filters, threshold=params["count"])
        line_of = dict(
            Machine.objects.filter(
                pk__in=[i["machine"]["id"] for i in result["items"]]
            ).values_list("pk", "line_id")
        )
        findings = []
        for item in result["items"]:
            machine = item["machine"]
            if rule.machine_id and machine["id"] != rule.machine_id:
                continue
            reason = item["reason"]
            findings.append(
                Finding(
                    Subject("machine", machine["id"], f"machine:{machine['id']}:{item['key']}"),
                    line_of.get(machine["id"]),
                    machine["id"],
                    item["first_occurrence"],
                    "alert.recurring_stop" if reason else "alert.recurring_stop_alarm",
                    {
                        "machine": machine["name"],
                        "count": item["count"],
                        "hours": params["window_hours"],
                        "reason": reason["name"] if reason else "",
                        "alarm": item["alarm_code"] or "",
                    },
                )
            )
        return findings


# --- machine_offline ------------------------------------------------------------------------


class MachineOfflineParams(serializers.Serializer):
    minutes = serializers.IntegerField(
        min_value=1,
        max_value=24 * 60,
        required=False,
        allow_null=True,
        default=None,
        help_text="Empty: the factory's stale-data threshold.",
    )


class MachineOffline(RuleEvaluator):
    """No data from a machine for N minutes. A whole silent line gives one line alert.
    Machines that never sent anything are ignored (not installed yet, not "offline")."""

    rule_type = RuleType.MACHINE_OFFLINE
    parameters = MachineOfflineParams
    triggers = frozenset({INGESTION})

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        minutes = params["minutes"] or _minutes(rule.factory.stale_after_seconds / 60)
        cutoff = ctx.now - timedelta(minutes=minutes)
        findings = []
        for line in ctx.lines(rule):
            machines = ctx.machines(rule, line)
            last_seen = dict(
                IngestedEvent.objects.filter(machine__in=machines, timestamp__lte=ctx.now)
                .values_list("machine_id")
                .annotate(last=Max("timestamp"))
                .order_by()
            )
            reporting = [m for m in machines if m.pk in last_seen]
            silent = [m for m in reporting if last_seen[m.pk] < cutoff]
            if not silent:
                continue
            whole_line = (
                rule.machine_id is None and len(reporting) > 1 and len(silent) == len(reporting)
            )
            if whole_line:
                findings.append(
                    Finding(
                        Subject("line", line.pk, f"line:{line.pk}:offline"),
                        line.pk,
                        None,
                        max(last_seen[m.pk] for m in silent),
                        "alert.line_offline",
                        {"line": line.name, "minutes": minutes},
                    )
                )
                continue
            findings.extend(
                Finding(
                    Subject("machine", m.pk, f"machine:{m.pk}:offline"),
                    line.pk,
                    m.pk,
                    last_seen[m.pk],
                    "alert.machine_offline",
                    {"machine": m.name, "line": line.name, "minutes": minutes},
                )
                for m in silent
            )
        return findings


# --- low_oee -----------------------------------------------------------------------------


class LowOeeParams(serializers.Serializer):
    below_percent = serializers.FloatField(min_value=1, max_value=100, default=60)
    min_planned_minutes = serializers.IntegerField(min_value=1, max_value=24 * 60, default=60)


class LowOee(RuleEvaluator):
    """The current shift's OEE so far is below X%, once there is enough planned time."""

    rule_type = RuleType.LOW_OEE
    parameters = LowOeeParams
    triggers = frozenset()
    machine_scoped = False

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        period = ctx.shift(rule.factory)
        if period is None:
            return []  # the shift ended: its alert resolves
        findings = []
        for line in ctx.lines(rule):
            try:
                data, _ = load_line_data(line, period.start, ctx.now, now=ctx.now)
            except NoCountingMachineError:
                continue
            result = calculate(compute_inputs(data, period.start, ctx.now))
            planned = result.inputs.planned_production_seconds
            if planned < params["min_planned_minutes"] * 60 or result.oee.value is None:
                continue  # too early in the shift to judge
            oee = percent(result.oee.value)
            if oee >= params["below_percent"]:
                continue
            findings.append(
                Finding(
                    Subject(
                        "line",
                        line.pk,
                        f"line:{line.pk}:shift:{period.shift_id}:{period.local_date}",
                    ),
                    line.pk,
                    None,
                    period.start,
                    "alert.low_oee",
                    {
                        "line": line.name,
                        "oee": oee,
                        "threshold": params["below_percent"],
                        "shift": period.label,
                    },
                )
            )
        return findings


# --- high_defect_rate ------------------------------------------------------------------------


class HighDefectRateParams(serializers.Serializer):
    above_percent = serializers.FloatField(min_value=0.01, max_value=100, default=2)
    window_minutes = serializers.IntegerField(min_value=5, max_value=24 * 60, default=30)
    min_units = serializers.IntegerField(min_value=1, default=500)
    station = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_station(self, value: int | None) -> int | None:
        factory = self.context.get("factory")
        if (
            value is not None
            and not InspectionStation.objects.filter(pk=value, line__factory=factory).exists()
        ):
            raise serializers.ValidationError("Unknown inspection station for this factory.")
        return value


class HighDefectRate(RuleEvaluator):
    """Defects in the last N minutes above X% of the bottles, with at least K bottles
    (reviews applied: false rejects do not count)."""

    rule_type = RuleType.HIGH_DEFECT_RATE
    parameters = HighDefectRateParams
    triggers = frozenset({QUALITY})
    machine_scoped = False

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        start = ctx.now - timedelta(minutes=params["window_minutes"])
        station = (
            InspectionStation.objects.select_related("machine", "line").get(pk=params["station"])
            if params["station"]
            else None
        )
        findings = []
        for line in ctx.lines(rule):
            if station is not None and station.line_id != line.pk:
                continue
            filters = QualityFilters(
                start=start, end=ctx.now, station_id=station.pk if station else None
            )
            defects = counted(select_results([line], filters)).count()
            if station is not None:
                units = machine_counts_by_bucket(station.machine, [(start, ctx.now)])[0][0]
            else:
                units = line_counts_between(line, start, ctx.now).total
            value = rate(defects, units)
            if (
                units < params["min_units"]
                or value is None
                or value * 100 <= params["above_percent"]
            ):
                continue
            key = f"station:{station.pk}:defects" if station else f"line:{line.pk}:defects"
            findings.append(
                Finding(
                    Subject(
                        "station" if station else "line", station.pk if station else line.pk, key
                    ),
                    line.pk,
                    station.machine_id if station else None,
                    start,
                    "alert.high_defect_rate_station" if station else "alert.high_defect_rate",
                    {
                        "line": line.name,
                        "station": station.name if station else "",
                        "rate": round(value * 100, 2),
                        "threshold": params["above_percent"],
                        "minutes": params["window_minutes"],
                        "defects": defects,
                        "units": units,
                    },
                )
            )
        return findings


# --- unclassified_stops ------------------------------------------------------------------------


class UnclassifiedStopsParams(serializers.Serializer):
    minutes_after_end = serializers.IntegerField(min_value=1, max_value=24 * 60, default=15)


class UnclassifiedStops(RuleEvaluator):
    """A first observed stop or secondary breakdown of the current shift still has no
    reason M minutes after it ended. Consequences (blocked/starved) never need one."""

    rule_type = RuleType.UNCLASSIFIED_STOPS
    parameters = UnclassifiedStopsParams
    triggers = frozenset({DOWNTIME, CLASSIFICATION})

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        params = self.params(rule)
        period = ctx.shift(rule.factory)
        if period is None:
            return []
        cutoff = ctx.now - timedelta(minutes=params["minutes_after_end"])
        lines = ctx.lines(rule)
        ids = needs_reason_ids(lines, period.start, ctx.now, ctx.now)
        events = DowntimeEvent.objects.filter(
            pk__in=ids,
            current_classification__isnull=True,
            ended_at__isnull=False,
            ended_at__lte=cutoff,
            is_obsolete=False,
        ).select_related("machine", "line")
        if rule.machine_id:
            events = events.filter(machine_id=rule.machine_id)
        return [
            Finding(
                Subject("downtime_event", e.pk, f"downtime_event:{e.pk}"),
                e.line_id,
                e.machine_id,
                e.ended_at,
                "alert.unclassified_stop",
                {
                    "machine": e.machine.name,
                    "line": e.line.name,
                    "minutes": params["minutes_after_end"],
                    "event_id": e.pk,
                },
            )
            for e in events
        ]


# --- maintenance_overdue -------------------------------------------------------------------


class MaintenanceOverdueParams(serializers.Serializer):
    pass


class MaintenanceOverdue(RuleEvaluator):
    """A maintenance action still open after the end of its due day (factory time).
    Due dates are calendar dates, so shifts and breaks never suppress it."""

    rule_type = RuleType.MAINTENANCE_OVERDUE
    parameters = MaintenanceOverdueParams
    triggers = frozenset({MAINTENANCE})

    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        from apps.maintenance.models import OPEN_STATUSES, MaintenanceAction

        today = ctx.now.astimezone(ZoneInfo(rule.factory.timezone)).date()
        actions = MaintenanceAction.objects.filter(
            factory_id=rule.factory_id,
            status__in=OPEN_STATUSES,
            due_date__lt=today,
        ).select_related("machine", "line")
        if rule.line_id:
            actions = actions.filter(line_id=rule.line_id)
        if rule.machine_id:
            actions = actions.filter(machine_id=rule.machine_id)
        zone = ZoneInfo(rule.factory.timezone)
        findings = []
        for action in actions:
            deadline = datetime.combine(action.due_date + timedelta(days=1), time(0), tzinfo=zone)
            findings.append(
                Finding(
                    Subject("maintenance_action", action.pk, f"maintenance_action:{action.pk}"),
                    action.line_id,
                    action.machine_id,
                    deadline,
                    "alert.maintenance_overdue",
                    {
                        "action_id": action.pk,
                        "title": action.title,
                        "machine": action.machine.name,
                        "line": action.line.name,
                        "due_date": action.due_date.isoformat(),
                        "days": (today - action.due_date).days,
                    },
                )
            )
        return findings

    def suppressed(self, rule: AlertRule, finding: Finding, ctx: EvaluationContext) -> bool:
        return False


EVALUATORS: dict[str, RuleEvaluator] = {
    evaluator.rule_type: evaluator
    for evaluator in (
        LongStop(),
        RecurringStop(),
        MachineOffline(),
        LowOee(),
        HighDefectRate(),
        UnclassifiedStops(),
        MaintenanceOverdue(),
    )
}


def describe_types() -> list[dict[str, Any]]:
    """Each type's parameters with defaults (drives the rule form)."""
    types = []
    for rule_type, evaluator in EVALUATORS.items():
        fields = []
        for name, field in evaluator.parameters().fields.items():
            fields.append(
                {
                    "name": name,
                    "kind": type(field).__name__.replace("Field", "").lower(),
                    "required": field.required and field.default is serializers.empty,
                    "default": None if field.default is serializers.empty else field.default,
                    "min": getattr(field, "min_value", None),
                    "max": getattr(field, "max_value", None),
                    "choices": list(field.choices) if hasattr(field, "choices") else None,
                    "help": field.help_text or "",
                }
            )
        types.append(
            {
                "type": rule_type,
                "time_driven": evaluator.time_driven,
                "machine_scoped": evaluator.machine_scoped,
                "parameters": fields,
            }
        )
    return types
