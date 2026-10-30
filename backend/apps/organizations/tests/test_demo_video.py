"""demo_reset, demo_video_prep and demo_video_restore only touch Demo Beverages."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant.models import Conversation
from apps.audit.models import AuditLog
from apps.maintenance.models import MaintenanceAction
from apps.notifications.defaults import ensure_default_rules
from apps.notifications.models import Alert, AlertRule, AlertStatus, Notification, RuleType
from apps.organizations import demo_video
from apps.organizations.models import Factory, Organization

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER_PASSWORD", "demo-password-for-tests")


def run(name: str) -> str:
    out = StringIO()
    call_command(name, stdout=out)
    return out.getvalue()


def open_alert(factory: Factory) -> Alert:
    now = timezone.now()
    rule = AlertRule.objects.get(factory=factory, rule_type=RuleType.LONG_STOP)
    return Alert.objects.create(
        rule=rule,
        factory=factory,
        subject_type="incident",
        subject_key="incident:1",
        severity=rule.severity,
        opened_at=now,
        condition_since=now,
        message_key="alert.long_stop",
        last_evaluated_at=now,
    )


def long_stop_minutes(factory: Factory) -> int:
    return AlertRule.objects.get(factory=factory, rule_type=RuleType.LONG_STOP).parameters[
        "minutes"
    ]


@pytest.fixture
def demo() -> Factory:
    call_command("seed_demo", stdout=StringIO())
    return Factory.objects.filter(organization__name=demo_video.DEMO_ORGANIZATION).first()


@pytest.fixture
def other_factory() -> Factory:
    organization = Organization.objects.create(name="Demo Video Other Company")
    factory = Factory.objects.create(organization=organization, name="Other Plant")
    ensure_default_rules(factory)
    return factory


def test_demo_reset_tidies_demo_beverages_and_keeps_other_companies(
    demo: Factory, other_factory: Factory
) -> None:
    alert = open_alert(demo)
    others = open_alert(other_factory)
    user = User.objects.get(email="production_supervisor@demo-beverages.test")
    Notification.objects.create(alert=alert, user=user, channel="in_app")
    Conversation.objects.create(organization=demo.organization, user=user)

    output = run("demo_reset")

    alert.refresh_from_db()
    others.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED and alert.resolution_note == demo_video.RESET_NOTE
    assert others.status == AlertStatus.OPEN
    assert not Notification.objects.filter(user=user, read_at__isnull=True).exists()
    assert not Conversation.objects.filter(organization=demo.organization).exists()
    assert "1 alert(s) resolved" in output
    run("demo_reset")  # again: nothing left to do, no error


IMPROVED = {
    "status": "improved",
    "before": {"occurrences_per_10h": 12.32, "downtime_minutes_per_10h": 18.36},
    "after": {"occurrences_per_10h": 1.34, "downtime_minutes_per_10h": 1.79},
}


def test_prep_sets_one_minute_prints_the_action_url_and_restore_puts_ten_back(
    demo: Factory, other_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    action = MaintenanceAction(pk=5, title="Labeler · E-204: recurring jams", status="verified")
    monkeypatch.setattr(demo_video, "ensure_effectiveness_action", lambda: (action, IMPROVED))
    audits = AuditLog.objects.count()

    output = run("demo_video_prep")
    assert long_stop_minutes(demo) == 1
    assert long_stop_minutes(other_factory) == 10
    assert "Jams per 10 run hours 12.32 -> 1.34" in output
    assert "Open it before recording: http://linemind.test/maintenance/5" in output
    assert "Unreviewed defects: 0." in output
    assert AuditLog.objects.count() > audits  # the rule change is audited

    run("demo_video_restore")
    assert long_stop_minutes(demo) == 10


def test_prep_fails_loudly_when_the_result_is_not_improved(
    demo: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    action = MaintenanceAction(pk=5, title="x", status="verified")
    result = {"status": "not_enough_data", "reason": "after_run_time"}
    monkeypatch.setattr(demo_video, "ensure_effectiveness_action", lambda: (action, result))
    with pytest.raises(CommandError, match='"not_enough_data" \\(after_run_time\\)'):
        run("demo_video_prep")


def test_history_is_moved_to_its_own_days_with_its_own_event_ids(demo: Factory) -> None:
    line = demo.lines.order_by("pk").first()
    events = demo_video._history(line)
    first, last = events[0], events[-1]
    assert first["timestamp"].startswith("2026-10-19T05:00:00")
    assert last["timestamp"].startswith("2026-10-21T05:00:00")
    assert len({e["event_id"] for e in events}) == len(events)
    assert first["event_id"] == demo_video._history(line)[0]["event_id"]  # stable for retakes


def test_the_effectiveness_action_is_built_once_through_the_real_services(demo: Factory) -> None:
    """Loads the two fixture days (slow, like the maintenance effectiveness tests)."""
    action, result = demo_video.ensure_effectiveness_action()

    assert action.status == "verified" and action.verification_result == "effective"
    assert action.fixed_at == demo_video.FIXED_AT and action.effectiveness_window_days == 1
    signature = action.links.get(kind="signature")
    assert (signature.signature_machine.external_id, signature.signature_alarm_code) == (
        "M05",
        "E-204",
    )
    stops = action.links.filter(kind="downtime_event").count()
    assert stops >= 5
    diagnosis = action.diagnoses.get()
    assert diagnosis.reason.code == "MECH-JAM" and diagnosis.applied_count == stops
    assert result["status"] == "improved"
    assert result["after"]["occurrences_per_10h"] < result["before"]["occurrences_per_10h"]
    assert not Notification.objects.filter(read_at__isnull=True).exists()

    again, _ = demo_video.ensure_effectiveness_action()  # a retake reuses everything
    assert again.pk == action.pk
    assert MaintenanceAction.objects.filter(title=demo_video.ACTION_TITLE).count() == 1
