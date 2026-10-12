"""Role-based permissions: read for every role, write only for managers and admins."""

import pytest

from apps.organizations.models import Factory, Machine
from tests.helpers import ApiFactory, World

READ_ONLY_ROLES = [
    "production_supervisor",
    "machine_operator",
    "maintenance_technician",
    "quality_inspector",
    "analyst",
]
WRITE_ROLES = ["factory_manager", "platform_admin"]


def new_machine_payload(world: World) -> dict[str, object]:
    return {
        "line": world.line_a.id,
        "external_id": "M02",
        "name": "Rinser",
        "machine_type": "rinser",
        "position": 2,
        "nominal_speed_per_hour": 6000,
    }


@pytest.mark.parametrize("role", READ_ONLY_ROLES)
def test_read_only_roles_cannot_create_machines(world: World, api: ApiFactory, role: str) -> None:
    response = api(world.users[role]).post(
        "/api/v1/machines/", new_machine_payload(world), format="json"
    )

    assert response.status_code == 403
    assert not Machine.objects.filter(line=world.line_a, external_id="M02").exists()


@pytest.mark.parametrize("role", ["machine_operator", "analyst"])
def test_operator_and_analyst_cannot_edit_or_delete_machines(
    world: World, api: ApiFactory, role: str
) -> None:
    client = api(world.users[role])
    url = f"/api/v1/machines/{world.machine_a.id}/"

    assert client.patch(url, {"name": "Changed"}, format="json").status_code == 403
    assert client.put(url, new_machine_payload(world), format="json").status_code == 403
    assert client.delete(url).status_code == 403
    world.machine_a.refresh_from_db()
    assert world.machine_a.name == "Machine M01"


@pytest.mark.parametrize("role", READ_ONLY_ROLES)
def test_read_only_roles_can_read(world: World, api: ApiFactory, role: str) -> None:
    client = api(world.users[role])

    assert client.get("/api/v1/machines/").status_code == 200
    assert client.get(f"/api/v1/machines/{world.machine_a.id}/").status_code == 200
    assert client.get(f"/api/v1/factories/{world.factory_a.id}/").status_code == 200


@pytest.mark.parametrize("role", WRITE_ROLES)
def test_managers_and_admins_can_create_update_and_delete_machines(
    world: World, api: ApiFactory, role: str
) -> None:
    client = api(world.users[role])

    created = client.post("/api/v1/machines/", new_machine_payload(world), format="json")
    assert created.status_code == 201
    machine_id = created.json()["id"]

    updated = client.patch(f"/api/v1/machines/{machine_id}/", {"name": "Rinser 2"}, format="json")
    assert updated.status_code == 200
    assert updated.json()["name"] == "Rinser 2"

    deleted = client.delete(f"/api/v1/machines/{machine_id}/")
    assert deleted.status_code == 204
    assert not Machine.objects.filter(pk=machine_id).exists()


def test_manager_creates_factory_in_own_organization(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/factories/",
        # An `organization` in the body is ignored: it always comes from the membership.
        {"name": "Oran Plant", "timezone": "Africa/Algiers", "organization": world.other_org.id},
        format="json",
    )

    assert response.status_code == 201
    factory = Factory.objects.get(name="Oran Plant")
    assert factory.organization == world.demo_org


def test_limited_manager_cannot_create_factory(world: World, api: ApiFactory) -> None:
    response = api(world.users["limited_manager"]).post(
        "/api/v1/factories/", {"name": "New Plant", "timezone": "UTC"}, format="json"
    )

    assert response.status_code == 403
    assert not Factory.objects.filter(name="New Plant").exists()


def test_operator_cannot_create_factory(world: World, api: ApiFactory) -> None:
    response = api(world.users["machine_operator"]).post(
        "/api/v1/factories/", {"name": "New Plant", "timezone": "UTC"}, format="json"
    )

    assert response.status_code == 403
