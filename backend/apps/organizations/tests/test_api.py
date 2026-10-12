"""API behaviour: validation, filters, ordering and protected deletes."""

import pytest

from apps.organizations.models import ProductionLine
from apps.organizations.oee_settings import DEFAULT_OEE_SETTINGS
from tests.helpers import ApiFactory, World, create_machine


def machine_payload(world: World, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "line": world.line_a.id,
        "external_id": "M02",
        "name": "Rinser",
        "machine_type": "rinser",
        "position": 2,
        "nominal_speed_per_hour": 6000,
    }
    payload.update(overrides)
    return payload


# --- Machine uniqueness through the API ------------------------------------------------


def test_duplicate_external_id_in_line_returns_400(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/machines/", machine_payload(world, external_id="M01"), format="json"
    )

    assert response.status_code == 400


def test_duplicate_position_in_line_returns_400(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/machines/", machine_payload(world, position=1), format="json"
    )

    assert response.status_code == 400


def test_same_external_id_on_other_line_is_allowed(world: World, api: ApiFactory) -> None:
    line = ProductionLine.objects.create(factory=world.factory_a, name="Line A2")

    response = api(world.users["factory_manager"]).post(
        "/api/v1/machines/",
        machine_payload(world, line=line.id, external_id="M01", position=1),
        format="json",
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "overrides", [{"position": 0}, {"nominal_speed_per_hour": 0}, {"external_id": ""}]
)
def test_invalid_machine_values_return_400(
    world: World, api: ApiFactory, overrides: dict[str, object]
) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/machines/", machine_payload(world, **overrides), format="json"
    )

    assert response.status_code == 400


# --- Factory validation ----------------------------------------------------------------


def test_partial_oee_settings_are_merged_with_defaults(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/factories/",
        {
            "name": "Oran",
            "timezone": "Africa/Algiers",
            "oee_settings": {"minimum_stop_seconds": 10},
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["oee_settings"] == {**DEFAULT_OEE_SETTINGS, "minimum_stop_seconds": 10}


def test_factory_without_oee_settings_gets_defaults(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/factories/", {"name": "Oran", "timezone": "Africa/Algiers"}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["oee_settings"] == DEFAULT_OEE_SETTINGS


@pytest.mark.parametrize(
    "oee_settings",
    [
        {"unknown_rule": True},
        {"planned_stops_excluded": "yes"},
        {"minimum_stop_seconds": True},
        {"minimum_stop_seconds": -1},
        ["not", "an", "object"],
    ],
)
def test_invalid_oee_settings_return_400(
    world: World, api: ApiFactory, oee_settings: object
) -> None:
    response = api(world.users["factory_manager"]).patch(
        f"/api/v1/factories/{world.factory_a.id}/", {"oee_settings": oee_settings}, format="json"
    )

    assert response.status_code == 400
    assert "oee_settings" in response.json()


def test_invalid_timezone_returns_400(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).patch(
        f"/api/v1/factories/{world.factory_a.id}/", {"timezone": "Mars/Olympus"}, format="json"
    )

    assert response.status_code == 400
    assert "timezone" in response.json()


def test_duplicate_factory_name_in_organization_returns_400(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).post(
        "/api/v1/factories/", {"name": "Plant A", "timezone": "UTC"}, format="json"
    )

    assert response.status_code == 400
    assert "name" in response.json()


def test_factory_name_may_repeat_across_organizations(world: World, api: ApiFactory) -> None:
    response = api(world.users["other_manager"]).post(
        "/api/v1/factories/", {"name": "Plant A", "timezone": "UTC"}, format="json"
    )

    assert response.status_code == 201


# --- Filters and ordering --------------------------------------------------------------


def test_lines_filtered_by_factory(world: World, api: ApiFactory) -> None:
    response = api(world.users["analyst"]).get(f"/api/v1/lines/?factory={world.factory_b.id}")

    assert [line["id"] for line in response.json()] == [world.line_b.id]


def test_machines_filtered_by_line_and_ordered_by_position(world: World, api: ApiFactory) -> None:
    third = create_machine(world.line_a, "M03", 3)
    second = create_machine(world.line_a, "M02", 2)

    response = api(world.users["analyst"]).get(f"/api/v1/machines/?line={world.line_a.id}")

    assert [m["id"] for m in response.json()] == [world.machine_a.id, second.id, third.id]


@pytest.mark.parametrize("url", ["/api/v1/machines/?line=abc", "/api/v1/lines/?factory=1x"])
def test_non_integer_filter_returns_400(world: World, api: ApiFactory, url: str) -> None:
    assert api(world.users["analyst"]).get(url).status_code == 400


# --- Protected deletes -----------------------------------------------------------------


def test_deleting_factory_with_lines_returns_409(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).delete(
        f"/api/v1/factories/{world.factory_a.id}/"
    )

    assert response.status_code == 409
    assert ProductionLine.objects.filter(pk=world.line_a.pk).exists()


def test_deleting_line_with_machines_returns_409(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).delete(f"/api/v1/lines/{world.line_a.id}/")

    assert response.status_code == 409


def test_deleting_empty_factory_succeeds(world: World, api: ApiFactory) -> None:
    client = api(world.users["factory_manager"])
    created = client.post("/api/v1/factories/", {"name": "Empty", "timezone": "UTC"}, format="json")

    response = client.delete(f"/api/v1/factories/{created.json()['id']}/")

    assert response.status_code == 204
