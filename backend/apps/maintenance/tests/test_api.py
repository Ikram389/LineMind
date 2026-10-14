"""Overdue alerts, notifications, permissions, isolation, list filters and CSV."""

import csv
import io
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from apps.maintenance.models import MaintenanceAction, MaintenanceEntry
from apps.maintenance.services.workflow import transition
from apps.notifications.models import (
    Alert,
    AlertRule,
    Channel,
    Notification,
    NotificationPreference,
)
from apps.notifications.services.engine import enabled_rules, evaluate_rules
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

URL = "/api/v1/maintenance-actions/"
NewAction = Callable[..., MaintenanceAction]


# --- maintenance_overdue --------------------------------------------------------------------


@pytest.fixture
def overdue_rule(bottling: Bottling) -> AlertRule:
    return AlertRule.objects.create(
        factory=bottling.line.factory,
        rule_type="maintenance_overdue",
        severity="warning",
        recipient_roles=["production_supervisor"],
        escalate_after_minutes=None,
    )


def test_overdue_opens_after_the_due_day_once_and_resolves_when_done(
    overdue_rule: AlertRule, new_action: NewAction, world: World
) -> None:
    action = new_action("in_progress", due_date=date(2026, 10, 5))
    end_of_day = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)  # factory B is in UTC

    assert not evaluate_rules(enabled_rules(), end_of_day - timedelta(minutes=1)).opened
    [alert] = evaluate_rules(enabled_rules(), end_of_day + timedelta(minutes=1)).opened
    assert (alert.subject_key, alert.message_key) == (
        f"maintenance_action:{action.pk}",
        "alert.maintenance_overdue",
    )
    assert alert.message_values["due_date"] == "2026-10-05"
    # Deduplicated like every rule, and never suppressed by shifts (there are none here).
    evaluate_rules(enabled_rules(), end_of_day + timedelta(hours=3))
    assert Alert.objects.count() == 1

    transition(action, "done", world.users["maintenance_technician"])
    assert [
        a.pk for a in evaluate_rules(enabled_rules(), end_of_day + timedelta(hours=4)).resolved
    ] == [alert.pk]


def test_a_cancelled_or_rescheduled_action_is_not_overdue(
    overdue_rule: AlertRule, new_action: NewAction, world: World, api: ApiFactory
) -> None:
    later = new_action("assigned", due_date=date(2026, 10, 5))
    cancelled = new_action("assigned", due_date=date(2026, 10, 5))
    transition(cancelled, "cancelled", world.users["production_supervisor"], note="Not needed")
    api(world.users["production_supervisor"]).patch(
        f"{URL}{later.id}/", {"due_date": "2026-10-09"}, format="json"
    )

    assert not evaluate_rules(enabled_rules(), datetime(2026, 10, 7, tzinfo=UTC)).opened


# --- Notifications -------------------------------------------------------------------------


def test_the_assignee_is_told_and_the_reporter_hears_when_it_is_done(
    new_action: NewAction, world: World, django_capture_on_commit_callbacks: Any
) -> None:
    technician, operator = world.users["maintenance_technician"], world.users["machine_operator"]
    action = new_action(priority="high")  # reported by the operator
    with django_capture_on_commit_callbacks(execute=True):
        transition(action, "assigned", world.users["production_supervisor"], assignee=technician)

    told = Notification.objects.filter(user=technician, reason="assigned")
    assert sorted(told.values_list("channel", flat=True)) == ["email", "in_app"]  # high = warning
    in_app = told.get(channel=Channel.IN_APP)
    assert (in_app.alert, in_app.message_key, in_app.link) == (
        None,
        "maintenance.assigned",
        f"/maintenance/{action.pk}",
    )
    [email] = mail.outbox
    assert email.to == [technician.email]
    assert f"http://linemind.test/maintenance/{action.pk}" in email.body
    assert "Labeler jams" in email.body

    transition(action, "in_progress", technician)
    transition(action, "done", technician)
    done = Notification.objects.get(user=operator, reason="completed")
    assert (done.channel, done.message_values["by"]) == (
        Channel.IN_APP,
        technician.email,
    )  # info: in-app only


def test_preferences_apply_to_maintenance_notifications(
    new_action: NewAction, world: World
) -> None:
    technician = world.users["maintenance_technician"]
    NotificationPreference.objects.create(
        user=technician, in_app_min_severity="warning", email_min_severity="off"
    )
    action = new_action(priority="low")

    transition(action, "assigned", world.users["production_supervisor"], assignee=technician)

    assert not Notification.objects.filter(user=technician).exists()  # low = info, below warning


def test_the_bell_shows_maintenance_notifications(
    new_action: NewAction, world: World, api: ApiFactory
) -> None:
    technician = world.users["maintenance_technician"]
    transition(new_action(), "assigned", world.users["production_supervisor"], assignee=technician)

    [row] = api(technician).get("/api/v1/notifications/").json()["results"]
    assert (row["alert"], row["message_key"], row["severity"]) == (
        None,
        "maintenance.assigned",
        "info",
    )
    assert row["link"].startswith("/maintenance/")
    assert api(technician).get(f"{URL}mine/count/").json() == {"count": 1}


# --- Permissions and isolation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "allowed"),
    [
        ("machine_operator", True),
        ("quality_inspector", True),
        ("maintenance_technician", True),
        ("production_supervisor", True),
        ("factory_manager", True),
        ("analyst", False),
    ],
)
def test_who_may_request(
    user: str, allowed: bool, bottling: Bottling, world: World, api: ApiFactory
) -> None:
    response = api(world.users[user]).post(
        URL, {"machine": bottling.machines["M05"].id, "title": "Noise"}, format="json"
    )

    assert response.status_code == (201 if allowed else 403)


def test_planning_fields_and_the_work_log(
    new_action: NewAction, world: World, api: ApiFactory
) -> None:
    action = new_action("assigned")
    for user, expected in (
        ("machine_operator", 403),
        ("maintenance_technician", 403),
        ("production_supervisor", 200),
    ):
        response = api(world.users[user]).patch(
            f"{URL}{action.id}/", {"priority": "urgent"}, format="json"
        )
        assert response.status_code == expected, user

    entry = {
        "kind": "repair",
        "text": "Replaced the roller",
        "time_spent_minutes": 45,
        "parts": [{"name": "Roller", "quantity": 1}],
    }
    assert (
        api(world.users["machine_operator"])
        .post(f"{URL}{action.id}/entries/", entry, format="json")
        .status_code
        == 403
    )
    assert (
        api(world.users["analyst"])
        .post(f"{URL}{action.id}/entries/", entry, format="json")
        .status_code
        == 403
    )
    created = api(world.users["maintenance_technician"]).post(
        f"{URL}{action.id}/entries/", entry, format="json"
    )
    assert created.status_code == 201
    assert created.json()["parts"] == [{"name": "Roller", "quantity": 1.0}]
    assert (
        api(world.users["analyst"]).get(f"{URL}{action.id}/entries/").json()[0]["text"]
        == "Replaced the roller"
    )
    with pytest.raises(Exception, match="cannot be changed"):
        MaintenanceEntry.objects.get().save()


@pytest.mark.parametrize("user", ["other_manager", "limited_operator"])
def test_other_tenants_get_404_everywhere(
    user: str, new_action: NewAction, world: World, api: ApiFactory
) -> None:
    action = new_action("done")
    client = api(world.users[user])

    for method, path, body in [
        ("get", f"{URL}{action.id}/", None),
        ("patch", f"{URL}{action.id}/", {"title": "x"}),
        ("post", f"{URL}{action.id}/transition/", {"to": "in_progress", "note": "x"}),
        ("get", f"{URL}{action.id}/entries/", None),
        (
            "post",
            f"{URL}{action.id}/links/",
            {"kind": "signature", "machine": 1, "alarm_code": "x"},
        ),
        ("get", f"{URL}{action.id}/history/", None),
        ("post", f"{URL}{action.id}/diagnosis/", {"reason": 1}),
        ("get", f"{URL}{action.id}/effectiveness/", None),
        ("post", f"{URL}{action.id}/verify/", {"result": "effective"}),
    ]:
        response = (
            getattr(client, method)(path, body, format="json")
            if body is not None
            else getattr(client, method)(path)
        )
        assert response.status_code == 404, (method, path)
    assert client.get(URL).json()["count"] == 0
    assert client.get(f"{URL}export.csv").status_code == 200
    assert read_csv(client.get(f"{URL}export.csv"))[1:] == []


def test_list_filters(new_action: NewAction, world: World, api: ApiFactory) -> None:
    mine = new_action("in_progress", due_date=date(2026, 1, 1))  # long overdue
    new_action("requested", priority="urgent")
    client = api(world.users["maintenance_technician"])

    def ids(**params: Any) -> list[int]:
        return [a["id"] for a in client.get(URL, params).json()["results"]]

    assert ids(mine="true") == [mine.id]
    assert ids(overdue="true") == [mine.id]
    assert ids()[0] == mine.id  # overdue first
    assert len(ids(status="requested,in_progress")) == 2
    assert ids(status="done") == []
    assert client.get(URL, {"status": "lost"}).status_code == 400
    assert client.get(f"{URL}{mine.id}/").json()["is_overdue"] is True


# --- CSV -------------------------------------------------------------------------------


def read_csv(response: Any) -> list[list[str]]:
    text = b"".join(response.streaming_content).decode("utf-8")
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def test_csv_filters_factory_time_and_formula_protection(
    new_action: NewAction, bottling: Bottling, world: World, api: ApiFactory
) -> None:
    factory = bottling.line.factory
    factory.timezone = "Africa/Algiers"
    factory.save()
    new_action(title="=HYPERLINK(1)", problem="@SUM(A1)")
    new_action("in_progress", title="Belt")
    client = api(world.users["analyst"])

    rows = read_csv(client.get(f"{URL}export.csv"))
    header, body = rows[0], rows[1:]
    assert len(body) == 2
    by_title = {row[header.index("title")]: dict(zip(header, row, strict=True)) for row in body}
    assert "'=HYPERLINK(1)" in by_title
    assert by_title["'=HYPERLINK(1)"]["problem"] == "'@SUM(A1)"
    assert by_title["Belt"]["created (factory)"].endswith("+01:00")
    only = read_csv(client.get(f"{URL}export.csv", {"status": "in_progress"}))
    assert [row[header.index("title")] for row in only[1:]] == ["Belt"]

    with override_settings(MAINTENANCE_EXPORT_MAX_ROWS=1):
        assert client.get(f"{URL}export.csv").status_code == 400


def test_completion_time_is_recorded(new_action: NewAction) -> None:
    before = timezone.now()
    action = new_action("done")
    assert action.completed_at >= before and action.fixed_at == action.completed_at


def test_assignees_are_people_of_the_factory_technicians_first(
    new_action: NewAction, world: World, api: ApiFactory
) -> None:
    action = new_action()
    rows = api(world.users["production_supervisor"]).get(f"{URL}{action.id}/assignees/").json()

    emails = [r["email"] for r in rows]
    assert emails[0] == "maintenance_technician@demo.test"
    assert "limited.operator@demo.test" not in emails  # Plant A only
    assert "manager@other.test" not in emails
    assert (
        api(world.users["machine_operator"]).get(f"{URL}{action.id}/assignees/").status_code == 403
    )
