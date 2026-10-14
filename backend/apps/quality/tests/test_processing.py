"""Defect events -> inspection results: once, idempotent, nothing dropped, raw data untouched."""

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from apps.production.event_types import EventType
from apps.production.models import IngestedEvent
from apps.production.services.ingestion import ingest_batch
from apps.quality.models import DefectType, InspectionResult, InspectionStation, Verdict
from apps.quality.services.processing import rebuild_quality
from apps.quality.services.reviews import review_result
from tests.helpers import ApiFactory, World
from tests.lines import Bottling, read_fixture

T0 = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)


def summary_of_results() -> Counter[tuple[str, str | None, str | None]]:
    return Counter(
        (r.machine.external_id, r.station.name if r.station else None, r.reported_code)
        for r in InspectionResult.objects.select_related("machine", "station")
    )


def raw_defect_rows() -> list[tuple]:
    return list(
        IngestedEvent.objects.filter(event_type=EventType.QUALITY_DEFECT_DETECTED)
        .order_by("event_id")
        .values_list("event_id", "machine_id", "timestamp", "payload", "received_at")
    )


def test_each_defect_event_becomes_one_result(
    catalogue: dict[str, DefectType], load: Callable[..., None], bottling: Bottling
) -> None:
    load("reference_1h")

    results = InspectionResult.objects.select_related("station", "defect_type")
    assert results.count() == 165
    assert summary_of_results() == {
        ("M06", "Final check (packer)", "Q02"): 110,
        ("M06", "Final check (packer)", "Q04"): 55,
    }
    first = results.first()
    assert first is not None
    assert first.defect_type == catalogue[first.reported_code]
    assert 0.80 <= first.confidence <= 0.99
    assert first.outcome == "rejected"
    assert first.source == "simulator"
    assert first.warnings == []
    assert first.raw_event.event_id == first.event_id


def test_duplicates_are_ignored(
    catalogue: dict[str, DefectType], load: Callable[..., None], bottling: Bottling
) -> None:
    load("reference_1h")
    again = ingest_batch(bottling.api_key, read_fixture("reference_1h")[:500])

    assert {r.status for r in again} == {"duplicate"}
    assert InspectionResult.objects.count() == 165


def test_any_arrival_order_gives_the_same_results(
    catalogue: dict[str, DefectType], load: Callable[..., None]
) -> None:
    load("reference_1h", shuffle_seed=7, batch_size=97)

    assert summary_of_results() == {
        ("M06", "Final check (packer)", "Q02"): 110,
        ("M06", "Final check (packer)", "Q04"): 55,
    }


def test_rebuild_is_idempotent_keeps_reviews_and_never_changes_raw_events(
    catalogue: dict[str, DefectType], load: Callable[..., None], bottling: Bottling, world: World
) -> None:
    load("reference_1h")
    raw_before = raw_defect_rows()
    result = InspectionResult.objects.order_by("timestamp").first()
    assert result is not None
    review = review_result(result, Verdict.FALSE_REJECT, None, "", world.users["quality_inspector"])
    ids_before = dict(InspectionResult.objects.values_list("event_id", "pk"))

    assert rebuild_quality(bottling.line) == 0  # nothing to change
    assert rebuild_quality(bottling.line, T0, T0 + timedelta(hours=1)) == 0

    assert dict(InspectionResult.objects.values_list("event_id", "pk")) == ids_before
    result.refresh_from_db()
    assert result.current_review == review
    assert raw_defect_rows() == raw_before


def test_unknown_codes_and_machines_without_a_station_are_kept_with_warnings(
    catalogue: dict[str, DefectType],
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    defect("M02", "Q06", T0)  # the rinser has no station
    defect("M05", "Q99", T0 + timedelta(seconds=1))  # not in the catalogue
    defect("M05", "", T0 + timedelta(seconds=2))  # no code at all
    defect("M05", "Q04", T0 + timedelta(seconds=3))  # the labeler station does not check caps
    defect("M05", "Q02", T0 + timedelta(seconds=4), confidence=1.7)

    rows = {
        r.timestamp: r for r in InspectionResult.objects.select_related("station", "defect_type")
    }
    rinser, unknown, empty, unchecked, bad_confidence = (
        rows[T0 + timedelta(seconds=s)] for s in range(5)
    )
    assert rinser.station is None and rinser.defect_type == catalogue["Q06"]
    assert rinser.warnings == ["No active inspection station is configured on Rinser."]
    assert unknown.defect_type is None and unknown.reported_code == "Q99"
    assert unknown.warnings == ["Unknown defect code 'Q99': it is not in the defect catalogue."]
    assert empty.warnings == ["The event has no defect code."]
    assert unchecked.defect_type == catalogue["Q04"]
    assert unchecked.warnings == [
        "Station 'Label and code check (labeler)' is not configured to check Q04."
    ]
    assert bad_confidence.confidence is None
    assert "Confidence 1.7 was ignored" in bad_confidence.warnings[0]

    # The warnings are visible in the API.
    body = (
        api(world.users["analyst"])
        .get(
            "/api/v1/inspection-results/",
            {
                "line": bottling.line.id,
                "start": T0.isoformat(),
                "end": (T0 + timedelta(minutes=1)).isoformat(),
            },
        )
        .json()
    )
    assert [r["warnings"] for r in body["results"] if r["reported_code"] == "Q99"] == [
        ["Unknown defect code 'Q99': it is not in the defect catalogue."]
    ]


def test_configuration_changes_remap_existing_results(
    catalogue: dict[str, DefectType],
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    defect("M02", "Q06", T0)
    defect("M05", "Q99", T0 + timedelta(seconds=1))
    manager = api(world.users["factory_manager"])

    created = manager.post(
        "/api/v1/inspection-stations/",
        {
            "line": bottling.line.id,
            "machine": bottling.machines["M02"].id,
            "name": "Rinse check",
            "defect_types": [catalogue["Q06"].id],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    manager.post(
        "/api/v1/defect-types/",
        {"code": "Q99", "name": "Foreign object", "severity": "critical"},
        format="json",
    )

    rinser = InspectionResult.objects.get(timestamp=T0)
    assert rinser.station_id == created.json()["id"] and rinser.warnings == []
    unknown = InspectionResult.objects.select_related("defect_type").get(
        timestamp=T0 + timedelta(seconds=1)
    )
    assert unknown.defect_type is not None and unknown.defect_type.code == "Q99"
    assert unknown.warnings == [
        "Station 'Label and code check (labeler)' is not configured to check Q99."
    ]


def test_archiving_a_station_keeps_it_on_its_past_results(
    catalogue: dict[str, DefectType],
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    defect("M05", "Q02", T0)
    station = InspectionStation.objects.get(machine=bottling.machines["M05"])

    response = api(world.users["factory_manager"]).post(
        f"/api/v1/inspection-stations/{station.id}/archive/"
    )
    assert response.status_code == 200
    rebuild_quality(bottling.line)
    defect("M05", "Q02", T0 + timedelta(seconds=5))

    old, new = InspectionResult.objects.order_by("timestamp")
    assert old.station_id == station.id  # history keeps its station
    assert new.station_id is None  # new defects: no active station any more
