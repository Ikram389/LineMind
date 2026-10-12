from rest_framework.test import APIClient

from tests.helpers import TEST_PASSWORD, ApiFactory, World

TOKEN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
ME_URL = "/api/v1/me/"


def test_login_returns_access_and_refresh_tokens(world: World) -> None:
    response = APIClient().post(
        TOKEN_URL, {"email": "analyst@demo.test", "password": TEST_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}


def test_login_email_is_case_insensitive(world: World) -> None:
    response = APIClient().post(
        TOKEN_URL, {"email": "Analyst@Demo.TEST", "password": TEST_PASSWORD}, format="json"
    )

    assert response.status_code == 200


def test_login_with_wrong_password_is_rejected(world: World) -> None:
    response = APIClient().post(
        TOKEN_URL, {"email": "analyst@demo.test", "password": "wrong"}, format="json"
    )

    assert response.status_code == 401


def test_refresh_token_gives_new_access_token(world: World) -> None:
    client = APIClient()
    tokens = client.post(
        TOKEN_URL, {"email": "analyst@demo.test", "password": TEST_PASSWORD}, format="json"
    ).json()

    response = client.post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json")

    assert response.status_code == 200
    assert "access" in response.json()


def test_access_token_works_on_protected_endpoint(world: World) -> None:
    client = APIClient()
    access = client.post(
        TOKEN_URL, {"email": "analyst@demo.test", "password": TEST_PASSWORD}, format="json"
    ).json()["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    assert client.get(ME_URL).status_code == 200


def test_me_returns_organization_role_and_factories(world: World, api: ApiFactory) -> None:
    response = api(world.users["factory_manager"]).get(ME_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "factory_manager@demo.test"
    assert body["organization"] == {"id": world.demo_org.id, "name": "Demo Beverages"}
    assert body["role"] == "factory_manager"
    assert body["all_factories"] is True
    assert {f["id"] for f in body["factories"]} == {world.factory_a.id, world.factory_b.id}


def test_me_for_limited_user_lists_only_permitted_factory(world: World, api: ApiFactory) -> None:
    body = api(world.users["limited_operator"]).get(ME_URL).json()

    assert body["all_factories"] is False
    assert body["factories"] == [{"id": world.factory_a.id, "name": "Plant A", "timezone": "UTC"}]


def test_me_without_membership_has_no_organization(world: World, api: ApiFactory) -> None:
    body = api(world.users["no_membership"]).get(ME_URL).json()

    assert body["organization"] is None
    assert body["role"] is None
    assert body["factories"] == []


def test_me_requires_authentication(db: None) -> None:
    assert APIClient().get(ME_URL).status_code == 401


def test_invalid_token_is_rejected(db: None) -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

    assert client.get(ME_URL).status_code == 401
