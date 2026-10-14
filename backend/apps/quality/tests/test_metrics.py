"""Quality metrics: summary, Pareto and trend, with reviews; OEE is not affected by reviews."""

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest

from apps.production.models import OrderStatus, Product, ProductionOrder, Shift
from apps.quality.models import DefectType, InspectionResult, Verdict
from apps.quality.services.reviews import review_result
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

HOUR = {"start": "2026-10-05T06:00:00Z", "end": "2026-10-05T07:00:00Z"}
SHIFT_150M = {"start": "2026-10-05T06:00:00Z", "end": "2026-10-05T08:30:00Z"}


def plan_hour(bottling: Bottling, world: World, sku: str = "W050") -> Product:
    """A break-free shift around the reference hour and a 0.6 s order covering it."""
    Shift.objects.create(
        factory=bottling.line.factory, name="Day", start_time=time(5), end_time=time(13)
    )
    product = Product.objects.create(
        organization=world.demo_org, name="Water 0.5 L", sku=sku, ideal_cycle_time_seconds="0.6"
    )
    ProductionOrder.objects.create(
        line=bottling.line,
        product=product,
        planned_quantity=6000,
        scheduled_start="2026-10-05T05:00:00Z",
        scheduled_end="2026-10-05T13:00:00Z",
        status=OrderStatus.COMPLETED,
    )
    return product


@pytest.fixture
def quality_hour(
    catalogue: dict[str, DefectType], load: Callable[..., None], bottling: Bottling
) -> Bottling:
    load("reference_quality_1h")
    return bottling


def get(api: ApiFactory, world: World, path: str, **params: Any) -> dict[str, Any]:
    response = api(world.users["analyst"]).get(f"/api/v1/{path}", params)
    assert response.status_code == 200, response.json()
    return response.json()


def review_some(world: World, false_rejects: int, reclassified: int, to: DefectType) -> None:
    inspector = world.users["quality_inspector"]
    results = list(InspectionResult.objects.order_by("timestamp")[: false_rejects + reclassified])
    for result in results[:false_rejects]:
        review_result(result, Verdict.CONFIRMED, None, "", inspector)  # history, then changed
        review_result(result, Verdict.FALSE_REJECT, None, "sensor glare", inspector)
    for result in results[false_rejects:]:
        review_result(result, Verdict.RECLASSIFIED, to, "", inspector)


def test_summary_of_the_reference_quality_hour(
    quality_hour: Bottling, world: World, api: ApiFactory
) -> None:
    body = get(api, world, "quality/summary/", line=quality_hour.line.id, **HOUR)

    stations = {s["station"]["machine"]["external_id"]: s for s in body["inspected_by_station"]}
    assert {m: (s["inspected"], s["defects"]) for m, s in stations.items()} == {
        "M01": (6000, 0),
        "M03": (6000, 0),
        "M04": (6000, 0),
        "M05": (6000, 120),
        "M06": (5880, 0),
    }
    assert stations["M05"]["defect_rate"] == 0.02
    assert body["line_total_count"] == 6000  # 5,880 at the packer + 120 removed upstream
    assert body["line_counts"] == {
        "counting_machine_output": 5880,
        "counting_machine_rejected": 0,
        "upstream_rejected": 120,
    }
    assert (body["defects"], body["defect_rate"]) == (120, 0.02)
    assert body["defects_by_severity"] == {"minor": 0, "major": 120, "critical": 0, "unknown": 0}
    assert (body["false_rejects"], body["unreviewed"], body["results_with_warnings"]) == (0, 120, 0)


def test_false_rejects_are_excluded_and_reclassified_results_move(
    quality_hour: Bottling, world: World, api: ApiFactory, catalogue: dict[str, DefectType]
) -> None:
    review_some(world, false_rejects=3, reclassified=2, to=catalogue["Q03"])

    summary = get(api, world, "quality/summary/", line=quality_hour.line.id, **HOUR)
    assert (summary["defects"], summary["false_rejects"], summary["unreviewed"]) == (117, 3, 115)
    assert summary["defects_by_severity"] == {"minor": 2, "major": 115, "critical": 0, "unknown": 0}

    pareto = get(api, world, "quality/pareto/", line=quality_hour.line.id, **HOUR)
    assert [(g["code"], g["count"]) for g in pareto["groups"]] == [("Q02", 115), ("Q03", 2)]
    assert pareto["total"] == summary["defects"]
    assert pareto["false_rejects_excluded"] == 3

    # The raw results and their review history stay visible.
    assert InspectionResult.objects.count() == 120
    listed = get(
        api, world, "inspection-results/", line=quality_hour.line.id, verdict="false_reject", **HOUR
    )
    assert listed["count"] == 3
    row = listed["results"][0]
    assert (row["is_defect"], row["defect_type"]["code"], row["review"]["verdict"]) == (
        False,
        "Q02",
        "false_reject",
    )
    history = get(api, world, f"inspection-results/{row['id']}/reviews/")
    assert [h["verdict"] for h in history] == ["false_reject", "confirmed"]
    reclassified = get(
        api, world, "inspection-results/", line=quality_hour.line.id, defect_type="Q03", **HOUR
    )
    assert [r["effective_defect_type"]["code"] for r in reclassified["results"]] == ["Q03", "Q03"]
    assert {r["defect_type"]["code"] for r in reclassified["results"]} == {"Q02"}


@pytest.mark.django_db
def test_pareto_totals_equal_the_summary_for_every_grouping(
    catalogue: dict[str, DefectType],
    load: Callable[..., None],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    load("normal_shift_150m")
    # A product for the first hour only, so the product grouping has two groups.
    product = Product.objects.create(
        organization=world.demo_org, name="Water", sku="W050", ideal_cycle_time_seconds="0.6"
    )
    ProductionOrder.objects.create(
        line=bottling.line,
        product=product,
        planned_quantity=6000,
        scheduled_start="2026-10-05T06:00:00Z",
        scheduled_end="2026-10-05T07:00:00Z",
        status=OrderStatus.COMPLETED,
    )
    review_some(world, false_rejects=4, reclassified=3, to=catalogue["Q06"])
    params = {"line": bottling.line.id, **SHIFT_150M}

    summary = get(api, world, "quality/summary/", **params)
    assert summary["defects"] > 50
    assert summary["defects"] == InspectionResult.objects.count() - 4
    station_total = sum(s["defects"] for s in summary["inspected_by_station"])
    assert station_total + summary["defects_without_station"] == summary["defects"]
    assert sum(summary["defects_by_severity"].values()) == summary["defects"]
    for group_by in ("defect_type", "station", "machine", "product"):
        pareto = get(api, world, "quality/pareto/", group_by=group_by, **params)
        assert sum(g["count"] for g in pareto["groups"]) == pareto["total"] == summary["defects"]
        assert pareto["groups"][-1]["cumulative_share"] == 1.0
    products = get(api, world, "quality/pareto/", group_by="product", **params)
    assert {g["label"] for g in products["groups"]} == {"W050 · Water", "No product assigned"}

    # Filters narrow both the same way.
    for extra in ({"defect_type": "Q02"}, {"severity": "critical"}, {"product": product.id}):
        filtered = get(api, world, "quality/summary/", **params, **extra)
        pareto = get(api, world, "quality/pareto/", **params, **extra)
        assert pareto["total"] == filtered["defects"]


def test_trend_totals_come_from_summed_counts(
    catalogue: dict[str, DefectType],
    load: Callable[..., None],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    load("normal_shift_150m")
    params = {"line": bottling.line.id, **SHIFT_150M}

    trend = get(api, world, "quality/trend/", group_by="hour", **params)
    summary = get(api, world, "quality/summary/", **params)

    buckets = trend["buckets"]
    assert [b["label"] for b in buckets] == [
        "2026-10-05 06:00",
        "2026-10-05 07:00",
        "2026-10-05 08:00",
    ]
    total = trend["total"]
    assert total["defects"] == sum(b["defects"] for b in buckets) == summary["defects"]
    assert total["total_count"] == sum(b["total_count"] for b in buckets)
    assert total["total_count"] == summary["line_total_count"]
    assert total["defect_rate"] == round(total["defects"] / total["total_count"], 6)
    average = sum(b["defect_rate"] for b in buckets) / len(buckets)
    assert total["defect_rate"] != pytest.approx(average, abs=1e-9)  # never an average of rates


@pytest.mark.parametrize("group_by", ["defect_type", "station", "machine", "product"])
def test_pareto_works_when_no_product_was_running(
    group_by: str, quality_hour: Bottling, world: World, api: ApiFactory
) -> None:
    """No production order in the range: every defect falls in "No product assigned"."""
    pareto = get(
        api, world, "quality/pareto/", line=quality_hour.line.id, group_by=group_by, **HOUR
    )

    assert pareto["total"] == 120
    if group_by == "product":
        assert [(g["label"], g["count"]) for g in pareto["groups"]] == [
            ("No product assigned", 120)
        ]


def test_trend_needs_a_line(
    world: World, api: ApiFactory, catalogue: dict[str, DefectType]
) -> None:
    response = api(world.users["analyst"]).get("/api/v1/quality/trend/", HOUR)

    assert response.status_code == 400


def test_reviews_never_change_the_oee(
    quality_hour: Bottling, world: World, api: ApiFactory, catalogue: dict[str, DefectType]
) -> None:
    plan_hour(quality_hour, world)
    url = f"/api/v1/lines/{quality_hour.line.id}/oee/"
    before = api(world.users["analyst"]).get(url, HOUR).json()["total"]

    review_some(world, false_rejects=30, reclassified=10, to=catalogue["Q03"])
    after = api(world.users["analyst"]).get(url, HOUR).json()["total"]

    assert after == before
    assert [after[k]["percent"] for k in ("availability", "performance", "quality", "oee")] == [
        100.0,
        100.0,
        98.0,
        98.0,
    ]


def test_the_shift_oee_quality_counts_upstream_rejects(
    catalogue: dict[str, DefectType],
    load: Callable[..., None],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    """normal_shift rejects only upstream of the packer: quality used to show 100%."""
    load("normal_shift_150m")
    plan_hour(bottling, world)

    total = (
        api(world.users["analyst"])
        .get(f"/api/v1/lines/{bottling.line.id}/oee/", SHIFT_150M)
        .json()["total"]
    )

    inputs = total["inputs"]
    assert inputs["counting_machine_rejected_count"] == 0
    assert inputs["upstream_rejected_count"] > 0
    assert inputs["rejected_count"] == inputs["upstream_rejected_count"]
    assert total["quality"]["percent"] < 100.0
    assert set(inputs["upstream_rejected_by_machine"]) <= {"M01", "M02", "M03", "M04", "M05"}
    start = datetime(2026, 10, 5, 6, tzinfo=UTC)
    assert (
        inputs["upstream_rejected_count"]
        == InspectionResult.objects.filter(
            timestamp__gte=start, timestamp__lt=start + timedelta(minutes=150)
        ).count()
    )
