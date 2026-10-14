"""Bulk classification, CSV export, reason management, suggestions, isolation and roles."""

import csv
import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.downtime.default_reasons import ensure_default_reasons
from apps.downtime.models import DowntimeClassification, DowntimeEvent, DowntimeReason
from apps.downtime.services.classification import classify_downtime
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

JAM = {"start": "2026-10-12T10:00:00Z", "end": "2026-10-12T10:15:00Z"}


@pytest.fixture
def jam(bottling: Bottling, load: Callable[..., None]) -> Bottling:
    load("labeler_jam")
    return bottling


def reason(bottling: Bottling, code: str) -> DowntimeReason:
    return DowntimeReason.objects.get(factory=bottling.line.factory, code=code)


def ids(bottling: Bottling, *machines: str) -> list[int]:
    return [
        DowntimeEvent.objects.get(machine=bottling.machines[m]).pk  # one event each in the jam
        for m in machines
    ]


def bulk(client: APIClient, event_ids: list[int], reason_id: int) -> Any:
    return client.post(
        "/api/v1/downtime-events/bulk-classify/",
        {"event_ids": event_ids, "reason": reason_id, "comment": "Same jam"},
        format="json",
    )


# --- Bulk classification ---------------------------------------------------------------


def test_bulk_classify_saves_each_with_audit(jam: Bottling, world: World, api: ApiFactory) -> None:
    event_ids = ids(jam, "M05", "M04", "M06")

    response = bulk(
        api(world.users["production_supervisor"]), event_ids, reason(jam, "MECH-JAM").id
    )

    assert response.status_code == 201
    assert response.json() == {"classified": 3}
    assert DowntimeClassification.objects.filter(downtime_event__in=event_ids).count() == 3
    assert AuditLog.objects.filter(action="downtime.classified").count() == 3


def test_bulk_classify_is_all_or_nothing(jam: Bottling, world: World, api: ApiFactory) -> None:
    foreign = DowntimeEvent.objects.create(  # an event of another organization
        machine=world.other_machine,
        line=world.other_line,
        start_kind="transition",
        start_event_id="00000000-0000-4000-8000-000000000001",
        state="stopped",
        category="breakdown",
        started_at=datetime(2026, 10, 12, 10, tzinfo=UTC),
        ended_at=datetime(2026, 10, 12, 10, 5, tzinfo=UTC),
    )

    response = bulk(
        api(world.users["production_supervisor"]),
        [*ids(jam, "M05", "M04"), foreign.pk],
        reason(jam, "MECH-JAM").id,
    )

    assert response.status_code == 400
    assert str(foreign.pk) in str(response.json())
    assert not DowntimeClassification.objects.exists()
    assert not AuditLog.objects.exists()


def test_bulk_classify_with_archived_reason_saves_nothing(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    archived = reason(jam, "MECH-JAM")
    archived.is_active = False
    archived.save()

    response = bulk(api(world.users["production_supervisor"]), ids(jam, "M05", "M04"), archived.id)

    assert response.status_code == 400
    assert not DowntimeClassification.objects.exists()


@pytest.mark.parametrize("role", ["machine_operator", "analyst", "quality_inspector"])
def test_bulk_classify_refused_for_other_roles(
    jam: Bottling, world: World, api: ApiFactory, role: str
) -> None:
    response = bulk(api(world.users[role]), ids(jam, "M05"), reason(jam, "MECH-JAM").id)

    assert response.status_code == 403
    assert not DowntimeClassification.objects.exists()


# --- CSV export ------------------------------------------------------------------------


def export(client: APIClient, **params: Any) -> list[list[str]]:
    response = client.get("/api/v1/downtime-events/export.csv", params)
    assert response.status_code == 200, getattr(response, "data", None)
    assert response["Content-Type"].startswith("text/csv")
    text = b"".join(response.streaming_content).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def test_export_applies_filters_and_factory_time(
    jam: Bottling, world: World, api: ApiFactory
) -> None:
    factory = jam.line.factory
    factory.timezone = "Africa/Algiers"
    factory.save()

    rows = export(api(world.users["analyst"]), line=jam.line.id, category="breakdown", **JAM)

    header, body = rows[0], rows[1:]
    assert header[:5] == ["id", "line", "machine_id", "machine", "category"]
    assert [r[header.index("machine_id")] for r in body] == ["M05"]
    start = body[0][header.index("start")]
    assert start.startswith("2026-10-12T11:05:00") and start.endswith("+01:00")
    assert body[0][header.index("timezone")] == "Africa/Algiers"
    assert body[0][header.index("first_observed_stop")] == "yes"


@pytest.mark.parametrize("comment", ["=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(A1)", "\t=1"])
def test_export_escapes_formula_injection(
    jam: Bottling, world: World, api: ApiFactory, comment: str
) -> None:
    event = DowntimeEvent.objects.get(machine=jam.machines["M05"])
    classify_downtime(event, reason(jam, "MECH-JAM"), comment, world.users["machine_operator"])

    rows = export(api(world.users["analyst"]), line=jam.line.id, category="breakdown", **JAM)

    assert rows[1][rows[0].index("comment")] == "'" + comment


def test_export_is_tenant_scoped(jam: Bottling, world: World, api: ApiFactory) -> None:
    rows = export(api(world.users["other_manager"]), **JAM)

    assert rows[1:] == []  # header only


def test_export_row_limit(jam: Bottling, world: World, api: ApiFactory, settings: Any) -> None:
    settings.DOWNTIME_EXPORT_MAX_ROWS = 3

    response = api(world.users["analyst"]).get(
        "/api/v1/downtime-events/export.csv", {"line": jam.line.id, **JAM}
    )

    assert response.status_code == 400
    assert "Narrow the filters" in str(response.json())


# --- Reasons ---------------------------------------------------------------------------


def test_manager_manages_reasons_with_audit(world: World, api: ApiFactory) -> None:
    client = api(world.users["factory_manager"])

    created = client.post(
        "/api/v1/downtime-reasons/",
        {
            "factory": world.factory_a.id,
            "code": "MECH-BELT",
            "name": "Belt slipping",
            "category": "mechanical",
        },
        format="json",
    )
    assert created.status_code == 201
    reason_id = created.json()["id"]
    edited = client.patch(
        f"/api/v1/downtime-reasons/{reason_id}/", {"is_changeover": True}, format="json"
    )
    archived = client.post(f"/api/v1/downtime-reasons/{reason_id}/archive/")

    assert edited.status_code == 200 and edited.json()["is_changeover"] is True
    assert archived.status_code == 200 and archived.json()["is_active"] is False
    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert actions == [
        "downtimereason.created",
        "downtimereason.updated",
        "downtimereason.archived",
    ]

    active = client.get("/api/v1/downtime-reasons/", {"factory": world.factory_a.id}).json()
    everything = client.get(
        "/api/v1/downtime-reasons/", {"factory": world.factory_a.id, "include_archived": "true"}
    ).json()
    assert reason_id not in {r["id"] for r in active}
    assert reason_id in {r["id"] for r in everything}


def test_archived_reason_cannot_be_chosen(jam: Bottling, world: World, api: ApiFactory) -> None:
    archived = reason(jam, "MECH-JAM")
    api(world.users["factory_manager"]).post(f"/api/v1/downtime-reasons/{archived.id}/archive/")
    event_id = ids(jam, "M05")[0]

    response = api(world.users["machine_operator"]).post(
        f"/api/v1/downtime-events/{event_id}/classifications/",
        {"reason": archived.id},
        format="json",
    )

    assert response.status_code == 400


def test_reason_in_use_cannot_be_deleted(jam: Bottling, world: World, api: ApiFactory) -> None:
    used, unused = reason(jam, "MECH-JAM"), reason(jam, "MECH-WEAR")
    classify_downtime(
        DowntimeEvent.objects.get(machine=jam.machines["M05"]),
        used,
        "",
        world.users["machine_operator"],
    )
    client = api(world.users["factory_manager"])

    in_use = client.delete(f"/api/v1/downtime-reasons/{used.id}/")
    free = client.delete(f"/api/v1/downtime-reasons/{unused.id}/")

    assert in_use.status_code == 409
    assert "Archive it" in in_use.json()["detail"]
    assert DowntimeReason.objects.filter(pk=used.pk).exists()
    assert free.status_code == 204
    detail = api(world.users["analyst"]).get(f"/api/v1/downtime-reasons/{used.id}/").json()
    assert detail["in_use"] is True


@pytest.mark.parametrize("role", ["machine_operator", "production_supervisor", "analyst"])
def test_other_roles_cannot_change_reasons(world: World, api: ApiFactory, role: str) -> None:
    ensure_default_reasons(world.factory_a)
    some = DowntimeReason.objects.filter(factory=world.factory_a).first()
    client = api(world.users[role])

    assert client.get("/api/v1/downtime-reasons/").status_code == 200
    assert (
        client.patch(
            f"/api/v1/downtime-reasons/{some.id}/", {"name": "x"}, format="json"
        ).status_code
        == 403
    )
    assert client.post(f"/api/v1/downtime-reasons/{some.id}/archive/").status_code == 403


def test_reasons_of_other_factories_and_organizations_are_out_of_reach(
    world: World, api: ApiFactory
) -> None:
    ensure_default_reasons(world.factory_b)
    b_reason = DowntimeReason.objects.filter(factory=world.factory_b).first()

    limited = api(world.users["limited_manager"])  # factory A only
    other = api(world.users["other_manager"])

    assert (
        limited.patch(
            f"/api/v1/downtime-reasons/{b_reason.id}/", {"name": "x"}, format="json"
        ).status_code
        == 404
    )
    assert other.get(f"/api/v1/downtime-reasons/{b_reason.id}/").status_code == 404
    created = limited.post(
        "/api/v1/downtime-reasons/",
        {"factory": world.factory_b.id, "code": "X", "name": "x", "category": "mechanical"},
        format="json",
    )
    assert created.status_code == 400


# --- Suggested reasons -----------------------------------------------------------------


def test_suggested_reasons_follow_history_then_category(
    jam: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    factory = jam.line.factory
    factory.stale_after_seconds = 24 * 3600
    factory.save()
    # Earlier labeler stops with the same alarm were mostly label rolls.
    for minute, code in [(0, "MAT-LABEL"), (2, "MAT-LABEL"), (4, "ELEC-SENSOR")]:
        base = datetime(2026, 10, 12, 8, minute, tzinfo=UTC)
        send("M05", "machine_stopped", base, alarm_code="E-204")
        send("M05", "machine_started", base + timedelta(seconds=30))
        earlier = DowntimeEvent.objects.get(machine=jam.machines["M05"], started_at=base)
        classify_downtime(earlier, reason(jam, code), "", world.users["machine_operator"])
    jam_event = DowntimeEvent.objects.get(
        machine=jam.machines["M05"], started_at__gte=datetime(2026, 10, 12, 10, tzinfo=UTC)
    )

    codes = [
        r["code"]
        for r in api(world.users["machine_operator"])
        .get(f"/api/v1/downtime-events/{jam_event.id}/suggested-reasons/")
        .json()
    ]

    assert codes[:2] == ["MAT-LABEL", "ELEC-SENSOR"]
    assert set(codes[2:]) <= {"MECH-JAM", "MECH-WEAR", "MECH-ADJUST", "ELEC-DRIVE"}
    assert len(codes) == 6


# --- Isolation and authentication on the analysis endpoints ----------------------------


@pytest.mark.parametrize("path", ["downtime/pareto/", "downtime/summary/", "downtime/recurring/"])
def test_analysis_is_tenant_isolated(
    jam: Bottling, world: World, api: ApiFactory, path: str
) -> None:
    url = f"/api/v1/{path}"

    assert (
        api(world.users["other_manager"]).get(url, {"line": jam.line.id, **JAM}).status_code == 404
    )
    assert (
        api(world.users["limited_operator"]).get(url, {"line": jam.line.id, **JAM}).status_code
        == 404
    )
    assert APIClient().get(url, {"line": jam.line.id, **JAM}).status_code == 401
    # Without ?line=: only the user's own lines are analysed.
    other = api(world.users["other_manager"]).get(url, JAM).json()
    assert other.get("total_seconds", 0) == 0 and other.get("items", []) == []
