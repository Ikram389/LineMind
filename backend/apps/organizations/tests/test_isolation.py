"""Tenant isolation: users never see or change data outside their permitted factories."""

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Factory, Machine, ProductionLine
from tests.helpers import ApiFactory, World

# (endpoint, attribute of the demo object in World, attribute of the other-org object)
RESOURCES = [
    ("factories", "factory_a", "other_factory"),
    ("lines", "line_a", "other_line"),
    ("machines", "machine_a", "other_machine"),
]
MODELS = {"factories": Factory, "lines": ProductionLine, "machines": Machine}


def ids(response_json: list[dict[str, object]]) -> set[object]:
    return {item["id"] for item in response_json}


# --- Another organization --------------------------------------------------------------


@pytest.mark.parametrize(("resource", "demo_attr", "other_attr"), RESOURCES)
def test_other_organization_list_excludes_demo_data(
    world: World, api: ApiFactory, resource: str, demo_attr: str, other_attr: str
) -> None:
    response = api(world.users["other_manager"]).get(f"/api/v1/{resource}/")

    assert response.status_code == 200
    assert ids(response.json()) == {getattr(world, other_attr).id}


@pytest.mark.parametrize(("resource", "demo_attr", "other_attr"), RESOURCES)
@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_other_organization_cannot_access_demo_object_by_id(
    world: World, api: ApiFactory, resource: str, demo_attr: str, other_attr: str, method: str
) -> None:
    target = getattr(world, demo_attr)
    original_name = target.name
    client = api(world.users["other_manager"])
    url = f"/api/v1/{resource}/{target.id}/"

    if method == "get":
        response = client.get(url)
    else:
        response = getattr(client, method)(url, {"name": "Hacked"}, format="json")

    assert response.status_code == 404
    unchanged = MODELS[resource].objects.get(pk=target.pk)
    assert unchanged.name == original_name


def test_other_organization_cannot_create_line_in_demo_factory(
    world: World, api: ApiFactory
) -> None:
    response = api(world.users["other_manager"]).post(
        "/api/v1/lines/", {"factory": world.factory_a.id, "name": "Intruder"}, format="json"
    )

    assert response.status_code == 400
    assert "factory" in response.json()
    assert not ProductionLine.objects.filter(name="Intruder").exists()


def test_other_organization_cannot_create_machine_in_demo_line(
    world: World, api: ApiFactory
) -> None:
    response = api(world.users["other_manager"]).post(
        "/api/v1/machines/",
        {
            "line": world.line_a.id,
            "external_id": "X99",
            "name": "Intruder",
            "machine_type": "filler",
            "position": 9,
            "nominal_speed_per_hour": 1000,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "line" in response.json()
    assert not Machine.objects.filter(external_id="X99").exists()


def test_other_organization_cannot_move_own_machine_into_demo_line(
    world: World, api: ApiFactory
) -> None:
    response = api(world.users["other_manager"]).patch(
        f"/api/v1/machines/{world.other_machine.id}/", {"line": world.line_a.id}, format="json"
    )

    assert response.status_code == 400
    world.other_machine.refresh_from_db()
    assert world.other_machine.line_id == world.other_line.id


def test_other_organization_filter_by_demo_ids_returns_nothing(
    world: World, api: ApiFactory
) -> None:
    client = api(world.users["other_manager"])

    assert client.get(f"/api/v1/lines/?factory={world.factory_a.id}").json() == []
    assert client.get(f"/api/v1/machines/?line={world.line_a.id}").json() == []


# --- Same organization, limited to one factory -----------------------------------------


@pytest.mark.parametrize(
    ("resource", "visible_attr"),
    [("factories", "factory_a"), ("lines", "line_a"), ("machines", "machine_a")],
)
def test_limited_user_lists_only_permitted_factory(
    world: World, api: ApiFactory, resource: str, visible_attr: str
) -> None:
    response = api(world.users["limited_operator"]).get(f"/api/v1/{resource}/")

    assert response.status_code == 200
    assert ids(response.json()) == {getattr(world, visible_attr).id}


@pytest.mark.parametrize(
    ("resource", "hidden_attr"),
    [("factories", "factory_b"), ("lines", "line_b"), ("machines", "machine_b")],
)
def test_limited_user_cannot_retrieve_other_factory_data(
    world: World, api: ApiFactory, resource: str, hidden_attr: str
) -> None:
    target = getattr(world, hidden_attr)

    response = api(world.users["limited_operator"]).get(f"/api/v1/{resource}/{target.id}/")

    assert response.status_code == 404


def test_limited_user_filter_on_other_factory_returns_nothing(
    world: World, api: ApiFactory
) -> None:
    client = api(world.users["limited_operator"])

    assert client.get(f"/api/v1/lines/?factory={world.factory_b.id}").json() == []
    assert client.get(f"/api/v1/machines/?line={world.line_b.id}").json() == []


def test_limited_manager_cannot_edit_other_factory(world: World, api: ApiFactory) -> None:
    client = api(world.users["limited_manager"])

    patch = client.patch(f"/api/v1/factories/{world.factory_b.id}/", {"name": "X"}, format="json")
    create_line = client.post(
        "/api/v1/lines/", {"factory": world.factory_b.id, "name": "New"}, format="json"
    )

    assert patch.status_code == 404
    assert create_line.status_code == 400


def test_limited_manager_can_create_line_in_own_factory(world: World, api: ApiFactory) -> None:
    response = api(world.users["limited_manager"]).post(
        "/api/v1/lines/", {"factory": world.factory_a.id, "name": "Line A2"}, format="json"
    )

    assert response.status_code == 201


# --- No membership / not logged in -----------------------------------------------------


@pytest.mark.parametrize("resource", ["factories", "lines", "machines"])
def test_user_without_membership_is_forbidden(world: World, api: ApiFactory, resource: str) -> None:
    response = api(world.users["no_membership"]).get(f"/api/v1/{resource}/")

    assert response.status_code == 403


@pytest.mark.parametrize(("resource", "demo_attr", "other_attr"), RESOURCES)
def test_unauthenticated_requests_are_rejected(
    world: World, resource: str, demo_attr: str, other_attr: str
) -> None:
    client = APIClient()
    target = getattr(world, demo_attr)

    assert client.get(f"/api/v1/{resource}/").status_code == 401
    assert client.get(f"/api/v1/{resource}/{target.id}/").status_code == 401
    assert client.post(f"/api/v1/{resource}/", {}, format="json").status_code == 401
    assert client.delete(f"/api/v1/{resource}/{target.id}/").status_code == 401
