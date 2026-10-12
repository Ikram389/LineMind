from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.models import (
    Factory,
    Machine,
    Membership,
    Organization,
    ProductionLine,
    Role,
)

pytestmark = pytest.mark.django_db

DEMO_PASSWORD = "demo-password-for-tests"


@pytest.fixture
def demo_password(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DEMO_USER_PASSWORD", DEMO_PASSWORD)
    return DEMO_PASSWORD


def seed() -> None:
    call_command("seed_demo", stdout=StringIO())


def row_counts() -> dict[str, int]:
    return {
        model.__name__: model.objects.count()
        for model in (Organization, Factory, ProductionLine, Machine, User, Membership)
    }


def test_seed_demo_runs_twice_without_duplicates(demo_password: str) -> None:
    seed()
    first = row_counts()
    seed()

    assert row_counts() == first
    assert first == {
        "Organization": 2,
        "Factory": 2,
        "ProductionLine": 2,
        "Machine": 9,
        "User": len(Role) + 1,
        "Membership": len(Role) + 1,
    }


def test_seed_demo_creates_demo_line_with_six_machines_in_order(demo_password: str) -> None:
    seed()

    factory = Factory.objects.get(organization__name="Demo Beverages", name="Algiers Plant")
    assert factory.timezone == "Africa/Algiers"
    machines = Machine.objects.filter(line__factory=factory, line__name="Bottling Line 1")
    assert [(m.position, m.external_id, m.name) for m in machines] == [
        (1, "M01", "Bottle feeder"),
        (2, "M02", "Rinser"),
        (3, "M03", "Filler"),
        (4, "M04", "Capper"),
        (5, "M05", "Labeler"),
        (6, "M06", "Packer"),
    ]
    assert {m.nominal_speed_per_hour for m in machines} == {6000}


def test_seed_demo_creates_one_user_per_role(demo_password: str) -> None:
    seed()

    roles = Membership.objects.filter(organization__name="Demo Beverages").values_list(
        "role", flat=True
    )
    assert sorted(roles) == sorted(role.value for role in Role)
    assert User.objects.get(email="analyst@demo-beverages.test").check_password(DEMO_PASSWORD)


def test_seed_demo_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_USER_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="DEMO_USER_PASSWORD"):
        seed()
    assert Organization.objects.count() == 0


def test_demo_user_logs_in_and_sees_only_own_factory_and_machines(demo_password: str) -> None:
    seed()
    client = APIClient()

    login = client.post(
        "/api/v1/auth/token/",
        {"email": "machine_operator@demo-beverages.test", "password": DEMO_PASSWORD},
        format="json",
    )
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

    factories = client.get("/api/v1/factories/").json()
    machines = client.get("/api/v1/machines/").json()

    assert [f["name"] for f in factories] == ["Algiers Plant"]
    assert [m["external_id"] for m in machines] == ["M01", "M02", "M03", "M04", "M05", "M06"]
