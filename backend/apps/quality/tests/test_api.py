"""Quality API: reviews, permissions, tenant isolation, configuration, list filters and CSV."""

import csv
import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import override_settings

from apps.audit.models import AuditLog
from apps.production.models import Shift
from apps.quality.models import DefectType, InspectionResult, InspectionStation, QualityReview
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

T0 = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
RANGE = {"start": "2026-10-05T06:00:00Z", "end": "2026-10-05T07:00:00Z"}


@pytest.fixture
def results(
    catalogue: dict[str, DefectType], defect: Callable[..., str], bottling: Bottling
) -> list[InspectionResult]:
    """Five defects: Q02 and Q03 at the labeler, Q04 at the capper, Q01 at the filler,
    and one with a spreadsheet formula as its code."""
    for seconds, machine, code in [
        (10, "M05", "Q02"),
        (20, "M05", "Q03"),
        (30, "M04", "Q04"),
        (40, "M03", "Q01"),
        (50, "M05", "=1+2"),
    ]:
        defect(machine, code, T0 + timedelta(seconds=seconds))
    return list(InspectionResult.objects.order_by("timestamp"))


def reviews_url(result: InspectionResult) -> str:
    return f"/api/v1/inspection-results/{result.id}/reviews/"


# --- Reviews --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["quality_inspector", "production_supervisor", "factory_manager", "platform_admin"]
)
def test_reviewers_can_review_and_history_is_kept_and_audited(
    role: str, results: list[InspectionResult], world: World, api: ApiFactory
) -> None:
    client = api(world.users[role])
    result = results[0]

    first = client.post(reviews_url(result), {"verdict": "confirmed"}, format="json")
    second = client.post(
        reviews_url(result), {"verdict": "false_reject", "comment": "glare"}, format="json"
    )

    assert (first.status_code, second.status_code) == (201, 201)
    history = client.get(reviews_url(result)).json()
    assert [(h["verdict"], h["comment"]) for h in history] == [
        ("false_reject", "glare"),
        ("confirmed", ""),
    ]
    assert history[0]["reviewed_by"] == world.users[role].email
    result.refresh_from_db()
    assert result.current_review_id == second.json()["id"]
    audits = AuditLog.objects.filter(action="inspectionresult.reviewed", entity_id=str(result.id))
    assert [
        (a.before and a.before["verdict"], a.after["verdict"]) for a in audits.order_by("id")
    ] == [
        (None, "confirmed"),
        ("confirmed", "false_reject"),
    ]


@pytest.mark.parametrize("role", ["machine_operator", "analyst", "maintenance_technician"])
def test_read_only_roles_cannot_review(
    role: str, results: list[InspectionResult], world: World, api: ApiFactory
) -> None:
    client = api(world.users[role])

    response = client.post(reviews_url(results[0]), {"verdict": "confirmed"}, format="json")

    assert response.status_code == 403
    assert client.get(reviews_url(results[0])).status_code == 200  # they can read history
    assert QualityReview.objects.count() == 0


@pytest.mark.parametrize("user", ["other_manager", "limited_operator"])
def test_other_tenants_get_404(
    user: str, results: list[InspectionResult], world: World, api: ApiFactory, bottling: Bottling
) -> None:
    client = api(world.users[user])
    result = results[0]

    assert client.get(f"/api/v1/inspection-results/{result.id}/").status_code == 404
    assert client.get(reviews_url(result)).status_code == 404
    assert client.post(
        reviews_url(result), {"verdict": "confirmed"}, format="json"
    ).status_code in (
        403,
        404,
    )
    for path in (
        "inspection-results/",
        "quality/summary/",
        "quality/pareto/",
        "quality/trend/",
        "inspection-results/export.csv",
    ):
        response = client.get(f"/api/v1/{path}", {"line": bottling.line.id, **RANGE})
        assert response.status_code == 404, path
    listed = client.get("/api/v1/inspection-results/", RANGE).json()
    assert listed["count"] == 0
    assert client.get("/api/v1/quality/summary/", RANGE).json()["defects"] == 0


def test_reclassify_rules(
    results: list[InspectionResult], world: World, api: ApiFactory, catalogue: dict[str, DefectType]
) -> None:
    client = api(world.users["quality_inspector"])
    result = results[0]  # detected as Q02
    other_org_type = DefectType.objects.get(organization=world.other_org, code="Q03")
    archived = catalogue["Q06"]
    archived.is_active = False
    archived.save()

    cases: list[tuple[dict[str, Any], int]] = [
        ({"verdict": "reclassified"}, 400),
        ({"verdict": "reclassified", "corrected_defect_type": other_org_type.id}, 400),
        ({"verdict": "reclassified", "corrected_defect_type": archived.id}, 400),
        ({"verdict": "reclassified", "corrected_defect_type": catalogue["Q02"].id}, 400),
        ({"verdict": "confirmed", "corrected_defect_type": catalogue["Q03"].id}, 400),
        ({"verdict": "maybe"}, 400),
        ({"verdict": "reclassified", "corrected_defect_type": catalogue["Q03"].id}, 201),
    ]
    for body, expected in cases:
        response = client.post(reviews_url(result), body, format="json")
        assert response.status_code == expected, (body, response.json())

    row = client.get(f"/api/v1/inspection-results/{result.id}/").json()
    assert row["defect_type"]["code"] == "Q02"  # the detection is never overwritten
    assert row["effective_defect_type"]["code"] == "Q03"


# --- Results list ---------------------------------------------------------------------


def test_results_list_filters(
    results: list[InspectionResult],
    world: World,
    api: ApiFactory,
    bottling: Bottling,
    catalogue: dict[str, DefectType],
) -> None:
    client = api(world.users["analyst"])
    api(world.users["quality_inspector"]).post(
        reviews_url(results[0]), {"verdict": "confirmed"}, format="json"
    )
    labeler = InspectionStation.objects.get(machine=bottling.machines["M05"])

    def codes(**params: Any) -> list[str]:
        response = client.get(
            "/api/v1/inspection-results/",
            {"line": bottling.line.id, "ordering": "timestamp", **RANGE, **params},
        )
        assert response.status_code == 200, response.json()
        return [r["reported_code"] for r in response.json()["results"]]

    assert codes() == ["Q02", "Q03", "Q04", "Q01", "=1+2"]
    assert codes(station=labeler.id) == ["Q02", "Q03", "=1+2"]
    assert codes(machine=bottling.machines["M04"].id) == ["Q04"]
    assert codes(defect_type="Q03") == ["Q03"]
    assert codes(defect_type="unknown") == ["=1+2"]
    assert codes(severity="critical") == ["Q04"]
    assert codes(reviewed="true") == ["Q02"]
    assert codes(reviewed="false") == ["Q03", "Q04", "Q01", "=1+2"]
    assert codes(verdict="confirmed") == ["Q02"]
    assert codes(ordering="-timestamp")[0] == "=1+2"
    assert codes(start="2026-10-05T06:00:25Z") == ["Q04", "Q01", "=1+2"]

    # A shift and a date narrow the range like on the downtime page.
    shift = Shift.objects.create(
        factory=bottling.line.factory, name="Early", start_time="06:00", end_time="06:00:30"
    )
    response = client.get(
        "/api/v1/inspection-results/",
        {"line": bottling.line.id, "shift": shift.id, "date": "2026-10-05"},
    )
    assert [r["reported_code"] for r in response.json()["results"]] == ["Q03", "Q02"]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start": "2026-10-05T07:00:00Z", "end": "2026-10-05T06:00:00Z"},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-10-05T00:00:00Z"},
        {**RANGE, "severity": "huge"},
        {**RANGE, "verdict": "sure"},
        {**RANGE, "reviewed": "perhaps"},
        {**RANGE, "ordering": "colour"},
        {**RANGE, "station": "abc"},
    ],
)
def test_invalid_parameters_return_400(
    params: dict[str, str], results: list[InspectionResult], world: World, api: ApiFactory
) -> None:
    response = api(world.users["analyst"]).get("/api/v1/inspection-results/", params)

    assert response.status_code == 400


def test_unauthenticated_gets_401(api: ApiFactory, world: World) -> None:
    for path in ("inspection-results/", "quality/summary/", "defect-types/"):
        assert api(None).get(f"/api/v1/{path}", RANGE).status_code == 401


# --- CSV ------------------------------------------------------------------------------


def read_csv(response: Any) -> list[list[str]]:
    text = b"".join(response.streaming_content).decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def test_csv_export_filters_factory_time_and_formula_protection(
    results: list[InspectionResult], world: World, api: ApiFactory, bottling: Bottling
) -> None:
    factory = bottling.line.factory
    factory.timezone = "Africa/Algiers"
    factory.save()
    api(world.users["quality_inspector"]).post(
        reviews_url(results[1]), {"verdict": "false_reject", "comment": "@SUM(A1)"}, format="json"
    )
    client = api(world.users["analyst"])

    rows = read_csv(
        client.get("/api/v1/inspection-results/export.csv", {"line": bottling.line.id, **RANGE})
    )
    header, body = rows[0], rows[1:]
    assert header[:4] == ["id", "line", "time (factory)", "timezone"]
    assert len(body) == 5
    first = dict(zip(header, body[0], strict=True))
    assert first["time (factory)"] == "2026-10-05T07:00:10.000+01:00"
    assert first["timezone"] == "Africa/Algiers"
    assert (first["station"], first["defect type"], first["severity"]) == (
        "Label and code check (labeler)",
        "Q02",
        "major",
    )
    by_code = {
        row[header.index("reported code")]: dict(zip(header, row, strict=True)) for row in body
    }
    assert "'=1+2" in by_code
    assert by_code["Q03"]["review comment"] == "'@SUM(A1)"
    assert by_code["Q03"]["review"] == "false_reject"

    filtered = read_csv(
        client.get(
            "/api/v1/inspection-results/export.csv",
            {"line": bottling.line.id, "defect_type": "Q04", **RANGE},
        )
    )
    assert [r[header.index("reported code")] for r in filtered[1:]] == ["Q04"]


def test_csv_export_has_a_row_limit(
    results: list[InspectionResult], world: World, api: ApiFactory, bottling: Bottling
) -> None:
    with override_settings(QUALITY_EXPORT_MAX_ROWS=4):
        response = api(world.users["analyst"]).get(
            "/api/v1/inspection-results/export.csv", {"line": bottling.line.id, **RANGE}
        )

    assert response.status_code == 400
    assert "Narrow the filters" in response.json()["detail"]


# --- Defect types and stations ----------------------------------------------------------


def test_managers_create_edit_archive_restore_defect_types_with_audit(
    catalogue: dict[str, DefectType], world: World, api: ApiFactory
) -> None:
    client = api(world.users["factory_manager"])

    created = client.post(
        "/api/v1/defect-types/",
        {"code": "Q07", "name": "Foreign object", "severity": "critical"},
        format="json",
    )
    assert created.status_code == 201
    type_id = created.json()["id"]
    assert (
        client.patch(
            f"/api/v1/defect-types/{type_id}/", {"name": "Foreign body"}, format="json"
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/defect-types/{type_id}/archive/").json()["is_active"] is False
    codes = [t["code"] for t in client.get("/api/v1/defect-types/").json()]
    assert "Q07" not in codes
    assert "Q07" in [
        t["code"] for t in client.get("/api/v1/defect-types/", {"include_archived": "true"}).json()
    ]
    assert client.post(f"/api/v1/defect-types/{type_id}/restore/").json()["is_active"] is True
    assert client.delete(f"/api/v1/defect-types/{type_id}/").status_code == 204  # never used

    actions = list(
        AuditLog.objects.filter(entity_id=str(type_id), entity_type="DefectType")
        .order_by("id")
        .values_list("action", flat=True)
    )
    assert actions == [
        "defecttype.created",
        "defecttype.updated",
        "defecttype.archived",
        "defecttype.restored",
        "defecttype.deleted",
    ]
    duplicate = client.post(
        "/api/v1/defect-types/", {"code": "Q01", "name": "x", "severity": "minor"}, format="json"
    )
    assert duplicate.status_code == 400


def test_a_used_defect_type_cannot_be_deleted_or_recoded(
    results: list[InspectionResult], catalogue: dict[str, DefectType], world: World, api: ApiFactory
) -> None:
    client = api(world.users["factory_manager"])
    q02 = catalogue["Q02"]

    assert client.delete(f"/api/v1/defect-types/{q02.id}/").status_code == 409
    assert (
        client.patch(f"/api/v1/defect-types/{q02.id}/", {"code": "Q20"}, format="json").status_code
        == 400
    )
    assert client.get(f"/api/v1/defect-types/{q02.id}/").json()["in_use"] is True


@pytest.mark.parametrize(
    "user", ["quality_inspector", "analyst", "production_supervisor", "limited_manager"]
)
def test_only_managers_with_all_factories_write_defect_types(
    user: str, catalogue: dict[str, DefectType], world: World, api: ApiFactory
) -> None:
    client = api(world.users[user])

    response = client.post(
        "/api/v1/defect-types/", {"code": "Q08", "name": "x", "severity": "minor"}, format="json"
    )

    assert response.status_code == 403
    assert client.get("/api/v1/defect-types/").status_code == 200


def test_defect_types_are_isolated_per_organization(
    catalogue: dict[str, DefectType], world: World, api: ApiFactory
) -> None:
    client = api(world.users["other_manager"])

    own = client.get("/api/v1/defect-types/").json()
    assert {t["id"] for t in own}.isdisjoint({t.id for t in catalogue.values()})
    q02 = catalogue["Q02"]
    assert client.get(f"/api/v1/defect-types/{q02.id}/").status_code == 404
    assert (
        client.patch(f"/api/v1/defect-types/{q02.id}/", {"name": "x"}, format="json").status_code
        == 404
    )
    assert client.delete(f"/api/v1/defect-types/{q02.id}/").status_code == 404


def test_station_rules_and_isolation(
    results: list[InspectionResult],
    catalogue: dict[str, DefectType],
    world: World,
    api: ApiFactory,
    bottling: Bottling,
) -> None:
    client = api(world.users["factory_manager"])
    labeler = InspectionStation.objects.get(machine=bottling.machines["M05"])

    def create(**overrides: Any) -> Any:
        body = {
            "line": bottling.line.id,
            "machine": bottling.machines["M02"].id,
            "name": "Rinse check",
            "defect_types": [catalogue["Q06"].id],
            **overrides,
        }
        return client.post("/api/v1/inspection-stations/", body, format="json")

    assert create(machine=bottling.machines["M05"].id).status_code == 400  # already has one
    assert create(machine=world.machine_a.id).status_code == 400  # another line's machine
    other_type = DefectType.objects.get(organization=world.other_org, code="Q06")
    assert create(defect_types=[other_type.id]).status_code == 400
    assert create(line=world.other_line.id).status_code == 400
    created = create()
    assert created.status_code == 201
    audit = AuditLog.objects.get(action="inspectionstation.created")
    assert audit.after["defect_types"] == [catalogue["Q06"].id]

    assert client.delete(f"/api/v1/inspection-stations/{labeler.id}/").status_code == 409
    assert client.delete(f"/api/v1/inspection-stations/{created.json()['id']}/").status_code == 204
    assert client.post(f"/api/v1/inspection-stations/{labeler.id}/archive/").status_code == 200

    other = api(world.users["other_manager"])
    assert other.get(f"/api/v1/inspection-stations/{labeler.id}/").status_code == 404
    assert other.post(f"/api/v1/inspection-stations/{labeler.id}/restore/").status_code == 404
    assert (
        api(world.users["quality_inspector"])
        .post(f"/api/v1/inspection-stations/{labeler.id}/restore/")
        .status_code
        == 403
    )
    listed = api(world.users["limited_operator"]).get("/api/v1/inspection-stations/").json()
    assert all(s["line"] != bottling.line.id for s in listed)
