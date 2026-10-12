"""Line API keys: hashed storage, the management command and authentication."""

from collections.abc import Callable
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.production.models import LineApiKey
from apps.production.services.api_keys import create_line_api_key, hash_key, revoke
from apps.production.tests.events import make_event
from tests.helpers import ApiFactory, World

EVENTS_URL = "/api/v1/events/"
KeyClient = Callable[[str | None], APIClient]


def test_key_is_stored_only_as_hash(world: World) -> None:
    api_key, raw_key = create_line_api_key(world.line_a, "Simulator")

    stored = LineApiKey.objects.filter(pk=api_key.pk).values().get()
    assert raw_key not in [str(value) for value in stored.values()]
    assert stored["key_hash"] == hash_key(raw_key)
    assert raw_key.startswith(f"lm_{api_key.prefix}_")


def test_command_prints_a_working_key(world: World, key_client: KeyClient) -> None:
    out = StringIO()
    call_command("create_line_api_key", str(world.line_a.id), "Simulator", stdout=out)

    raw_key = out.getvalue().strip().splitlines()[-1]
    response = key_client(raw_key).post(EVENTS_URL, make_event(), format="json")
    assert response.status_code == 201
    assert LineApiKey.objects.get(name="Simulator").line == world.line_a


def test_command_with_unknown_line_fails(db: None) -> None:
    with pytest.raises(CommandError, match="No production line"):
        call_command("create_line_api_key", "999999", "Simulator", stdout=StringIO())


@pytest.mark.parametrize(
    "header",
    [
        None,  # no header at all
        "Api-Key",  # keyword without key
        "Api-Key lm_deadbeef_wrongsecret",  # unknown key
        "Api-Key not-a-key",  # wrong format
        "Api-Key a b",  # too many parts
    ],
)
def test_missing_or_invalid_key_is_refused(world: World, header: str | None) -> None:
    client = APIClient()
    if header is not None:
        client.credentials(HTTP_AUTHORIZATION=header)

    response = client.post(EVENTS_URL, make_event(), format="json")

    assert response.status_code == 401


def test_wrong_secret_with_valid_prefix_is_refused(
    world: World, key_client: KeyClient, line_a_key: str
) -> None:
    tampered = line_a_key[:-4] + "XXXX"

    response = key_client(tampered).post(EVENTS_URL, make_event(), format="json")

    assert response.status_code == 401


def test_revoked_key_is_refused(world: World, key_client: KeyClient) -> None:
    api_key, raw_key = create_line_api_key(world.line_a, "Old")
    revoke(api_key)

    response = key_client(raw_key).post(EVENTS_URL, make_event(), format="json")

    assert response.status_code == 401


def test_user_jwt_cannot_send_events(world: World, api: ApiFactory) -> None:
    response = api(world.users["platform_admin"]).post(EVENTS_URL, make_event(), format="json")

    assert response.status_code == 401


def test_api_key_cannot_read_user_endpoints(world: World, sender: APIClient) -> None:
    assert sender.get("/api/v1/machines/").status_code == 401
    assert sender.get(f"/api/v1/lines/{world.line_a.id}/status/").status_code == 401


def test_last_used_at_is_updated(world: World, key_client: KeyClient) -> None:
    api_key, raw_key = create_line_api_key(world.line_a, "Simulator")
    assert api_key.last_used_at is None

    key_client(raw_key).post(EVENTS_URL, make_event(), format="json")

    api_key.refresh_from_db()
    assert api_key.last_used_at is not None
