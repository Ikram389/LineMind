"""Shifts, breaks, products, cycle-time overrides, production orders: API, rules, audit."""

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.downtime.models import DowntimeReason
from apps.organizations.models import Factory
from apps.production.models import Product, ProductionOrder, Shift, ShiftBreak
from tests.helpers import ApiFactory, World
from tests.lines import Bottling


@pytest.fixture
def shift(world: World) -> Shift:
    return Shift.objects.create(
        factory=world.factory_a, name="Morning", start_time=time(6), end_time=time(14)
    )


@pytest.fixture
def product(world: World) -> Product:
    return Product.objects.create(
        organization=world.demo_org, name="Water 0.5 L", sku="W050", ideal_cycle_time_seconds="0.6"
    )


def order_payload(world: World, product: Product, start: str, end: str) -> dict[str, object]:
    return {
        "line": world.line_a.id,
        "product": product.id,
        "planned_quantity": 1000,
        "scheduled_start": start,
        "scheduled_end": end,
    }


# --- Permissions and isolation ---------------------------------------------------------


def test_manager_creates_shift_and_break(world: World, api: ApiFactory) -> None:
    client = api(world.users["factory_manager"])

    shift = client.post(
        "/api/v1/shifts/",
        {
            "factory": world.factory_a.id,
            "name": "Night",
            "start_time": "22:00",
            "end_time": "06:00",
        },
        format="json",
    )
    assert shift.status_code == 201
    brk = client.post(
        "/api/v1/shift-breaks/",
        {"shift": shift.json()["id"], "name": "Meal", "start_time": "02:00", "end_time": "02:30"},
        format="json",
    )
    assert brk.status_code == 201
    listed = client.get(f"/api/v1/shifts/{shift.json()['id']}/").json()
    assert [b["name"] for b in listed["breaks"]] == ["Meal"]


@pytest.mark.parametrize("role", ["machine_operator", "analyst", "production_supervisor"])
def test_other_roles_cannot_edit_shifts(
    world: World, api: ApiFactory, shift: Shift, role: str
) -> None:
    client = api(world.users[role])

    assert client.get("/api/v1/shifts/").status_code == 200
    assert (
        client.patch(f"/api/v1/shifts/{shift.id}/", {"name": "X"}, format="json").status_code == 403
    )
    assert (
        client.post(
            "/api/v1/shifts/",
            {
                "factory": world.factory_a.id,
                "name": "N",
                "start_time": "22:00",
                "end_time": "06:00",
            },
            format="json",
        ).status_code
        == 403
    )


def test_other_organization_cannot_see_or_touch_planning_data(
    world: World, api: ApiFactory, shift: Shift, product: Product
) -> None:
    client = api(world.users["other_manager"])

    assert client.get("/api/v1/shifts/").json() == []
    assert client.get(f"/api/v1/shifts/{shift.id}/").status_code == 404
    assert (
        client.patch(f"/api/v1/shifts/{shift.id}/", {"name": "X"}, format="json").status_code == 404
    )
    assert client.get("/api/v1/products/").json() == []
    assert client.get(f"/api/v1/products/{product.id}/").status_code == 404
    response = client.post(
        "/api/v1/production-orders/",
        order_payload(world, product, "2026-10-13T06:00:00Z", "2026-10-13T14:00:00Z"),
        format="json",
    )
    assert response.status_code == 400  # line and product are not theirs
    assert not ProductionOrder.objects.exists()


def test_limited_user_sees_only_their_factory_shifts(
    world: World, api: ApiFactory, shift: Shift
) -> None:
    other = Shift.objects.create(
        factory=world.factory_b, name="B shift", start_time=time(6), end_time=time(14)
    )
    ids = {s["id"] for s in api(world.users["limited_operator"]).get("/api/v1/shifts/").json()}

    assert ids == {shift.id}
    assert other.id not in ids


def test_limited_manager_cannot_change_products(
    world: World, api: ApiFactory, product: Product
) -> None:
    client = api(world.users["limited_manager"])

    assert client.get("/api/v1/products/").status_code == 200
    response = client.patch(
        f"/api/v1/products/{product.id}/", {"ideal_cycle_time_seconds": "0.5"}, format="json"
    )
    assert response.status_code == 403


def test_unauthenticated_gets_401() -> None:
    for url in ["/api/v1/shifts/", "/api/v1/products/", "/api/v1/production-orders/"]:
        assert APIClient().get(url).status_code == 401


# --- Validation ------------------------------------------------------------------------


def test_break_outside_shift_is_rejected(world: World, api: ApiFactory, shift: Shift) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/shift-breaks/",
        {"shift": shift.id, "start_time": "13:45", "end_time": "14:15"},
        format="json",
    )

    assert response.status_code == 400


def test_zero_length_shift_is_rejected(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/shifts/",
        {"factory": world.factory_a.id, "name": "X", "start_time": "06:00", "end_time": "06:00"},
        format="json",
    )

    assert response.status_code == 400


def test_overlapping_orders_are_rejected(world: World, api: ApiFactory, product: Product) -> None:
    client = api(world.users["factory_manager"])
    first = client.post(
        "/api/v1/production-orders/",
        order_payload(world, product, "2026-10-13T06:00:00Z", "2026-10-13T14:00:00Z"),
        format="json",
    )
    overlapping = client.post(
        "/api/v1/production-orders/",
        order_payload(world, product, "2026-10-13T13:00:00Z", "2026-10-13T20:00:00Z"),
        format="json",
    )
    adjacent = client.post(
        "/api/v1/production-orders/",
        order_payload(world, product, "2026-10-13T14:00:00Z", "2026-10-13T20:00:00Z"),
        format="json",
    )

    assert first.status_code == 201
    assert overlapping.status_code == 400
    assert "Overlaps" in str(overlapping.json())
    assert adjacent.status_code == 201


def test_counting_machine_must_belong_to_the_line(world: World, api: ApiFactory) -> None:
    client = api(world.users["factory_manager"])

    wrong = client.patch(
        f"/api/v1/lines/{world.line_a.id}/", {"counting_machine": world.machine_b.id}, format="json"
    )
    right = client.patch(
        f"/api/v1/lines/{world.line_a.id}/", {"counting_machine": world.machine_a.id}, format="json"
    )

    assert wrong.status_code == 400
    assert right.status_code == 200
    world.line_a.refresh_from_db()
    assert world.line_a.output_machine() == world.machine_a


def test_line_without_counting_machine_uses_last_machine(bottling: Bottling) -> None:
    assert bottling.line.output_machine().external_id == "M06"


# --- Audit -----------------------------------------------------------------------------


def test_configuration_changes_are_audited(world: World, api: ApiFactory, shift: Shift) -> None:
    client = api(world.users["factory_manager"])

    client.patch(f"/api/v1/shifts/{shift.id}/", {"end_time": "14:30"}, format="json")
    client.patch(
        f"/api/v1/factories/{world.factory_a.id}/", {"stale_after_seconds": 90}, format="json"
    )
    new_line = client.post(
        "/api/v1/lines/", {"factory": world.factory_a.id, "name": "Line A9"}, format="json"
    ).json()
    client.delete(f"/api/v1/lines/{new_line['id']}/")

    entries = list(AuditLog.objects.order_by("id"))
    assert [e.action for e in entries] == [
        "shift.updated",
        "factory.updated",
        "productionline.created",
        "productionline.deleted",
    ]
    assert entries[0].before["end_time"] == "14:00:00"
    assert entries[0].after["end_time"] == "14:30:00"
    assert entries[1].before["stale_after_seconds"] == 60
    assert entries[1].after["stale_after_seconds"] == 90
    assert entries[3].after is None
    assert all(e.user == world.users["factory_manager"] for e in entries)
    assert all(e.organization == world.demo_org for e in entries)


def test_refused_delete_writes_no_audit_entry(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).delete(
        f"/api/v1/factories/{world.factory_a.id}/"
    )

    assert response.status_code == 409
    assert not AuditLog.objects.exists()


# --- Downtime shift filter -------------------------------------------------------------


def test_downtime_events_can_be_filtered_by_shift(
    bottling: Bottling, send: Callable[..., str], world: World, api: ApiFactory
) -> None:
    factory: Factory = bottling.line.factory  # UTC
    factory.stale_after_seconds = 12 * 3600  # sparse hand-made events: no telemetry gaps
    factory.save()
    morning = Shift.objects.create(
        factory=factory, name="Morning", start_time=time(6), end_time=time(14)
    )
    day = datetime(2026, 10, 12, tzinfo=UTC)
    send("M05", "machine_stopped", day + timedelta(hours=7))  # in the morning shift
    send("M05", "machine_started", day + timedelta(hours=7, minutes=5))
    send("M05", "machine_stopped", day + timedelta(hours=15))  # afternoon
    send("M05", "machine_started", day + timedelta(hours=15, minutes=5))
    client = api(world.users["analyst"])

    morning_events = client.get(
        "/api/v1/downtime-events/",
        {"shift": morning.id, "date": "2026-10-12"},
    ).json()["results"]

    assert [e["started_at"][:16] for e in morning_events] == ["2026-10-12T07:00"]
    assert client.get("/api/v1/downtime-events/", {"shift": morning.id}).status_code == 400
    other_factory_shift = Shift.objects.create(
        factory=world.other_factory, name="X", start_time=time(6), end_time=time(14)
    )
    assert (
        client.get(
            "/api/v1/downtime-events/", {"shift": other_factory_shift.id, "date": "2026-10-12"}
        ).status_code
        == 400
    )


# --- seed_demo -------------------------------------------------------------------------


def test_seed_demo_creates_planning_data_once(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USER_PASSWORD", "demo-password-for-tests")

    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    shifts = Shift.objects.filter(factory__name="Algiers Plant").order_by("start_time")
    assert [(s.name, s.start_time, s.end_time) for s in shifts] == [
        ("Morning", time(6), time(14)),
        ("Afternoon", time(14), time(22)),
        ("Night", time(22), time(6)),
    ]
    assert ShiftBreak.objects.filter(shift__in=shifts).count() == 3
    assert sorted(Product.objects.values_list("name", "ideal_cycle_time_seconds")) == [
        ("Water 0.5 L", Decimal("0.600")),
        ("Water 1.5 L", Decimal("0.900")),
    ]
    order = ProductionOrder.objects.get()
    algiers = ZoneInfo("Africa/Algiers")
    assert order.product.sku == "W050"
    assert order.line.name == "Bottling Line 1"
    assert (
        order.scheduled_start.astimezone(algiers).date()
        == timezone.now().astimezone(algiers).date()
    )
    assert order.scheduled_start.astimezone(algiers).time() == time(6)
    assert order.scheduled_end - order.scheduled_start == timedelta(days=1)
    changeovers = DowntimeReason.objects.filter(factory__name="Algiers Plant", is_changeover=True)
    assert [(r.code, r.name) for r in changeovers] == [("PLAN-CHANGEOVER", "Product changeover")]
