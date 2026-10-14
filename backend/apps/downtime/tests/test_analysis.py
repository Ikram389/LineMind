"""Downtime analysis: line view vs machine view, Pareto, summary, clipping, recurring."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.downtime.models import DowntimeEvent, DowntimeReason
from apps.downtime.services.classification import classify_downtime
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

JAM = {"start": "2026-10-12T10:00:00Z", "end": "2026-10-12T10:15:00Z"}
SECONDARY = {"start": "2026-10-12T14:00:00Z", "end": "2026-10-12T14:15:00Z"}
NORMAL = {"start": "2026-10-05T06:00:00Z", "end": "2026-10-05T08:30:00Z"}


@pytest.fixture
def get(world: World, api: ApiFactory, bottling: Bottling) -> Callable[..., Any]:
    client = api(world.users["production_supervisor"])

    def _get(path: str, **params: Any) -> Any:
        response = client.get(f"/api/v1/{path}", {"line": bottling.line.id, **params})
        assert response.status_code == 200, response.json()
        return response.json()

    return _get


def reason(bottling: Bottling, code: str) -> DowntimeReason:
    return DowntimeReason.objects.get(factory=bottling.line.factory, code=code)


def event_of(bottling: Bottling, machine: str, category: str = "breakdown") -> DowntimeEvent:
    return DowntimeEvent.objects.get(machine=bottling.machines[machine], category=category)


# --- Line view vs machine view ---------------------------------------------------------


def test_labeler_jam_counts_once_in_line_view(
    load: Callable[..., None], get: Callable[..., Any]
) -> None:
    load("labeler_jam")

    line = get("downtime/pareto/", group_by="machine", **JAM)

    assert line["view"] == "line"
    assert [g["label"] for g in line["groups"]] == ["M05 Labeler"]
    assert line["total_seconds"] == pytest.approx(91.0, abs=0.01)  # the incident, once
    assert line["total_occurrences"] == 1
    assert "first observed stop" in line["view_note"]


def test_machine_view_adds_blocked_and_starved_time_and_says_so(
    load: Callable[..., None], get: Callable[..., Any]
) -> None:
    load("labeler_jam")

    machine = get("downtime/pareto/", view="machine", group_by="machine", **JAM)

    totals = {g["label"]: g["total_seconds"] for g in machine["groups"]}
    assert totals == pytest.approx(
        {
            "M05 Labeler": 90,
            "M04 Capper": 87,
            "M06 Packer": 83,
            "M03 Filler": 50,
            "M02 Rinser": 35,
            "M01 Bottle feeder": 20,
        },
        abs=0.01,
    )
    assert machine["total_seconds"] == pytest.approx(365, abs=0.05)
    assert "blocked" in machine["view_note"] and "starved" in machine["view_note"]
    by_category = get("downtime/pareto/", view="machine", group_by="category", **JAM)
    assert {g["label"] for g in by_category["groups"]} == {"Breakdown", "Blocked", "Starved"}


def test_pareto_groups_add_up_exactly_to_the_summary(
    load: Callable[..., None], get: Callable[..., Any], bottling: Bottling, world: World
) -> None:
    load("normal_shift_150m")  # loaded once; every view and grouping checked below
    # Classify a few stops so several reason groups exist.
    events = list(DowntimeEvent.objects.filter(line=bottling.line, is_first_stop=True)[:2])
    for event in events:
        classify_downtime(event, reason(bottling, "MECH-JAM"), "", world.users["machine_operator"])

    for view in ("line", "machine"):
        summary = get("downtime/summary/", view=view, **NORMAL)
        for group_by in ("reason", "machine", "category", "alarm_code"):
            pareto = get("downtime/pareto/", view=view, group_by=group_by, **NORMAL)
            case = f"{view}/{group_by}"
            assert pareto["groups"], case
            assert sum(g["total_micros"] for g in pareto["groups"]) == pareto["total_micros"], case
            assert pareto["total_micros"] == summary["total_micros"], case
            assert sum(g["occurrences"] for g in pareto["groups"]) == summary["stops"], case
            assert pareto["groups"][-1]["cumulative_share"] == 1.0, case
            totals = [g["total_seconds"] for g in pareto["groups"]]
            assert totals == sorted(totals, reverse=True), case
            assert all(g["estimated_lost_units"]["is_estimate"] for g in pareto["groups"]), case


def test_machine_view_total_is_larger_on_a_normal_shift(
    load: Callable[..., None], get: Callable[..., Any]
) -> None:
    load("normal_shift_150m")

    line = get("downtime/summary/", **NORMAL)
    machine = get("downtime/summary/", view="machine", **NORMAL)

    assert machine["total_seconds"] > line["total_seconds"] > 0


def test_unclassified_stops_are_their_own_group(
    load: Callable[..., None], get: Callable[..., Any], bottling: Bottling, world: World
) -> None:
    load("labeler_jam")
    all_unclassified = get("downtime/pareto/", view="machine", group_by="reason", **JAM)
    assert [g["label"] for g in all_unclassified["groups"]] == ["Unclassified"]

    classify_downtime(
        event_of(bottling, "M05"),
        reason(bottling, "MAT-LABEL"),
        "",
        world.users["machine_operator"],
    )
    mixed = get("downtime/pareto/", view="machine", group_by="reason", **JAM)

    labels = {g["label"]: g["occurrences"] for g in mixed["groups"]}
    assert labels == {"Unclassified": 5, "MAT-LABEL · Label roll empty": 1}
    line = get("downtime/pareto/", group_by="reason", **JAM)
    assert [g["label"] for g in line["groups"]] == ["MAT-LABEL · Label roll empty"]


# --- Range clipping, ongoing stops, planned / no data ----------------------------------


@pytest.fixture
def sparse(bottling: Bottling) -> Bottling:
    """Hand-made events are far apart: no telemetry gaps."""
    factory = bottling.line.factory
    factory.stale_after_seconds = 24 * 3600
    factory.save()
    return bottling


def test_durations_are_clipped_to_the_range(
    sparse: Bottling, send: Callable[..., str], get: Callable[..., Any]
) -> None:
    send("M05", "machine_stopped", datetime(2026, 10, 12, 5, 50, tzinfo=UTC))
    send("M05", "machine_started", datetime(2026, 10, 12, 6, 10, tzinfo=UTC))

    summary = get("downtime/summary/", start="2026-10-12T06:00:00Z", end="2026-10-12T07:00:00Z")

    assert summary["total_seconds"] == 600
    assert summary["longest"]["duration_seconds"] == 600


def test_ongoing_stop_counts_up_to_now(
    sparse: Bottling, send: Callable[..., str], get: Callable[..., Any]
) -> None:
    started = timezone.now() - timedelta(minutes=5)
    send("M05", "machine_stopped", started)

    summary = get(
        "downtime/summary/",
        start=(started - timedelta(minutes=1)).isoformat(),
        end=(started + timedelta(hours=1)).isoformat(),  # reaches into the future
    )

    assert 299 <= summary["total_seconds"] <= 320


def test_planned_and_no_data_are_excluded_by_default(
    sparse: Bottling, send: Callable[..., str], get: Callable[..., Any]
) -> None:
    base = datetime(2026, 10, 12, 10, tzinfo=UTC)
    for machine in ("M01", "M02", "M03", "M04", "M05", "M06"):  # a line-wide break
        send(machine, "planned_stop_started", base)
        send(machine, "planned_stop_ended", base + timedelta(minutes=30))
    send("M05", "sensor_disconnected", base + timedelta(minutes=40))
    send("M05", "machine_started", base + timedelta(minutes=45))
    window = {"start": "2026-10-12T09:00:00Z", "end": "2026-10-12T12:00:00Z"}

    default = get("downtime/summary/", **window)
    line = get("downtime/summary/", include="planned,no_data", **window)
    machine = get("downtime/summary/", view="machine", include="planned,no_data", **window)

    assert default["total_seconds"] == 0
    assert line["total_seconds"] == 30 * 60 + 5 * 60  # the break counts once for the line
    assert line["stops"] == 2
    assert machine["total_seconds"] == 6 * 30 * 60 + 5 * 60


# --- Secondary breakdowns --------------------------------------------------------------


def test_secondary_breakdown_is_counted_once_in_the_incident(
    load: Callable[..., None], get: Callable[..., Any], bottling: Bottling
) -> None:
    load("secondary_breakdown")

    line = get("downtime/pareto/", group_by="machine", **SECONDARY)
    summary = get("downtime/summary/", **SECONDARY)
    events = get("downtime-events/", **SECONDARY)["results"]

    assert [g["label"] for g in line["groups"]] == ["M05 Labeler"]  # still attributed once
    assert summary["stops"] == 1
    assert summary["secondary_breakdowns"] == 1
    roles = {e["machine"]["external_id"]: e["role_in_incident"] for e in events}
    assert roles == {
        "M05": "first_observed_stop",
        "M03": "secondary_breakdown",
        "M04": "consequence",
        "M06": "consequence",
        "M02": "consequence",
        "M01": "consequence",
    }


def test_incident_detail_shows_the_cascade_with_delays(
    load: Callable[..., None], world: World, api: ApiFactory, bottling: Bottling
) -> None:
    load("secondary_breakdown")
    incident_id = event_of(bottling, "M05").incident_id

    detail = api(world.users["analyst"]).get(f"/api/v1/incidents/{incident_id}/").json()

    rows = [
        (e["machine"]["external_id"], e["role_in_incident"], e["delay_seconds"])
        for e in detail["events"]
    ]
    assert rows[0] == ("M05", "first_observed_stop", 0.0)
    assert ("M03", "secondary_breakdown", pytest.approx(20.0, abs=0.01)) in [
        (m, r, d) for m, r, d in rows
    ]
    m03 = next(e for e in detail["events"] if e["machine"]["external_id"] == "M03")
    assert m03["alarm_code"] == "E-301"
    assert m03["classifications"] == []


def test_queue_holds_first_stop_then_secondary_breakdown_never_consequences(
    load: Callable[..., None], get: Callable[..., Any], bottling: Bottling, world: World
) -> None:
    load("secondary_breakdown")

    queue = get("downtime-events/", needs_reason="true", classified="false", **SECONDARY)

    assert [e["machine"]["external_id"] for e in queue["results"]] == ["M05", "M03"]

    classify_downtime(
        event_of(bottling, "M05"),
        reason(bottling, "MAT-LABEL"),
        "",
        world.users["machine_operator"],
    )
    after = get("downtime-events/", needs_reason="true", classified="false", **SECONDARY)
    assert [e["machine"]["external_id"] for e in after["results"]] == ["M03"]


# --- Recurring -------------------------------------------------------------------------


def test_recurring_respects_the_threshold_and_counts_secondary_breakdowns(
    load: Callable[..., None], send: Callable[..., str], get: Callable[..., Any], bottling: Bottling
) -> None:
    load("secondary_breakdown")  # one M03 E-301 breakdown, as a secondary breakdown
    send("M03", "machine_stopped", datetime(2026, 10, 12, 14, 12, tzinfo=UTC), alarm_code="E-301")
    send("M03", "machine_started", datetime(2026, 10, 12, 14, 12, 20, tzinfo=UTC))

    default = get("downtime/recurring/", **SECONDARY)
    assert default["threshold"] == 3
    assert default["items"] == []

    factory = bottling.line.factory
    factory.recurring_stop_threshold = 2
    factory.save()
    lowered = get("downtime/recurring/", **SECONDARY)

    assert [
        (i["machine"]["external_id"], i["alarm_code"], i["count"]) for i in lowered["items"]
    ] == [("M03", "E-301", 2)]
    assert lowered["items"][0]["reason"] is None


def test_recurring_ignores_blocked_and_starved(
    load: Callable[..., None], get: Callable[..., Any], bottling: Bottling
) -> None:
    load("labeler_jam")
    factory = bottling.line.factory
    factory.recurring_stop_threshold = 2
    factory.save()

    assert get("downtime/recurring/", **JAM)["items"] == []  # only one breakdown


# --- Events list filters ---------------------------------------------------------------


def test_events_list_filters(load: Callable[..., None], get: Callable[..., Any]) -> None:
    load("labeler_jam")

    def machines(**params: Any) -> list[str]:
        return [
            e["machine"]["external_id"] for e in get("downtime-events/", **JAM, **params)["results"]
        ]

    assert machines(view="line") == ["M05"]
    assert machines(min_duration=80) == ["M05", "M04", "M06"]
    assert machines(max_duration=40) == ["M02", "M01"]
    assert sorted(machines(category="blocked,starved")) == ["M01", "M02", "M03", "M04", "M06"]
    assert machines(ordering="-duration")[:2] == ["M05", "M04"]
    assert machines(reason="unclassified", is_first_stop="true") == ["M05"]
    assert machines(alarm="E-204") == ["M05"]
    assert len(machines(alarm="none")) == 5
    assert get("downtime/summary/", alarm="E-204", **JAM)["stops"] == 1
    assert get("downtime/summary/", alarm="none", **JAM)["stops"] == 0
    clipped = get(
        "downtime-events/", start="2026-10-12T10:06:00Z", end="2026-10-12T10:15:00Z", machine=""
    )
    m05 = next(e for e in clipped["results"] if e["machine"]["external_id"] == "M05")
    assert m05["clipped_duration_seconds"] == pytest.approx(30, abs=0.01)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start": "2026-10-12T10:00:00Z"},
        {"view": "sideways", **JAM},
        {"group_by": "colour", **JAM},
        {"include": "everything", **JAM},
        {"min_duration": "-3", **JAM},
    ],
)
def test_invalid_analysis_parameters(
    get: Callable[..., Any],
    world: World,
    api: ApiFactory,
    bottling: Bottling,
    params: dict[str, str],
) -> None:
    response = api(world.users["analyst"]).get(
        "/api/v1/downtime/pareto/", {"line": bottling.line.id, **params}
    )

    assert response.status_code == 400
