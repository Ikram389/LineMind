"""The engine: deduplication (also in the database), cooldown, auto-resolve, suppression,
idempotency and escalation."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.notifications.evaluators.base import Finding, Subject
from apps.notifications.models import (
    Alert,
    AlertRule,
    AlertStatus,
    Notification,
    RuleType,
    Severity,
)
from apps.notifications.services.actions import acknowledge
from apps.notifications.services.engine import (
    _open,
    enabled_rules,
    evaluate_rules,
    rules_for_lines,
)
from apps.notifications.services.escalation import escalate_due
from apps.organizations.models import Role
from apps.production.models import Shift
from tests.helpers import World
from tests.lines import Bottling

from .support import T

Send = Callable[..., str]


@pytest.fixture
def offline(day_shift: Shift, send: Send, make_rule: Callable[..., Any]) -> AlertRule:
    """M03 silent since T-10 min while M01 and M02 keep reporting: true at T."""
    for machine in ("M01", "M02", "M03"):
        send(machine, "machine_started", T - timedelta(minutes=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", T - timedelta(seconds=10))
    return make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2}, cooldown_minutes=30)


def test_a_condition_that_stays_true_creates_one_alert(
    offline: AlertRule, evaluate: Callable[..., Any]
) -> None:
    # Every 30 s while M01 and M02 still report (they are silent from T+110 s on).
    for seconds in range(0, 100, 30):
        evaluate(T + timedelta(seconds=seconds))

    assert Alert.objects.count() == 1
    alert = Alert.objects.get()
    assert alert.last_evaluated_at == T + timedelta(seconds=90)


def test_running_an_evaluation_twice_changes_nothing(
    offline: AlertRule, evaluate: Callable[..., Any]
) -> None:
    evaluate(T)
    before = list(Alert.objects.values())

    result = evaluate(T)

    assert (result.opened, result.resolved, result.kept) == ([], [], 1)
    assert list(Alert.objects.values()) == before


def test_the_database_refuses_a_second_unresolved_alert(
    offline: AlertRule, evaluate: Callable[..., Any]
) -> None:
    [alert] = evaluate(T).opened
    finding = Finding(Subject("machine", alert.machine_id, alert.subject_key), None, None, T, "x")

    # A second worker that already passed every check in code still cannot insert.
    assert _open(offline, finding, T) is None
    with pytest.raises(IntegrityError), transaction.atomic():
        Alert.objects.create(
            rule=offline,
            factory=offline.factory,
            subject_type="machine",
            subject_key=alert.subject_key,
            severity="warning",
            opened_at=T,
            condition_since=T,
            message_key="x",
            last_evaluated_at=T,
        )
    assert Alert.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_workers_evaluating_at_once_create_one_alert(
    offline: AlertRule,
) -> None:
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            evaluate_rules(enabled_rules(), T)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert Alert.objects.count() == 1


def test_auto_resolve_then_cooldown_before_reopening(
    offline: AlertRule, send: Send, evaluate: Callable[..., Any]
) -> None:
    [alert] = evaluate(T).opened
    send("M03", "machine_started", T + timedelta(minutes=1))
    assert [a.pk for a in evaluate(T + timedelta(minutes=1)).resolved] == [alert.pk]

    # Silent again: the condition is true, but the cooldown (30 min) blocks a new alert.
    send("M01", "machine_started", T + timedelta(minutes=10))
    send("M02", "machine_started", T + timedelta(minutes=10))
    result = evaluate(T + timedelta(minutes=10))
    assert (result.opened, result.cooling_down) == ([], 1)

    send("M01", "machine_started", T + timedelta(minutes=40))
    send("M02", "machine_started", T + timedelta(minutes=40))
    assert len(evaluate(T + timedelta(minutes=40)).opened) == 1
    assert Alert.objects.filter(status=AlertStatus.RESOLVED).count() == 1


def test_no_new_alert_during_a_break_but_open_alerts_still_resolve(
    offline: AlertRule, send: Send, evaluate: Callable[..., Any]
) -> None:
    break_time = datetime(2026, 10, 5, 10, 10, tzinfo=UTC)
    for machine in ("M01", "M02"):
        send(machine, "machine_started", break_time - timedelta(seconds=5))

    result = evaluate(break_time)
    assert (result.opened, result.suppressed) == ([], 1)


def test_no_new_alert_while_the_machine_is_in_a_planned_stop(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    for machine in ("M01", "M02"):
        send(machine, "machine_started", T - timedelta(seconds=10))
    send("M03", "planned_stop_started", T - timedelta(minutes=10))

    result = evaluate(T)

    assert (result.opened, result.suppressed) == ([], 1)


def test_an_open_alert_resolves_even_when_new_ones_are_suppressed(
    offline: AlertRule, send: Send, evaluate: Callable[..., Any]
) -> None:
    [alert] = evaluate(T).opened
    evening = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)  # outside the shift
    send("M03", "machine_started", evening - timedelta(seconds=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", evening - timedelta(seconds=10))

    assert [a.pk for a in evaluate(evening).resolved] == [alert.pk]


def test_a_broken_rule_does_not_stop_the_others(
    offline: AlertRule, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    AlertRule.objects.filter(pk=make_rule(RuleType.LOW_OEE).pk).update(
        parameters={"below_percent": "lots"}
    )

    assert len(evaluate(T).opened) == 1  # the offline rule still works


# --- Escalation ----------------------------------------------------------------------------


@pytest.fixture
def escalating(offline: AlertRule, world: World) -> AlertRule:
    offline.escalate_after_minutes = 15
    offline.escalation_roles = [Role.FACTORY_MANAGER]
    offline.save()
    return offline


def escalated_users() -> set[str]:
    return set(
        Notification.objects.filter(reason="escalated").values_list("user__email", flat=True)
    )


def test_escalation_fires_once_after_the_delay(
    escalating: AlertRule, evaluate: Callable[..., Any]
) -> None:
    [alert] = evaluate(T).opened

    assert escalate_due(T + timedelta(minutes=14)) == []
    assert [a.pk for a in escalate_due(T + timedelta(minutes=15))] == [alert.pk]
    assert escalate_due(T + timedelta(minutes=30)) == []

    assert escalated_users() == {"factory_manager@demo.test"}
    alert.refresh_from_db()
    assert alert.escalated_at == T + timedelta(minutes=15)


def test_no_escalation_after_acknowledgement(
    escalating: AlertRule, evaluate: Callable[..., Any], world: World
) -> None:
    [alert] = evaluate(T).opened
    acknowledge(alert, world.users["production_supervisor"], "on my way")

    assert escalate_due(T + timedelta(minutes=20)) == []
    assert escalated_users() == set()


def test_info_alerts_never_escalate(escalating: AlertRule, evaluate: Callable[..., Any]) -> None:
    escalating.severity = Severity.INFO
    escalating.save()
    evaluate(T)

    assert escalate_due(T + timedelta(hours=2)) == []


def test_escalation_skips_people_already_told(
    escalating: AlertRule, evaluate: Callable[..., Any]
) -> None:
    escalating.recipient_roles = [Role.PRODUCTION_SUPERVISOR, Role.FACTORY_MANAGER]
    escalating.save()
    evaluate(T)

    escalate_due(T + timedelta(minutes=16))

    assert escalated_users() == set()


# --- Event-driven evaluation ----------------------------------------------------------------


def test_new_data_evaluates_the_affected_rules_after_commit(
    bottling: Bottling,
    send: Send,
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The event-driven path uses the real clock, so this test does too."""
    Shift.objects.create(
        factory=bottling.line.factory, name="All day", start_time=time(0), end_time=time(0)
    )
    now = timezone.now()
    for machine in ("M01", "M02", "M03"):
        send(machine, "machine_started", now - timedelta(minutes=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", now - timedelta(seconds=10))
    offline = make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    low_oee = make_rule(RuleType.LOW_OEE)  # time-driven only: not evaluated on new data
    evaluate(now)
    alert = Alert.objects.get(rule=offline)

    with django_capture_on_commit_callbacks(execute=True):
        send("M03", "machine_started", timezone.now() - timedelta(seconds=1))

    alert.refresh_from_db()
    assert (alert.status, alert.resolution) == ("resolved", "auto")
    assert rules_for_lines([bottling.line.id], ["ingestion"]) == [alert.rule]
    assert low_oee not in rules_for_lines([bottling.line.id], ["ingestion", "downtime", "quality"])
