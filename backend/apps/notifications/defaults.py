"""Default alert rules for a factory (seed_demo). Existing rules are never changed."""

from typing import Any

from apps.notifications.models import AlertRule, RuleType, Severity
from apps.organizations.models import Factory, Role

OPERATOR, SUPERVISOR = Role.MACHINE_OPERATOR, Role.PRODUCTION_SUPERVISOR
MANAGER, TECHNICIAN, INSPECTOR = (
    Role.FACTORY_MANAGER,
    Role.MAINTENANCE_TECHNICIAN,
    Role.QUALITY_INSPECTOR,
)

# (name, type, parameters, severity, recipients, escalate after minutes, escalation roles)
DEFAULT_RULES: list[tuple[str, str, dict[str, Any], str, list[str], int | None, list[str]]] = [
    (
        "Long line stop",
        RuleType.LONG_STOP,
        {"minutes": 10, "scope": "incident"},
        Severity.WARNING,
        [OPERATOR, SUPERVISOR],
        15,
        [MANAGER],
    ),
    (
        "Machine offline",
        RuleType.MACHINE_OFFLINE,
        {},
        Severity.WARNING,
        [SUPERVISOR, TECHNICIAN],
        15,
        [MANAGER],
    ),
    (
        "Recurring stop",
        RuleType.RECURRING_STOP,
        {"count": 3, "window_hours": 8},
        Severity.WARNING,
        [SUPERVISOR],
        None,
        [],
    ),
    (
        "Low OEE this shift",
        RuleType.LOW_OEE,
        {"below_percent": 60, "min_planned_minutes": 60},
        Severity.WARNING,
        [SUPERVISOR, MANAGER],
        None,
        [],
    ),
    (
        "High defect rate",
        RuleType.HIGH_DEFECT_RATE,
        {"above_percent": 2, "window_minutes": 30, "min_units": 500},
        Severity.WARNING,
        [INSPECTOR, SUPERVISOR],
        None,
        [],
    ),
    (
        "Stop still needs a reason",
        RuleType.UNCLASSIFIED_STOPS,
        {"minutes_after_end": 15},
        Severity.INFO,
        [OPERATOR, SUPERVISOR],
        None,
        [],
    ),
    (
        "Maintenance overdue",
        RuleType.MAINTENANCE_OVERDUE,
        {},
        Severity.WARNING,
        [SUPERVISOR, MANAGER],
        None,
        [],
    ),
]


def ensure_default_rules(factory: Factory) -> int:
    """Create the rules this factory does not have yet (one per type)."""
    created = 0
    for name, rule_type, params, severity, roles, escalate, escalation_roles in DEFAULT_RULES:
        if AlertRule.objects.filter(factory=factory, rule_type=rule_type).exists():
            continue
        AlertRule.objects.create(
            factory=factory,
            name=name,
            rule_type=rule_type,
            parameters=params,
            severity=severity,
            recipient_roles=roles,
            escalate_after_minutes=escalate,
            escalation_roles=escalation_roles,
        )
        created += 1
    return created
