"""The shared interface of rule types, and what they get to work with.

A rule type (an "evaluator") answers one question: for this rule, right now, which
subjects is the condition true for? It returns `Finding`s. The engine
(services/engine.py) turns findings into alerts: it opens, keeps and resolves them,
applies cooldowns and the database deduplication. Evaluators never touch alerts.

Numbers always come from the existing services (downtime, OEE, quality metrics);
evaluators only compare them with the rule's thresholds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from rest_framework import serializers

from apps.notifications.models import AlertRule
from apps.organizations.models import Factory, Machine, ProductionLine
from apps.production.event_types import MachineState
from apps.production.models import MachineStateEvent
from apps.production.services.shifts import ShiftPeriod, current_shift

# What can trigger an event-driven evaluation (after the matching work has committed).
INGESTION = "ingestion"  # any event stored for the line
DOWNTIME = "downtime"  # state events stored: downtime/incidents were re-derived
QUALITY = "quality"  # defects stored or a quality review saved
CLASSIFICATION = "classification"  # a stop was classified


@dataclass(frozen=True)
class Subject:
    type: str  # "incident", "downtime_event", "machine", "line", "station"
    id: int | None
    key: str  # unique per rule, e.g. "incident:14", "line:1:shift:3:2026-10-14"


@dataclass(frozen=True)
class Finding:
    """The condition is true, now, for this subject."""

    subject: Subject
    line_id: int | None
    machine_id: int | None
    since: datetime  # when the problem itself began
    message_key: str
    values: dict[str, Any] = field(default_factory=dict)


class EvaluationContext:
    """The moment of evaluation, with small caches shared by all rules of one run."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self._shifts: dict[int, ShiftPeriod | None] = {}
        self._states: dict[int, str | None] = {}

    def lines(self, rule: AlertRule) -> list[ProductionLine]:
        if rule.line_id is not None:
            return [rule.line]
        return list(
            ProductionLine.objects.filter(factory_id=rule.factory_id).select_related("factory")
        )

    def machines(self, rule: AlertRule, line: ProductionLine) -> list[Machine]:
        if rule.machine_id is not None:
            return [rule.machine] if rule.machine.line_id == line.pk else []
        return list(line.machines.order_by("position"))

    def shift(self, factory: Factory) -> ShiftPeriod | None:
        if factory.pk not in self._shifts:
            self._shifts[factory.pk] = current_shift(factory, self.now)
        return self._shifts[factory.pk]

    def machine_state(self, machine_id: int) -> str | None:
        """The latest reported state (at or before now)."""
        if machine_id not in self._states:
            self._states[machine_id] = (
                MachineStateEvent.objects.filter(machine_id=machine_id, timestamp__lte=self.now)
                .order_by("-timestamp", "-event_id")
                .values_list("state", flat=True)
                .first()
            )
        return self._states[machine_id]


class RuleEvaluator(ABC):
    rule_type: ClassVar[str]
    parameters: ClassVar[type[serializers.Serializer]]
    triggers: ClassVar[frozenset[str]]  # event-driven evaluation after these
    time_driven: ClassVar[bool] = True  # also evaluated every 30 seconds
    machine_scoped: ClassVar[bool] = True  # may a rule be narrowed to one machine?

    @abstractmethod
    def findings(self, rule: AlertRule, ctx: EvaluationContext) -> list[Finding]:
        """Every subject the condition is true for, now."""

    def params(self, rule: AlertRule) -> dict[str, Any]:
        """The rule's parameters with defaults filled in (validated on save)."""
        serializer = self.parameters(data=rule.parameters or {}, context={"factory": rule.factory})
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)

    def suppressed(self, rule: AlertRule, finding: Finding, ctx: EvaluationContext) -> bool:
        """No *new* alert outside shifts, during breaks or during a planned stop.

        Open alerts are not affected: they still resolve when the condition clears.
        """
        if rule.active_outside_shifts:
            return False
        period = ctx.shift(rule.factory)
        if period is None:
            return True
        if any(start <= ctx.now < end for start, end in period.breaks):
            return True
        if finding.machine_id is not None:
            return ctx.machine_state(finding.machine_id) == MachineState.PLANNED_STOP
        if finding.line_id is not None:
            machine_ids = ProductionLine.objects.get(pk=finding.line_id).machines.values_list(
                "pk", flat=True
            )
            return any(ctx.machine_state(m) == MachineState.PLANNED_STOP for m in machine_ids)
        return False
