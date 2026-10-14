from collections.abc import Callable
from datetime import datetime, time
from typing import Any

import pytest

from apps.notifications.models import AlertRule, Severity
from apps.notifications.services.engine import EvaluationResult, enabled_rules, evaluate_rules
from apps.organizations.models import Role
from apps.production.models import Shift, ShiftBreak
from tests.helpers import World
from tests.lines import Bottling


@pytest.fixture
def day_shift(bottling: Bottling) -> Shift:
    """06:00-14:00 UTC every day, break 10:00-10:30. No gaps in sparse test data."""
    factory = bottling.line.factory
    factory.stale_after_seconds = 24 * 3600
    factory.save()
    shift = Shift.objects.create(factory=factory, name="Day", start_time=time(6), end_time=time(14))
    ShiftBreak.objects.create(shift=shift, name="Break", start_time=time(10), end_time=time(10, 30))
    return shift


@pytest.fixture
def make_rule(bottling: Bottling) -> Callable[..., AlertRule]:
    def _make(rule_type: str, parameters: dict[str, Any] | None = None, **fields: Any) -> AlertRule:
        defaults: dict[str, Any] = {
            "factory": bottling.line.factory,
            "line": bottling.line,
            "rule_type": rule_type,
            "parameters": parameters or {},
            "severity": Severity.WARNING,
            "recipient_roles": [Role.PRODUCTION_SUPERVISOR],
            "escalate_after_minutes": None,
            "cooldown_minutes": 30,
        }
        defaults.update(fields)
        return AlertRule.objects.create(**defaults)

    return _make


@pytest.fixture
def evaluate(world: World) -> Callable[[datetime], EvaluationResult]:
    """evaluate(now): every enabled rule, as the periodic task does."""
    return lambda now: evaluate_rules(enabled_rules(), now)
