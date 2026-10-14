"""Each rule type: triggers when it should, not when it shouldn't (including its guards)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.downtime.models import DowntimeEvent, DowntimeReason
from apps.downtime.services.classification import classify_downtime
from apps.notifications.models import Alert, AlertStatus, Resolution, RuleType
from apps.production.models import Shift
from apps.quality.defaults import ensure_default_defect_types, ensure_demo_stations
from apps.quality.models import InspectionResult, Verdict
from apps.quality.services.reviews import review_result
from tests.helpers import World
from tests.lines import Bottling

from .support import T

Send = Callable[..., str]


def alerts() -> list[Alert]:
    return list(Alert.objects.order_by("id"))


def stop(
    send: Send, machine: str, at: datetime, seconds: float | None, alarm: str | None = None
) -> None:
    send(machine, "machine_stopped", at, **({"alarm_code": alarm} if alarm else {}))
    if seconds is not None:
        send(machine, "machine_started", at + timedelta(seconds=seconds))


def running_line(send: Send, at: datetime, machines: str = "M01 M02 M03 M04 M05 M06") -> None:
    for machine in machines.split():
        send(machine, "machine_started", at)


# --- long_stop ---------------------------------------------------------------------------


def test_long_stop_opens_once_per_line_stop_after_the_threshold(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.LONG_STOP, {"minutes": 10})
    running_line(send, T - timedelta(hours=1))
    stop(send, "M05", T - timedelta(minutes=12), None, alarm="E-204")
    send("M04", "machine_blocked", T - timedelta(minutes=11, seconds=57))  # a consequence

    assert not evaluate(T - timedelta(minutes=3)).opened  # 9 minutes: not yet
    opened = evaluate(T).opened

    assert len(opened) == 1  # one line stop, not one per affected machine
    alert = opened[0]
    assert (alert.subject_type, alert.machine.external_id) == ("incident", "M05")
    assert alert.message_key == "alert.long_stop"
    assert alert.message_values["alarm"] == "E-204"
    assert alert.condition_since == T - timedelta(minutes=12)

    send("M05", "machine_started", T + timedelta(minutes=1))
    send("M04", "machine_started", T + timedelta(minutes=1))
    result = evaluate(T + timedelta(minutes=2))
    assert [a.pk for a in result.resolved] == [alert.pk]
    alert.refresh_from_db()
    assert (alert.status, alert.resolution) == (AlertStatus.RESOLVED, Resolution.AUTO)


def test_long_stop_default_threshold_is_the_factory_escalation_threshold(
    day_shift: Shift,
    bottling: Bottling,
    send: Send,
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
) -> None:
    factory = bottling.line.factory
    factory.escalation_after_seconds = 5 * 60
    factory.save()
    make_rule(RuleType.LONG_STOP)
    running_line(send, T - timedelta(hours=1))
    stop(send, "M05", T - timedelta(minutes=6), None)

    assert len(evaluate(T).opened) == 1


def test_long_stop_breakdown_scope_alerts_per_machine(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.LONG_STOP, {"minutes": 5, "scope": "breakdown"})
    running_line(send, T - timedelta(hours=1))
    stop(send, "M05", T - timedelta(minutes=12), None)
    stop(send, "M03", T - timedelta(minutes=8), None)

    opened = evaluate(T).opened

    assert sorted(a.machine.external_id for a in opened) == ["M03", "M05"]
    assert {a.message_key for a in opened} == {"alert.long_breakdown"}


# --- recurring_stop ----------------------------------------------------------------------------


def test_recurring_stop_needs_the_count_and_slides_out_of_the_window(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.RECURRING_STOP, {"count": 3, "window_hours": 2})
    running_line(send, T - timedelta(hours=3))
    for minutes in (90, 60):
        stop(send, "M05", T - timedelta(minutes=minutes), 30, alarm="E-204")

    assert not evaluate(T).opened  # twice is not recurring

    stop(send, "M05", T - timedelta(minutes=30), 30, alarm="E-204")
    stop(send, "M03", T - timedelta(minutes=20), 30, alarm="E-301")  # another machine
    [alert] = evaluate(T).opened
    assert alert.machine.external_id == "M05"
    assert alert.message_key == "alert.recurring_stop_alarm"
    assert alert.message_values["count"] == 3
    assert alert.line_id is not None

    # 2 hours later the first stop has left the window: no longer recurring.
    assert [a.pk for a in evaluate(T + timedelta(minutes=35)).resolved] == [alert.pk]


# --- machine_offline -----------------------------------------------------------------------------


def test_machine_offline_after_n_minutes_and_back_when_data_returns(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    running_line(send, T - timedelta(minutes=10), "M01 M02 M03")  # M04-M06 never reported
    running_line(send, T - timedelta(seconds=30), "M01 M02")

    [alert] = evaluate(T).opened
    assert (alert.machine.external_id, alert.message_key) == ("M03", "alert.machine_offline")
    assert alert.condition_since == T - timedelta(minutes=10)

    send("M03", "machine_started", T + timedelta(seconds=40))
    assert [a.pk for a in evaluate(T + timedelta(minutes=1)).resolved] == [alert.pk]


def test_a_silent_line_gives_one_alert_not_one_per_machine(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    running_line(send, T - timedelta(minutes=10))

    opened = evaluate(T).opened

    assert [(a.subject_type, a.message_key) for a in opened] == [("line", "alert.line_offline")]


def test_machine_offline_is_not_an_alert_outside_a_shift_by_default(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> None:
    evening = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
    rule = make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    running_line(send, evening - timedelta(minutes=10), "M01 M02 M03")
    running_line(send, evening - timedelta(seconds=10), "M01 M02")

    assert not evaluate(evening).opened

    rule.active_outside_shifts = True
    rule.save()
    assert len(evaluate(evening).opened) == 1


# --- low_oee ----------------------------------------------------------------------------------


def test_low_oee_waits_for_enough_planned_time(
    day_shift: Shift,
    load: Callable[..., None],
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
) -> None:
    """reference_1h: 06:00-07:00, OEE 88.92% (the 5-minute packer stop)."""
    load("reference_1h")
    seven = datetime(2026, 10, 5, 7, 0, tzinfo=UTC)
    rule = make_rule(RuleType.LOW_OEE, {"below_percent": 90, "min_planned_minutes": 61})

    assert not evaluate(seven).opened  # only 60 minutes of planned time so far

    rule.parameters = {"below_percent": 90, "min_planned_minutes": 60}
    rule.save()
    [alert] = evaluate(seven).opened
    assert alert.message_values["oee"] == 88.92
    assert alert.subject_key.startswith(f"line:{rule.line_id}:shift:")

    rule.parameters = {"below_percent": 85, "min_planned_minutes": 60}
    rule.save()
    assert [a.pk for a in evaluate(seven).resolved] == [alert.pk]  # 88.92% is fine now


# --- high_defect_rate -----------------------------------------------------------------------------


def test_high_defect_rate_needs_volume_and_counts_reviews(
    day_shift: Shift,
    load: Callable[..., None],
    bottling: Bottling,
    world: World,
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
) -> None:
    """reference_quality_1h: 2% of bottles rejected at the labeler (06:00-07:00)."""
    ensure_demo_stations(bottling.line, ensure_default_defect_types(world.demo_org))
    load("reference_quality_1h")
    seven = datetime(2026, 10, 5, 7, 0, tzinfo=UTC)
    rule = make_rule(
        RuleType.HIGH_DEFECT_RATE, {"above_percent": 1.5, "window_minutes": 30, "min_units": 5000}
    )

    assert not evaluate(seven).opened  # only ~3,000 bottles in 30 minutes: too few to judge

    rule.parameters = {"above_percent": 1.5, "window_minutes": 30, "min_units": 500}
    rule.save()
    [alert] = evaluate(seven).opened
    assert alert.message_values["rate"] == 2.0
    assert alert.message_values["units"] == 3000

    # Reviewed false rejects are not defects: the rate drops below 1.5% and the alert resolves.
    inspector = world.users["quality_inspector"]
    recent = InspectionResult.objects.filter(timestamp__gte=seven - timedelta(minutes=30))
    for result in recent.order_by("timestamp")[:20]:
        review_result(result, Verdict.FALSE_REJECT, None, "", inspector)
    assert [a.pk for a in evaluate(seven).resolved] == [alert.pk]


# --- unclassified_stops ----------------------------------------------------------------------


def test_unclassified_first_stops_alert_until_classified(
    day_shift: Shift,
    send: Send,
    bottling: Bottling,
    world: World,
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
) -> None:
    make_rule(RuleType.UNCLASSIFIED_STOPS, {"minutes_after_end": 15})
    running_line(send, T - timedelta(hours=1))
    stop(send, "M05", T - timedelta(minutes=30), 60, alarm="E-204")
    send("M04", "machine_blocked", T - timedelta(minutes=29, seconds=50))  # a consequence
    send("M04", "machine_started", T - timedelta(minutes=29))
    stop(send, "M03", T - timedelta(minutes=5), 60)  # ended only 4 minutes ago

    [alert] = evaluate(T).opened
    assert (alert.machine.external_id, alert.subject_type) == ("M05", "downtime_event")

    event = DowntimeEvent.objects.get(pk=alert.subject_id)
    reason = DowntimeReason.objects.get(factory=bottling.line.factory, code="MAT-LABEL")
    classify_downtime(event, reason, "", world.users["machine_operator"])
    assert [a.pk for a in evaluate(T).resolved] == [alert.pk]
