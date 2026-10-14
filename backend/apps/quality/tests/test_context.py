"""Production context of a defect: product/order, machine state and alarm, recent line stop."""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from apps.downtime.models import LineStopIncident
from apps.production.models import OrderStatus, Product, ProductionOrder
from apps.quality.models import DefectType
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

T0 = datetime(2026, 10, 5, 10, 5, tzinfo=UTC)
JAM_END = T0 + timedelta(seconds=90)


@pytest.fixture
def jam(
    send: Callable[..., str], catalogue: dict[str, DefectType], bottling: Bottling
) -> LineStopIncident:
    """The labeler stops at 10:05:00 with E-204 and restarts at 10:06:30."""
    factory = bottling.line.factory
    factory.stale_after_seconds = 24 * 3600  # no gaps between these sparse test events
    factory.save()
    send("M05", "machine_started", T0 - timedelta(minutes=30))
    send("M05", "machine_stopped", T0, alarm_code="E-204")
    send("M05", "machine_started", JAM_END)
    incident = LineStopIncident.objects.get()
    assert incident.ended_at == JAM_END
    return incident


def contexts(api: ApiFactory, world: World, bottling: Bottling) -> dict[str, dict[str, Any]]:
    body = (
        api(world.users["analyst"])
        .get(
            "/api/v1/inspection-results/",
            {
                "line": bottling.line.id,
                "start": "2026-10-05T09:00:00Z",
                "end": "2026-10-05T12:00:00Z",
            },
        )
        .json()
    )
    return {r["timestamp"]: r["context"] for r in body["results"]}


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def test_product_order_machine_state_and_last_alarm(
    jam: LineStopIncident,
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    product = Product.objects.create(
        organization=world.demo_org, name="Water 0.5 L", sku="W050", ideal_cycle_time_seconds="0.6"
    )
    order = ProductionOrder.objects.create(
        line=bottling.line,
        product=product,
        planned_quantity=1000,
        scheduled_start="2026-10-05T10:00:00Z",
        scheduled_end="2026-10-05T11:00:00Z",
        status=OrderStatus.RUNNING,
    )
    during = T0 + timedelta(seconds=30)
    after = JAM_END + timedelta(minutes=2)
    defect("M05", "Q02", during)
    defect("M05", "Q02", after)
    defect("M05", "Q02", T0 - timedelta(minutes=10))  # before the order and the alarm

    found = contexts(api, world, bottling)

    assert found[iso(during)]["machine_state"] == "stopped"
    assert found[iso(after)]["machine_state"] == "running"
    assert found[iso(after)]["last_alarm_code"] == "E-204"
    assert found[iso(after)]["product"] == {"id": product.id, "sku": "W050", "name": "Water 0.5 L"}
    assert found[iso(after)]["order_id"] == order.id
    early = found[iso(T0 - timedelta(minutes=10))]
    assert (early["product"], early["order_id"], early["last_alarm_code"]) == (None, None, None)
    assert early["machine_state"] == "running"


def test_a_line_stop_is_linked_only_inside_the_window(
    jam: LineStopIncident,
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    defect("M05", "Q02", T0 + timedelta(seconds=30))  # during the stop: it has not ended
    defect("M04", "Q04", JAM_END + timedelta(minutes=2))
    defect("M05", "Q02", JAM_END + timedelta(minutes=9, seconds=59))
    defect("M05", "Q02", JAM_END + timedelta(minutes=10, seconds=1))

    found = contexts(api, world, bottling)

    assert found[iso(T0 + timedelta(seconds=30))]["incident"] is None
    two = found[iso(JAM_END + timedelta(minutes=2))]["incident"]
    assert two["id"] == jam.id
    assert two["seconds_after"] == 120
    assert two["first_observed_stop"] == {"machine": "Labeler", "alarm_code": "E-204"}
    assert two["text"] == (
        f"Occurred 2 min after incident #{jam.id} ended (first observed stop: Labeler, E-204)"
    )
    assert found[iso(JAM_END + timedelta(minutes=9, seconds=59))]["incident"]["id"] == jam.id
    assert found[iso(JAM_END + timedelta(minutes=10, seconds=1))]["incident"] is None

    # The window is a factory setting.
    factory = bottling.line.factory
    factory.quality_incident_window_minutes = 15
    factory.save()
    later = contexts(api, world, bottling)[iso(JAM_END + timedelta(minutes=10, seconds=1))]
    assert later["incident"]["id"] == jam.id


def test_the_wording_never_claims_a_cause(
    jam: LineStopIncident,
    defect: Callable[..., str],
    bottling: Bottling,
    world: World,
    api: ApiFactory,
) -> None:
    for seconds in (5, 45, 300):
        defect("M05", "Q02", JAM_END + timedelta(seconds=seconds))

    texts = [
        c["incident"]["text"] for c in contexts(api, world, bottling).values() if c["incident"]
    ]

    assert sorted(texts) == sorted(
        [
            f"Occurred 5 s after incident #{jam.id} ended (first observed stop: Labeler, E-204)",
            f"Occurred 45 s after incident #{jam.id} ended (first observed stop: Labeler, E-204)",
            f"Occurred 5 min after incident #{jam.id} ended (first observed stop: Labeler, E-204)",
        ]
    )
    for text in texts:
        assert not re.search(r"caus|root|because|due to", text, re.IGNORECASE)
