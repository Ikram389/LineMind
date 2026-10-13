"""OEE endpoint end to end: reference fixture, grouping, isolation and validation."""

from collections.abc import Callable
from datetime import UTC, datetime, time

import pytest
from rest_framework.test import APIClient

from apps.production.models import OrderStatus, Product, ProductionOrder, Shift
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

START, END = "2026-10-05T06:00:00Z", "2026-10-05T07:00:00Z"


def oee_url(bottling: Bottling) -> str:
    return f"/api/v1/lines/{bottling.line.id}/oee/"


@pytest.fixture
def reference(bottling: Bottling, load: Callable[..., None], world: World) -> Bottling:
    """reference_1h loaded; a break-free shift covering 05:00-13:00 UTC; a 0.6 s product order."""
    load("reference_1h")
    factory = bottling.line.factory  # timezone UTC
    Shift.objects.create(factory=factory, name="Day", start_time=time(5), end_time=time(13))
    product = Product.objects.create(
        organization=world.demo_org, name="Water 0.5 L", sku="W050", ideal_cycle_time_seconds="0.6"
    )
    ProductionOrder.objects.create(
        line=bottling.line,
        product=product,
        planned_quantity=6000,
        scheduled_start="2026-10-05T05:00:00Z",
        scheduled_end="2026-10-05T13:00:00Z",
        status=OrderStatus.COMPLETED,
    )
    return bottling


def test_end_to_end_reference_case(reference: Bottling, world: World, api: ApiFactory) -> None:
    response = api(world.users["analyst"]).get(oee_url(reference), {"start": START, "end": END})

    assert response.status_code == 200
    total = response.json()["total"]
    inputs = total["inputs"]
    assert inputs["planned_production_seconds"] == 3600
    assert inputs["unplanned_downtime_seconds"] == 300
    assert inputs["run_seconds"] == 3300
    assert (inputs["total_count"], inputs["rejected_count"], inputs["good_count"]) == (
        5500,
        165,
        5335,
    )
    assert inputs["unplanned_downtime_by_category_seconds"] == {"breakdown": 300}
    assert [total[k]["percent"] for k in ("availability", "performance", "quality", "oee")] == [
        91.67,
        100.00,
        97.00,
        88.92,
    ]
    assert total["data_coverage"]["percent"] == 100.0
    assert total["warnings"] == []
    assert response.json()["counting_machine"] == "M06"


@pytest.mark.parametrize("group_by", ["hour", "day", "shift"])
def test_group_by_total_equals_whole_range(
    reference: Bottling, world: World, api: ApiFactory, group_by: str
) -> None:
    client = api(world.users["analyst"])
    params = {"start": "2026-10-05T05:30:00Z", "end": "2026-10-05T08:00:00Z"}

    whole = client.get(oee_url(reference), params).json()["total"]
    grouped = client.get(oee_url(reference), {**params, "group_by": group_by}).json()

    assert grouped["total"] == whole
    summed = sum(b["inputs"]["total_count"] for b in grouped["buckets"])
    assert summed == whole["inputs"]["total_count"] == 5500
    if group_by == "hour":
        assert [b["label"] for b in grouped["buckets"]] == [
            "2026-10-05 05:00",
            "2026-10-05 06:00",
            "2026-10-05 07:00",
        ]


def test_counter_reset_in_real_data_is_reported(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    Shift.objects.create(
        factory=bottling.line.factory, name="Day", start_time=time(5), end_time=time(13)
    )
    base = datetime(2026, 10, 5, 6, tzinfo=UTC)
    send("M06", "machine_started", base)
    for minute, count in [(0, 1000), (10, 2000), (20, 300), (30, 1300)]:
        send(
            "M06", "production_count_updated", base.replace(minute=minute), count=count, rejected=0
        )

    body = (
        api(world.users["analyst"])
        .get(oee_url(bottling), {"start": START, "end": "2026-10-05T06:30:00Z"})
        .json()
    )

    assert body["total"]["inputs"]["total_count"] == 1000 + 300 + 1000
    codes = {w["code"] for w in body["total"]["warnings"]}
    assert {"counter_reset", "no_product_assigned"} <= codes


def test_zero_planned_time_is_null_not_an_error(
    bottling: Bottling, load: Callable[..., None], world: World, api: ApiFactory
) -> None:
    load("reference_1h")  # no shifts defined

    total = (
        api(world.users["analyst"])
        .get(oee_url(bottling), {"start": START, "end": END})
        .json()["total"]
    )

    assert total["oee"]["ratio"] is None
    assert total["null_reason"] == "no planned production time in this range"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"start": START},
        {"start": END, "end": START},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
        {"start": START, "end": END, "group_by": "week"},
        {"start": "2026-10-05T06:00:00", "end": END},
    ],
)
def test_invalid_parameters_return_400(
    bottling: Bottling, world: World, api: ApiFactory, params: dict[str, str]
) -> None:
    assert api(world.users["analyst"]).get(oee_url(bottling), params).status_code == 400


@pytest.mark.parametrize("user_key", ["other_manager", "limited_operator"])
def test_oee_is_tenant_isolated(
    bottling: Bottling, world: World, api: ApiFactory, user_key: str
) -> None:
    response = api(world.users[user_key]).get(oee_url(bottling), {"start": START, "end": END})

    assert response.status_code == 404


def test_oee_requires_authentication(bottling: Bottling) -> None:
    assert APIClient().get(oee_url(bottling), {"start": START, "end": END}).status_code == 401
