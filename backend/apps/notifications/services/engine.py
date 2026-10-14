"""The alert engine: the only code that opens and automatically resolves alerts.

For one rule at one moment:
1. its evaluator lists the findings (subjects the condition is true for);
2. a finding without an unresolved alert opens one, unless it is suppressed (outside
   shifts, breaks, planned stops) or the same rule + subject was resolved less than
   `cooldown_minutes` ago;
3. a finding that already has an unresolved alert only refreshes it (no new alert);
4. an unresolved alert whose subject is no longer a finding resolves (resolution=auto).

Deduplication does not rely on this code alone: the database refuses a second
unresolved alert for the same rule + subject (constraint on Alert), so two workers
evaluating at the same moment still create one alert. Running an evaluation twice
changes nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from apps.notifications.evaluators import EVALUATORS
from apps.notifications.evaluators.base import EvaluationContext, Finding
from apps.notifications.models import Alert, AlertRule, AlertStatus, Resolution
from apps.notifications.services.live import queue_alert_message
from apps.notifications.services.notify import notify_alert_opened

logger = logging.getLogger(__name__)

UNRESOLVED = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)


@dataclass
class EvaluationResult:
    opened: list[Alert] = field(default_factory=list)
    resolved: list[Alert] = field(default_factory=list)
    kept: int = 0
    suppressed: int = 0
    cooling_down: int = 0

    def __iadd__(self, other: EvaluationResult) -> EvaluationResult:
        self.opened += other.opened
        self.resolved += other.resolved
        self.kept += other.kept
        self.suppressed += other.suppressed
        self.cooling_down += other.cooling_down
        return self


def _in_cooldown(rule: AlertRule, key: str, now: datetime) -> bool:
    if not rule.cooldown_minutes:
        return False
    return Alert.objects.filter(
        rule=rule,
        subject_key=key,
        status=AlertStatus.RESOLVED,
        resolved_at__gt=now - timedelta(minutes=rule.cooldown_minutes),
    ).exists()


def _open(rule: AlertRule, finding: Finding, now: datetime) -> Alert | None:
    """Insert the alert; None if another evaluation opened it first (the constraint)."""
    try:
        with transaction.atomic():
            alert = Alert.objects.create(
                rule=rule,
                factory_id=rule.factory_id,
                line_id=finding.line_id,
                machine_id=finding.machine_id,
                subject_type=finding.subject.type,
                subject_id=finding.subject.id,
                subject_key=finding.subject.key,
                severity=rule.severity,
                opened_at=now,
                condition_since=finding.since,
                message_key=finding.message_key,
                message_values=finding.values,
                last_evaluated_at=now,
            )
    except IntegrityError:
        return None
    return alert


def resolve_automatically(alert: Alert, now: datetime) -> bool:
    """Resolve if still unresolved (a conditional update: safe with two workers)."""
    updated = Alert.objects.filter(pk=alert.pk, status__in=UNRESOLVED).update(
        status=AlertStatus.RESOLVED,
        resolution=Resolution.AUTO,
        resolved_at=now,
        last_evaluated_at=now,
    )
    if updated:
        alert.refresh_from_db()
        queue_alert_message("alert_resolved", alert)
    return bool(updated)


def evaluate_rule(rule: AlertRule, ctx: EvaluationContext) -> EvaluationResult:
    result = EvaluationResult()
    evaluator = EVALUATORS[rule.rule_type]
    findings = {f.subject.key: f for f in evaluator.findings(rule, ctx)}
    unresolved = {a.subject_key: a for a in rule.alerts.filter(status__in=UNRESOLVED)}

    for key, finding in findings.items():
        alert = unresolved.get(key)
        if alert is not None:
            Alert.objects.filter(pk=alert.pk).update(
                last_evaluated_at=ctx.now, message_values=finding.values
            )
            result.kept += 1
            continue
        if evaluator.suppressed(rule, finding, ctx):
            result.suppressed += 1
            continue
        if _in_cooldown(rule, key, ctx.now):
            result.cooling_down += 1
            continue
        opened = _open(rule, finding, ctx.now)
        if opened is not None:
            result.opened.append(opened)
            notify_alert_opened(opened)
            queue_alert_message("alert_opened", opened)

    for key, alert in unresolved.items():
        if key not in findings and resolve_automatically(alert, ctx.now):
            result.resolved.append(alert)
    return result


def evaluate_rules(rules: Iterable[AlertRule], now: datetime) -> EvaluationResult:
    """Evaluate each rule in its own transaction: one broken rule never blocks the others."""
    ctx = EvaluationContext(now)
    total = EvaluationResult()
    for rule in rules:
        try:
            with transaction.atomic():
                total += evaluate_rule(rule, ctx)
        except Exception:
            logger.exception("Alert rule %s could not be evaluated.", rule.pk)
    return total


def enabled_rules() -> QuerySet[AlertRule]:
    return AlertRule.objects.filter(is_enabled=True).select_related(
        "factory", "line__factory", "machine"
    )


def rules_for_lines(line_ids: Iterable[int], triggers: Iterable[str]) -> list[AlertRule]:
    """Enabled rules that can be affected by new data on these lines."""
    from apps.organizations.models import ProductionLine

    line_ids = set(line_ids)
    factories = set(
        ProductionLine.objects.filter(pk__in=line_ids).values_list("factory_id", flat=True)
    )
    triggers = set(triggers)
    rules = enabled_rules().filter(
        Q(line_id__in=line_ids) | Q(line__isnull=True, factory_id__in=factories)
    )
    return [r for r in rules if EVALUATORS[r.rule_type].triggers & triggers]
