"""Downtime API: classification, permissions, isolation, filters, admin, seed data."""

from collections.abc import Callable
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.downtime.default_reasons import DEFAULT_REASONS, ensure_default_reasons
from apps.downtime.models import (
    DowntimeClassification,
    DowntimeEvent,
    DowntimeReason,
    LineStopIncident,
)
from apps.production.models import IngestedEvent, MachineStateEvent
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

EVENTS = "/api/v1/downtime-events/"


@pytest.fixture
def jam(bottling: Bottling, load: Callable[..., None]) -> Bottling:
    load("labeler_jam")
    return bottling


def labeler_event(jam: Bottling) -> DowntimeEvent:
    return DowntimeEvent.objects.get(machine=jam.machines["M05"])


def reason(jam: Bottling, code: str) -> DowntimeReason:
    return DowntimeReason.objects.get(factory=jam.line.factory, code=code)


def classify(client: APIClient, event: DowntimeEvent, reason_id: int, comment: str = "") -> object:
    return client.post(
        f"{EVENTS}{event.id}/classifications/",
        {"reason": reason_id, "comment": comment},
        format="json",
    )


# --- Classification --------------------------------------------------------------------


def test_classification_history_audit_and_raw_data_untouched(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    event = labeler_event(jam)
    raw_before = (
        list(MachineStateEvent.objects.order_by("id").values()),
        list(IngestedEvent.objects.order_by("id").values_list("id", "event_type", "timestamp")),
    )

    first = classify(
        api(world.users["machine_operator"]), event, reason(jam, "MAT-LABEL").id, "Roll empty"
    )
    second = classify(
        api(world.users["production_supervisor"]), event, reason(jam, "MECH-JAM").id, "Web snapped"
    )

    assert first.status_code == 201 and first.json()["source"] == "operator"
    assert second.status_code == 201 and second.json()["source"] == "supervisor"

    history = api(world.users["analyst"]).get(f"{EVENTS}{event.id}/classifications/").json()
    assert [h["reason"]["code"] for h in history] == ["MECH-JAM", "MAT-LABEL"]  # newest first
    assert history[1]["created_by"] == "machine_operator@demo.test"

    detail = api(world.users["analyst"]).get(f"{EVENTS}{event.id}/").json()
    assert detail["classification"]["reason"]["code"] == "MECH-JAM"
    assert DowntimeClassification.objects.filter(downtime_event=event).count() == 2

    audit = list(AuditLog.objects.filter(entity_id=str(event.id)).order_by("timestamp", "id"))
    assert [a.action for a in audit] == ["downtime.classified", "downtime.classified"]
    assert audit[0].before is None
    assert audit[0].after["reason"] == "MAT-LABEL"
    assert audit[1].before["reason"] == "MAT-LABEL"
    assert audit[1].after["reason"] == "MECH-JAM"
    assert audit[1].user == world.users["production_supervisor"]
    assert audit[1].organization == world.demo_org

    raw_after = (
        list(MachineStateEvent.objects.order_by("id").values()),
        list(IngestedEvent.objects.order_by("id").values_list("id", "event_type", "timestamp")),
    )
    assert raw_after == raw_before


@pytest.mark.parametrize("role", ["factory_manager", "platform_admin"])
def test_managers_and_admins_can_classify(
    jam: Bottling, world: World, api: ApiFactory, role: str
) -> None:
    response = classify(api(world.users[role]), labeler_event(jam), reason(jam, "MECH-JAM").id)

    assert response.status_code == 201


@pytest.mark.parametrize("role", ["analyst", "maintenance_technician", "quality_inspector"])
def test_other_roles_cannot_classify(
    jam: Bottling, world: World, api: ApiFactory, role: str
) -> None:
    response = classify(api(world.users[role]), labeler_event(jam), reason(jam, "MECH-JAM").id)

    assert response.status_code == 403
    assert not DowntimeClassification.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize("user_key", ["other_manager", "limited_operator"])
def test_users_outside_the_factory_get_404(
    jam: Bottling, world: World, api: ApiFactory, user_key: str
) -> None:
    client = api(world.users[user_key])
    event = labeler_event(jam)

    assert classify(client, event, reason(jam, "MECH-JAM").id).status_code == 404
    assert client.get(f"{EVENTS}{event.id}/").status_code == 404
    assert client.get(f"{EVENTS}{event.id}/classifications/").status_code == 404
    assert event.id not in {e["id"] for e in client.get(EVENTS).json()["results"]}
    incident = LineStopIncident.objects.get()
    assert client.get(f"/api/v1/incidents/{incident.id}/").status_code == 404
    assert client.get("/api/v1/incidents/").json()["results"] == []
    assert not DowntimeClassification.objects.exists()


def test_reason_from_another_factory_is_rejected(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    ensure_default_reasons(world.factory_a)
    other_factory_reason = DowntimeReason.objects.get(factory=world.factory_a, code="MECH-JAM")

    response = classify(
        api(world.users["machine_operator"]), labeler_event(jam), other_factory_reason.id
    )

    assert response.status_code == 400
    assert not DowntimeClassification.objects.exists()


def test_unknown_reason_is_rejected(jam: Bottling, world: World, api: ApiFactory) -> None:
    response = classify(api(world.users["machine_operator"]), labeler_event(jam), 999999)

    assert response.status_code == 400


def test_unauthenticated_requests_get_401(jam: Bottling) -> None:
    client = APIClient()
    event = labeler_event(jam)

    assert client.get(EVENTS).status_code == 401
    assert client.get("/api/v1/incidents/").status_code == 401
    assert client.get("/api/v1/downtime-reasons/").status_code == 401
    assert classify(client, event, reason(jam, "MECH-JAM").id).status_code == 401


# --- Incidents API ---------------------------------------------------------------------


def test_incident_detail_lists_members_in_time_order(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    client = api(world.users["analyst"])
    incidents = client.get("/api/v1/incidents/", {"line": jam.line.id}).json()["results"]
    assert len(incidents) == 1

    detail = client.get(f"/api/v1/incidents/{incidents[0]['id']}/").json()
    assert detail["origin"] == "machine_stop"
    assert detail["first_observed_stop"]["machine"]["external_id"] == "M05"
    assert "first observed stop" in detail["first_observed_stop"]["note"]
    assert [e["machine"]["external_id"] for e in detail["events"]] == [
        "M05",
        "M04",
        "M06",
        "M03",
        "M02",
        "M01",
    ]
    assert [e["is_first_stop"] for e in detail["events"]] == [True] + [False] * 5
    assert detail["estimated_loss"]["is_estimate"] is True
    assert detail["event_count"] == 6
    assert detail["is_ongoing"] is False


def test_api_never_speaks_of_root_cause(jam: Bottling, world: World, api: ApiFactory) -> None:
    """LineMind reports the first *observed* stop; it never claims a root cause."""
    client = api(world.users["analyst"])
    incident = LineStopIncident.objects.get()
    event = labeler_event(jam)
    responses = [
        client.get("/api/v1/incidents/"),
        client.get(f"/api/v1/incidents/{incident.id}/"),
        client.get(EVENTS),
        client.get(f"{EVENTS}{event.id}/"),
    ]

    for response in responses:
        assert response.status_code == 200
        text = response.content.decode().lower()
        assert "root cause" not in text
        assert "root_cause" not in text
    detail = responses[1].json()
    assert "first_observed_stop" in detail
    assert detail["first_observed_stop"]["machine"]["external_id"] == "M05"


def test_every_loss_is_labelled_as_estimate(jam: Bottling, world: World, api: ApiFactory) -> None:
    events = api(world.users["analyst"]).get(EVENTS).json()["results"]

    assert events
    assert all(e["estimated_loss"]["is_estimate"] is True for e in events)
    labeler = next(e for e in events if e["machine"]["external_id"] == "M05")
    assert labeler["estimated_loss"]["units"] == 150  # 90 s at 6,000/h


# --- Filters ---------------------------------------------------------------------------


def test_downtime_filters(jam: Bottling, world: World, api: ApiFactory) -> None:
    client = api(world.users["analyst"])
    classify(api(world.users["machine_operator"]), labeler_event(jam), reason(jam, "MECH-JAM").id)

    def ids(**params: object) -> list[str]:
        results = client.get(EVENTS, params).json()["results"]
        return sorted(e["machine"]["external_id"] for e in results)

    assert ids(line=jam.line.id) == ["M01", "M02", "M03", "M04", "M05", "M06"]
    assert ids(machine=jam.machines["M04"].id) == ["M04"]
    assert ids(category="starved") == ["M06"]
    assert ids(category="breakdown") == ["M05"]
    assert ids(is_first_stop="true") == ["M05"]
    assert ids(classified="true") == ["M05"]
    assert len(ids(classified="false")) == 5
    assert ids(reason="MECH-JAM") == ["M05"]
    assert ids(start="2026-10-12T10:05:30Z", end="2026-10-12T10:05:45Z") == [
        "M03",
        "M04",
        "M05",
        "M06",
    ]
    assert ids(start="2026-10-12T11:00:00Z") == []


@pytest.mark.parametrize(
    "params",
    [{"classified": "maybe"}, {"category": "explosion"}, {"start": "yesterday"}, {"line": "x"}],
)
def test_invalid_filters_return_400(
    jam: Bottling, world: World, api: ApiFactory, params: dict[str, str]
) -> None:
    assert api(world.users["analyst"]).get(EVENTS, params).status_code == 400


# --- Reasons ---------------------------------------------------------------------------


def test_reasons_are_scoped_to_accessible_factories(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    mine = api(world.users["analyst"]).get("/api/v1/downtime-reasons/").json()
    other = api(world.users["other_manager"]).get("/api/v1/downtime-reasons/").json()

    assert {r["code"] for r in mine} == {code for code, _, _ in DEFAULT_REASONS}
    assert other == []


def test_seed_demo_adds_reason_catalogue_once(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER_PASSWORD", "demo-password-for-tests")

    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    algiers = DowntimeReason.objects.filter(factory__name="Algiers Plant")
    assert algiers.count() == len(DEFAULT_REASONS)
    assert set(algiers.values_list("category", flat=True)) == {
        "mechanical",
        "electrical",
        "material",
        "quality",
        "organizational",
        "planned",
    }


# --- Admin -----------------------------------------------------------------------------


@pytest.fixture
def admin_client(db: None) -> Client:
    user = User.objects.create_superuser(email="root@example.com", password="x-strong-pass-1")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize(
    "model", [DowntimeEvent, LineStopIncident, DowntimeClassification, AuditLog]
)
def test_admin_shows_but_cannot_change_derived_and_history(
    jam: Bottling, world: World, api: ApiFactory, admin_client: Client, model: type
) -> None:
    classify(api(world.users["machine_operator"]), labeler_event(jam), reason(jam, "MECH-JAM").id)
    obj = model.objects.first()
    opts = model._meta
    change_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])

    assert (
        admin_client.get(
            reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        ).status_code
        == 200
    )
    assert admin_client.get(change_url).status_code == 200
    assert admin_client.post(change_url, {}).status_code == 403
    assert (
        admin_client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_add")).status_code
        == 403
    )
