"""Evidence links (same factory only), "create from" prefill, and the confirmed diagnosis."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from apps.downtime.default_reasons import ensure_default_reasons
from apps.downtime.models import DowntimeClassification, DowntimeEvent, DowntimeReason
from apps.downtime.services.analysis import AnalysisFilters, pareto, select_entries
from apps.downtime.services.classification import classify_downtime
from apps.maintenance.models import MaintenanceAction, MaintenanceDiagnosis
from apps.maintenance.services.diagnosis import preview, record_diagnosis
from apps.maintenance.services.links import LinkError, add_links
from apps.maintenance.services.workflow import NotAllowed, WorkflowError
from apps.notifications.models import Alert, AlertRule
from apps.production.models import IngestedEvent, MachineStateEvent
from apps.production.services.ingestion import ingest_event
from apps.quality.defaults import ensure_default_defect_types, ensure_demo_stations
from apps.quality.models import InspectionResult
from tests.helpers import ApiFactory, World
from tests.lines import Bottling, create_bottling_line

T = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
Send = Callable[..., str]


def jams(send: Send, count: int, start: datetime = T, alarm: str = "E-204") -> list[DowntimeEvent]:
    send("M05", "machine_started", start - timedelta(hours=1))
    for i in range(count):
        at = start + timedelta(minutes=10 * i)
        send("M05", "machine_stopped", at, alarm_code=alarm)
        send("M05", "machine_started", at + timedelta(seconds=60))
    return list(
        DowntimeEvent.objects.filter(
            line__name="Bottling Line", machine__external_id="M05", category="breakdown"
        ).order_by("started_at")
    )


@pytest.fixture
def plant_a(world: World) -> Bottling:
    """A second bottling line in Plant A, with a stop of its own (another factory)."""
    ensure_default_reasons(world.factory_a)
    line = create_bottling_line(world.factory_a, "Plant A line")
    for at, kind in (
        (T, "machine_started"),
        (T + timedelta(minutes=1), "machine_stopped"),
        (T + timedelta(minutes=2), "machine_started"),
    ):
        ingest_event(
            line.api_key,
            {
                "event_id": str(uuid.uuid4()),
                "machine_external_id": "M05",
                "event_type": kind,
                "timestamp": at.isoformat(),
            },
        )
    return line


def reason(bottling: Bottling, code: str) -> DowntimeReason:
    return DowntimeReason.objects.get(factory=bottling.line.factory, code=code)


# --- Links -------------------------------------------------------------------------------


def test_links_must_belong_to_the_actions_factory(
    all_day_shift: Any,
    send: Send,
    plant_a: Bottling,
    bottling: Bottling,
    new_action: Callable[..., MaintenanceAction],
    world: World,
) -> None:
    [own] = jams(send, 1)
    action = new_action()
    other_stop = DowntimeEvent.objects.get(line=plant_a.line, category="breakdown")
    user = world.users["production_supervisor"]

    add_links(
        action,
        [{"kind": "downtime_event", "id": own.pk}, {"kind": "incident", "id": own.incident_id}],
        user,
    )
    for bad in (
        {"kind": "downtime_event", "id": other_stop.pk},
        {"kind": "incident", "id": other_stop.incident_id},
        {"kind": "signature", "machine": plant_a.machines["M05"].pk, "alarm_code": "E-204"},
        {
            "kind": "signature",
            "machine": bottling.machines["M05"].pk,
            "reason": DowntimeReason.objects.filter(factory=world.factory_a).first().pk,
        },
        {"kind": "signature", "machine": bottling.machines["M05"].pk},  # neither reason nor alarm
        {"kind": "downtime_event", "id": 999999},
    ):
        with pytest.raises(LinkError):
            add_links(action, [bad], user)
    # Another organization's user cannot even see this factory's objects.
    with pytest.raises(LinkError):
        add_links(action, [{"kind": "downtime_event", "id": own.pk}], world.users["other_manager"])

    add_links(
        action,
        [{"kind": "signature", "machine": bottling.machines["M05"].pk, "alarm_code": "E-204"}],
        user,
    )
    with pytest.raises(LinkError, match="already has a problem signature"):
        add_links(
            action,
            [{"kind": "signature", "machine": bottling.machines["M05"].pk, "alarm_code": "E-301"}],
            user,
        )
    assert sorted(action.links.values_list("kind", flat=True)) == [
        "downtime_event",
        "incident",
        "signature",
    ]


def test_prefill_from_each_source(
    all_day_shift: Any,
    send: Send,
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    events = jams(send, 3)
    client = api(world.users["machine_operator"])

    def form(**params: Any) -> dict[str, Any]:
        response = client.get("/api/v1/maintenance-actions/prefill/", params)
        assert response.status_code == 200, response.json()
        return response.json()

    incident = form(source="incident", id=events[0].incident_id)
    assert (incident["machine_name"], incident["line"]) == ("Labeler", bottling.line.id)
    assert {"kind": "incident", "id": events[0].incident_id} in incident["links"]
    assert {
        "kind": "signature",
        "machine": bottling.machines["M05"].id,
        "alarm_code": "E-204",
    } in incident["links"]

    recurring = form(
        source="recurring",
        machine=bottling.machines["M05"].id,
        alarm="E-204",
        start=(T - timedelta(hours=1)).isoformat(),
        end=(T + timedelta(hours=1)).isoformat(),
    )
    assert recurring["title"] == "Labeler · E-204: recurring stops"
    assert sorted(
        link["id"] for link in recurring["links"] if link["kind"] == "downtime_event"
    ) == [e.pk for e in events]

    rule = AlertRule.objects.create(
        factory=bottling.line.factory,
        rule_type="long_stop",
        recipient_roles=["production_supervisor"],
    )
    alert = Alert.objects.create(
        rule=rule,
        factory=bottling.line.factory,
        line=bottling.line,
        machine=bottling.machines["M05"],
        subject_type="incident",
        subject_id=events[0].incident_id,
        subject_key="incident:x",
        severity="warning",
        opened_at=T,
        condition_since=T,
        message_key="alert.long_stop",
        last_evaluated_at=T,
    )
    from_alert = form(source="alert", id=alert.pk)
    assert from_alert["machine"] == bottling.machines["M05"].id
    assert from_alert["links"] == [
        {"kind": "alert", "id": alert.pk},
        {"kind": "incident", "id": events[0].incident_id},
    ]

    ensure_demo_stations(bottling.line, ensure_default_defect_types(world.demo_org))
    send("M04", "quality_defect_detected", T, payload={"defect_code": "Q04"})
    result = InspectionResult.objects.get()
    from_defect = form(source="inspection_result", id=result.pk)
    assert (from_defect["machine_name"], from_defect["links"]) == (
        "Capper",
        [{"kind": "inspection_result", "id": result.pk}],
    )

    machine = form(source="machine", id=bottling.machines["M03"].id)
    assert (machine["machine_name"], machine["links"]) == ("Filler", [])

    other = api(world.users["other_manager"]).get(
        "/api/v1/maintenance-actions/prefill/", {"source": "incident", "id": events[0].incident_id}
    )
    assert other.status_code == 404


def test_create_with_links_from_the_api(
    all_day_shift: Any,
    send: Send,
    bottling: Bottling,
    plant_a: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    [stop] = jams(send, 1)
    client = api(world.users["machine_operator"])
    body = {
        "machine": bottling.machines["M05"].id,
        "title": "Labeler jam",
        "links": [{"kind": "downtime_event", "id": stop.pk}],
    }

    created = client.post("/api/v1/maintenance-actions/", body, format="json")
    assert created.status_code == 201, created.json()
    assert (created.json()["status"], created.json()["link_count"]) == ("requested", 1)

    other_stop = DowntimeEvent.objects.get(line=plant_a.line, category="breakdown")
    refused = client.post(
        "/api/v1/maintenance-actions/",
        {**body, "links": [{"kind": "downtime_event", "id": other_stop.pk}]},
        format="json",
    )
    assert refused.status_code == 400
    assert MaintenanceAction.objects.count() == 1  # nothing half-created
    # An operator may not set planning fields.
    assert (
        client.post(
            "/api/v1/maintenance-actions/", {**body, "priority": "urgent"}, format="json"
        ).status_code
        == 403
    )


# --- Diagnosis ---------------------------------------------------------------------------


@pytest.fixture
def diagnosed_setup(
    all_day_shift: Any,
    send: Send,
    bottling: Bottling,
    world: World,
    new_action: Callable[..., MaintenanceAction],
) -> dict[str, Any]:
    """Five linked E-204 stops: 2 unclassified, 1 already MECH-WEAR, 1 MECH-JAM (same
    category, mechanical) and 1 MAT-LABEL (a different category, chosen by the operator)."""
    events = jams(send, 5)
    operator = world.users["machine_operator"]
    classify_downtime(events[2], reason(bottling, "MECH-WEAR"), "", operator)
    classify_downtime(events[3], reason(bottling, "MECH-JAM"), "", operator)
    classify_downtime(events[4], reason(bottling, "MAT-LABEL"), "label roll was empty", operator)
    action = new_action(
        "in_progress", links=[{"kind": "downtime_event", "id": e.pk} for e in events]
    )
    return {"events": events, "action": action}


def test_preview_counts_what_would_change(
    diagnosed_setup: dict[str, Any], bottling: Bottling
) -> None:
    summary = preview(diagnosed_setup["action"], reason(bottling, "MECH-WEAR"))

    assert summary == {
        "linked_stops": 5,
        "unclassified": 2,
        "same_reason": 1,
        "same_category": 1,
        "other_reasons": [{"code": "MAT-LABEL", "name": "Label roll empty", "count": 1}],
        "would_apply": 3,
        "would_apply_with_replace": 4,
    }


def raw_rows() -> list[tuple]:
    return sorted(
        MachineStateEvent.objects.values_list("event_id", "state", "timestamp", "alarm_code")
    ) + sorted(IngestedEvent.objects.values_list("event_id", "payload", "timestamp"))


def test_applying_keeps_deliberate_reasons_by_default(
    diagnosed_setup: dict[str, Any], bottling: Bottling, world: World
) -> None:
    events, action = diagnosed_setup["events"], diagnosed_setup["action"]
    raw_before = raw_rows()
    wear = reason(bottling, "MECH-WEAR")

    diagnosis = record_diagnosis(
        action,
        wear,
        "Worn roller, replaced",
        world.users["maintenance_technician"],
        apply_to_stops=True,
    )

    assert (diagnosis.applied_count, diagnosis.skipped_count) == (3, 2)
    current = {e.pk: DowntimeEvent.objects.get(pk=e.pk).current_classification for e in events}
    assert [current[e.pk].reason.code for e in events] == [
        "MECH-WEAR",
        "MECH-WEAR",
        "MECH-WEAR",
        "MECH-WEAR",
        "MAT-LABEL",
    ]
    assert [current[e.pk].source for e in events] == [
        "technician",
        "technician",
        "operator",
        "technician",
        "operator",
    ]
    # The operator's choice for the jam stays in the history under the technician's.
    history = DowntimeClassification.objects.filter(downtime_event=events[3]).order_by("created_at")
    assert [(c.reason.code, c.source) for c in history] == [
        ("MECH-JAM", "operator"),
        ("MECH-WEAR", "technician"),
    ]
    assert raw_rows() == raw_before


def test_replacing_other_reasons_only_when_asked_and_the_pareto_moves(
    diagnosed_setup: dict[str, Any], bottling: Bottling, world: World
) -> None:
    events, action = diagnosed_setup["events"], diagnosed_setup["action"]
    filters = AnalysisFilters(
        start=T - timedelta(hours=1),
        end=T + timedelta(hours=2),
        now=T + timedelta(hours=2),
        view="machine",
        categories=frozenset({"breakdown"}),
    )
    before = {
        g["label"]: g["total_seconds"]
        for g in pareto(select_entries([bottling.line], filters), "reason", "machine")["groups"]
    }
    assert before["Unclassified"] == 120

    diagnosis = record_diagnosis(
        action,
        reason(bottling, "MECH-WEAR"),
        "",
        world.users["maintenance_technician"],
        apply_to_stops=True,
        replace_other_reasons=True,
    )

    assert (diagnosis.applied_count, diagnosis.skipped_count) == (
        4,
        1,
    )  # only the one already MECH-WEAR skipped
    after = {
        g["label"]: g["total_seconds"]
        for g in pareto(select_entries([bottling.line], filters), "reason", "machine")["groups"]
    }
    assert after == {"MECH-WEAR · Worn part": 300}
    assert DowntimeEvent.objects.get(pk=events[4].pk).current_classification.source == "technician"


def test_a_diagnosis_without_applying_changes_no_stop(
    diagnosed_setup: dict[str, Any], bottling: Bottling, world: World
) -> None:
    before = list(DowntimeClassification.objects.values_list("pk", flat=True))

    record_diagnosis(
        diagnosed_setup["action"],
        reason(bottling, "MECH-WEAR"),
        "Checked",
        world.users["maintenance_technician"],
    )

    assert list(DowntimeClassification.objects.values_list("pk", flat=True)) == before
    assert MaintenanceDiagnosis.objects.get().applied_to_stops is False


def test_who_and_when_a_diagnosis_can_be_recorded(
    diagnosed_setup: dict[str, Any],
    bottling: Bottling,
    world: World,
    new_action: Callable[..., MaintenanceAction],
    plant_a: Bottling,
) -> None:
    action = diagnosed_setup["action"]
    for user in ("machine_operator", "analyst", "production_supervisor"):
        with pytest.raises(NotAllowed):
            record_diagnosis(action, reason(bottling, "MECH-WEAR"), "", world.users[user])
    with pytest.raises(WorkflowError, match="active downtime reason of this factory"):
        record_diagnosis(
            action,
            DowntimeReason.objects.filter(factory=world.factory_a).first(),
            "",
            world.users["maintenance_technician"],
        )
    with pytest.raises(WorkflowError):
        record_diagnosis(
            new_action("requested"),
            reason(bottling, "MECH-WEAR"),
            "",
            world.users["maintenance_technician"],
        )


def test_diagnosis_api_preview_and_apply(
    diagnosed_setup: dict[str, Any], bottling: Bottling, world: World, api: ApiFactory
) -> None:
    action = diagnosed_setup["action"]
    wear = reason(bottling, "MECH-WEAR")
    client = api(world.users["maintenance_technician"])

    assert (
        client.get(
            f"/api/v1/maintenance-actions/{action.id}/diagnosis/", {"reason": wear.id}
        ).json()["would_apply"]
        == 3
    )
    saved = client.post(
        f"/api/v1/maintenance-actions/{action.id}/diagnosis/",
        {"reason": wear.id, "text": "Worn roller", "apply_to_linked_stops": True},
        format="json",
    )
    assert saved.status_code == 201
    assert (saved.json()["applied_count"], saved.json()["skipped_count"]) == (3, 2)
    history = client.get(f"/api/v1/maintenance-actions/{action.id}/history/").json()
    assert history["diagnoses"][0]["reason"]["code"] == "MECH-WEAR"
