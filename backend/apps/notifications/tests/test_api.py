"""Alerts API: rules CRUD and validation, alert actions, notifications, preferences, isolation."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from apps.audit.models import AuditLog
from apps.notifications.models import (
    Alert,
    AlertRule,
    AlertStatus,
    DeliveryStatus,
    Notification,
    RuleType,
)
from apps.notifications.tasks import after_failed_attempt
from apps.production.models import Shift
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

from .support import T

Send = Callable[..., str]
RULES = "/api/v1/alert-rules/"


@pytest.fixture
def alert(
    day_shift: Shift, send: Send, make_rule: Callable[..., Any], evaluate: Callable[..., Any]
) -> Alert:
    """An open machine_offline alert for the Filler, told to production supervisors."""
    for machine in ("M01", "M02", "M03"):
        send(machine, "machine_started", T - timedelta(minutes=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", T - timedelta(seconds=10))
    make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})
    [opened] = evaluate(T).opened
    return opened


def rule_body(bottling: Bottling, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "factory": bottling.line.factory.id,
        "line": bottling.line.id,
        "rule_type": "long_stop",
        "parameters": {"minutes": 5},
        "severity": "warning",
        "recipient_roles": ["production_supervisor"],
        "escalate_after_minutes": 15,
        "escalation_roles": ["factory_manager"],
    }
    body.update(overrides)
    return body


# --- Rules -------------------------------------------------------------------------------


def test_managers_create_edit_and_delete_rules_with_audit(
    bottling: Bottling, world: World, api: ApiFactory
) -> None:
    client = api(world.users["factory_manager"])

    created = client.post(RULES, rule_body(bottling), format="json")
    assert created.status_code == 201, created.json()
    rule_id = created.json()["id"]
    edited = client.patch(f"{RULES}{rule_id}/", {"is_enabled": False}, format="json")
    assert edited.status_code == 200 and edited.json()["is_enabled"] is False
    assert client.delete(f"{RULES}{rule_id}/").status_code == 204

    actions = list(
        AuditLog.objects.filter(entity_type="AlertRule", entity_id=str(rule_id))
        .order_by("id")
        .values_list("action", flat=True)
    )
    assert actions == ["alertrule.created", "alertrule.updated", "alertrule.deleted"]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"parameters": {"minutes": 0}}, "parameters"),
        ({"parameters": {"minutes": 5, "colour": "red"}}, "parameters"),
        ({"parameters": {"scope": "everything"}}, "parameters"),
        ({"rule_type": "low_oee", "parameters": {"below_percent": 150}}, "parameters"),
        ({"rule_type": "high_defect_rate", "parameters": {"station": 999999}}, "parameters"),
        ({"rule_type": "low_oee", "parameters": {}, "machine": "M05"}, "machine"),
        ({"rule_type": "teleport"}, "rule_type"),
        ({"recipient_roles": []}, "recipient_roles"),
        ({"recipient_roles": ["boss"]}, "recipient_roles"),
        ({"escalation_roles": []}, "escalation_roles"),
        ({"line": "other"}, "line"),
    ],
)
def test_rule_validation(
    overrides: dict[str, Any], field: str, bottling: Bottling, world: World, api: ApiFactory
) -> None:
    if overrides.get("machine") == "M05":
        overrides["machine"] = bottling.machines["M05"].id
    if overrides.get("line") == "other":
        overrides["line"] = world.line_a.id  # Plant A, not this rule's factory
    response = api(world.users["factory_manager"]).post(
        RULES, rule_body(bottling, **overrides), format="json"
    )

    assert response.status_code == 400
    assert field in response.json(), response.json()


def test_each_type_has_a_valid_default(bottling: Bottling, world: World, api: ApiFactory) -> None:
    client = api(world.users["factory_manager"])
    types = client.get(f"{RULES}types/").json()

    assert {t["type"] for t in types} == set(RuleType.values)
    for item in types:
        body = rule_body(bottling, rule_type=item["type"], parameters={})
        assert client.post(RULES, body, format="json").status_code == 201, item["type"]


@pytest.mark.parametrize("user", ["production_supervisor", "machine_operator", "limited_manager"])
def test_only_configuration_managers_write_rules(
    user: str, bottling: Bottling, world: World, api: ApiFactory
) -> None:
    client = api(world.users[user])

    response = client.post(RULES, rule_body(bottling), format="json")

    # limited_manager manages Plant A only: Plant B's factory is not a valid choice for them.
    assert response.status_code in (400, 403)
    assert not AlertRule.objects.exists()


def test_rules_are_tenant_isolated(bottling: Bottling, world: World, api: ApiFactory) -> None:
    rule = AlertRule.objects.create(
        factory=bottling.line.factory,
        rule_type="long_stop",
        recipient_roles=["production_supervisor"],
    )
    for user in ("other_manager", "limited_manager"):
        client = api(world.users[user])
        assert client.get(f"{RULES}{rule.id}/").status_code == 404
        assert (
            client.patch(f"{RULES}{rule.id}/", {"is_enabled": False}, format="json").status_code
            == 404
        )
        assert client.delete(f"{RULES}{rule.id}/").status_code == 404
        assert rule.id not in [r["id"] for r in client.get(RULES).json()]
    other = api(world.users["other_manager"]).post(RULES, rule_body(bottling), format="json")
    assert other.status_code == 400  # another organization's factory is not a valid choice


# --- Alerts --------------------------------------------------------------------------------


def test_alert_list_filters_and_open_first(alert: Alert, world: World, api: ApiFactory) -> None:
    resolved = Alert.objects.create(
        rule=alert.rule,
        factory=alert.factory,
        line=alert.line,
        subject_type="machine",
        subject_key="machine:old",
        severity="critical",
        status=AlertStatus.RESOLVED,
        opened_at=T + timedelta(hours=1),
        condition_since=T,
        message_key="alert.machine_offline",
        last_evaluated_at=T,
        resolution="auto",
        resolved_at=T + timedelta(hours=2),
    )
    client = api(world.users["analyst"])

    def ids(**params: Any) -> list[int]:
        response = client.get("/api/v1/alerts/", params)
        assert response.status_code == 200, response.json()
        return [a["id"] for a in response.json()["results"]]

    assert ids() == [alert.id, resolved.id]  # open first, although older
    assert ids(status="resolved") == [resolved.id]
    assert ids(status="unresolved") == [alert.id]
    assert ids(severity="critical") == [resolved.id]
    assert ids(type="machine_offline") == [alert.id, resolved.id]
    assert ids(type="low_oee") == []
    assert ids(machine=alert.machine_id) == [alert.id]
    assert ids(start=(T + timedelta(minutes=30)).isoformat()) == [resolved.id]
    assert client.get("/api/v1/alerts/", {"status": "maybe"}).status_code == 400
    row = client.get(f"/api/v1/alerts/{alert.id}/").json()
    assert row["message_key"] == "alert.machine_offline"
    assert row["message_values"]["machine"] == "Filler"
    assert row["subject"] == {"type": "machine", "id": alert.machine_id, "key": alert.subject_key}


def test_acknowledge_and_resolve_permissions_and_audit(
    alert: Alert, world: World, api: ApiFactory
) -> None:
    url = f"/api/v1/alerts/{alert.id}/"
    assert api(world.users["analyst"]).post(f"{url}acknowledge/").status_code == 403
    assert api(world.users["machine_operator"]).post(f"{url}acknowledge/").status_code == 403

    acked = api(world.users["production_supervisor"]).post(
        f"{url}acknowledge/", {"note": "Checking the cable"}, format="json"
    )
    assert acked.status_code == 200
    assert (acked.json()["status"], acked.json()["acknowledge_note"]) == (
        "acknowledged",
        "Checking the cable",
    )
    assert api(world.users["production_supervisor"]).post(f"{url}acknowledge/").status_code == 400

    assert (
        api(world.users["machine_operator"]).post(f"{url}resolve/", {"note": "x"}).status_code
        == 403
    )
    no_note = api(world.users["factory_manager"]).post(
        f"{url}resolve/", {"note": " "}, format="json"
    )
    assert no_note.status_code == 400 and "note" in no_note.json()
    resolved = api(world.users["factory_manager"]).post(
        f"{url}resolve/", {"note": "Sensor replaced"}, format="json"
    )
    assert resolved.status_code == 200
    assert (resolved.json()["resolution"], resolved.json()["resolved_by"]) == (
        "manual",
        "factory_manager@demo.test",
    )

    audits = AuditLog.objects.filter(entity_type="Alert", entity_id=str(alert.id)).order_by("id")
    assert [(a.action, a.after["status"]) for a in audits] == [
        ("alert.acknowledged", "acknowledged"),
        ("alert.resolved", "resolved"),
    ]


def test_recipient_roles_may_acknowledge(
    day_shift: Shift,
    send: Send,
    make_rule: Callable[..., Any],
    evaluate: Callable[..., Any],
    world: World,
    api: ApiFactory,
) -> None:
    for machine in ("M01", "M02", "M03"):
        send(machine, "machine_started", T - timedelta(minutes=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", T - timedelta(seconds=10))
    make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2}, recipient_roles=["maintenance_technician"])
    [alert] = evaluate(T).opened

    response = api(world.users["maintenance_technician"]).post(
        f"/api/v1/alerts/{alert.id}/acknowledge/"
    )

    assert response.status_code == 200


@pytest.mark.parametrize("user", ["other_manager", "limited_operator"])
def test_alerts_are_tenant_isolated(user: str, alert: Alert, world: World, api: ApiFactory) -> None:
    client = api(world.users[user])
    url = f"/api/v1/alerts/{alert.id}/"

    assert client.get(url).status_code == 404
    assert client.post(f"{url}acknowledge/").status_code == 404
    assert client.post(f"{url}resolve/", {"note": "x"}).status_code == 404
    assert client.get("/api/v1/alerts/").json()["count"] == 0


# --- Notifications and preferences ------------------------------------------------------


def test_notifications_are_your_own_and_can_be_marked_read(
    alert: Alert, world: World, api: ApiFactory
) -> None:
    supervisor = api(world.users["production_supervisor"])
    assert supervisor.get("/api/v1/notifications/unread-count/").json() == {"unread_count": 1}
    [row] = supervisor.get("/api/v1/notifications/").json()["results"]
    assert row["alert"]["id"] == alert.id and row["read_at"] is None

    others = api(world.users["factory_manager"])
    assert others.get("/api/v1/notifications/").json()["count"] == 0
    assert others.post(f"/api/v1/notifications/{row['id']}/read/").status_code == 404

    assert supervisor.post(f"/api/v1/notifications/{row['id']}/read/").json() == {"unread_count": 0}
    assert supervisor.get("/api/v1/notifications/", {"unread": "true"}).json()["count"] == 0
    Notification.objects.filter(pk=row["id"]).update(read_at=None)
    assert supervisor.post("/api/v1/notifications/read-all/").json() == {"unread_count": 0}
    assert api(None).get("/api/v1/notifications/").status_code == 401


def test_preferences_get_and_patch(world: World, api: ApiFactory) -> None:
    client = api(world.users["production_supervisor"])
    url = "/api/v1/me/notification-preferences/"

    assert client.get(url).json() == {
        "in_app_min_severity": "info",
        "email_min_severity": "warning",
    }
    changed = client.patch(url, {"email_min_severity": "critical"}, format="json")
    assert changed.json() == {"in_app_min_severity": "info", "email_min_severity": "critical"}
    assert client.patch(url, {"in_app_min_severity": "off"}, format="json").status_code == 400
    assert client.patch(url, {"email_min_severity": "off"}, format="json").status_code == 200


def test_email_retry_decision() -> None:
    notification = Notification(status=DeliveryStatus.PENDING)
    notification.save = lambda **kwargs: None  # type: ignore[method-assign]

    assert [after_failed_attempt(notification, n) for n in (0, 1, 2)] == ["retry"] * 3
    assert after_failed_attempt(notification, 3) == "failed"
    assert notification.status == DeliveryStatus.FAILED
