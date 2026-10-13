"""Tickets and the line WebSocket: authentication, tenant checks, delivery."""

import time
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.utils import timezone
from rest_framework.test import APIClient

from apps.live.routing import websocket_urlpatterns
from apps.live.tickets import issue_ticket, redeem_ticket
from apps.production.services.ingestion import ingest_event
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

APP = URLRouter(websocket_urlpatterns)


# --- Tickets ---------------------------------------------------------------------------


def test_ticket_requires_login(db: None) -> None:
    assert APIClient().post("/api/v1/ws-ticket/").status_code == 401


def test_ticket_is_issued_to_logged_in_member(world: World, api: ApiFactory) -> None:
    response = api(world.users["production_supervisor"]).post("/api/v1/ws-ticket/")

    assert response.status_code == 201
    assert response.json()["expires_in"] == 30
    assert redeem_ticket(response.json()["ticket"]) == world.users["production_supervisor"]


def test_ticket_is_single_use(world: World) -> None:
    ticket = issue_ticket(world.users["analyst"])

    assert redeem_ticket(ticket) == world.users["analyst"]
    assert redeem_ticket(ticket) is None


def test_ticket_expires(world: World) -> None:
    ticket = issue_ticket(world.users["analyst"], ttl_seconds=1)
    time.sleep(1.2)

    assert redeem_ticket(ticket) is None


def test_unknown_or_missing_ticket(db: None) -> None:
    assert redeem_ticket("not-a-ticket") is None
    assert redeem_ticket(None) is None


# --- WebSocket -------------------------------------------------------------------------


async def connect(line_id: int, ticket: str | None) -> tuple[WebsocketCommunicator, bool, int]:
    path = f"/ws/lines/{line_id}/" + (f"?ticket={ticket}" if ticket else "")
    communicator = WebsocketCommunicator(APP, path)
    connected, code = await communicator.connect()
    return communicator, connected, code


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_missing_ticket_is_refused(bottling: Bottling) -> None:
    communicator, connected, code = await connect(bottling.line.id, None)

    assert not connected
    assert code == 4401


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_used_ticket_is_refused(bottling: Bottling, world: World) -> None:
    ticket = issue_ticket(world.users["production_supervisor"])
    first, ok, _ = await connect(bottling.line.id, ticket)
    second, connected, code = await connect(bottling.line.id, ticket)

    assert ok
    assert not connected and code == 4401
    await first.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("user_key", ["other_manager", "limited_operator", "no_membership"])
async def test_users_outside_the_line_are_refused(
    bottling: Bottling, world: World, user_key: str
) -> None:
    ticket = issue_ticket(world.users[user_key])

    _, connected, code = await connect(bottling.line.id, ticket)

    assert not connected
    assert code == 4403


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_allowed_user_receives_state_change_after_ingestion(
    bottling: Bottling, world: World
) -> None:
    communicator, connected, _ = await connect(
        bottling.line.id, issue_ticket(world.users["production_supervisor"])
    )
    assert connected

    event = {
        "event_id": "6b1d6f0e-2f7c-4d2e-9d55-5b6f3f9f0a01",
        "machine_external_id": "M05",
        "event_type": "machine_stopped",
        "timestamp": (timezone.now() - timedelta(seconds=2)).isoformat(),
        "alarm_code": "E-204",
    }
    result = await sync_to_async(ingest_event)(bottling.api_key, event)
    assert result.status == "created"

    message = await communicator.receive_json_from(timeout=3)
    assert message["type"] == "machine_state_changed"
    assert message["line_id"] == bottling.line.id
    assert message["data"]["external_id"] == "M05"
    assert message["data"]["state"] == "stopped"
    assert message["data"]["alarm_code"] == "E-204"
    assert message["sent_at"].endswith("Z")
    await communicator.disconnect()
