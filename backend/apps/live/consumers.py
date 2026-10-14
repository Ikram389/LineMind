"""WebSocket consumers (server-to-browser only): one group per production line, and one
per user for their notifications."""

from typing import Any
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.models import User
from apps.live.broadcast import line_group, user_group
from apps.live.tickets import redeem_ticket
from apps.organizations.models import ProductionLine
from apps.organizations.tenancy import scope_to_user

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


def _can_view_line(user: User, line_id: int) -> bool:
    lines = scope_to_user(ProductionLine.objects.all(), user, "factory")
    return lines.filter(pk=line_id).exists()


class LineConsumer(AsyncJsonWebsocketConsumer):
    group_name: str | None = None

    async def connect(self) -> None:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        ticket = (query.get("ticket") or [None])[0]
        user = await database_sync_to_async(redeem_ticket)(ticket)
        if user is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        line_id = int(self.scope["url_route"]["kwargs"]["line_id"])
        # Same tenant rule as the REST API: other organizations and factories are refused.
        if not await database_sync_to_async(_can_view_line)(user, line_id):
            await self.close(code=CLOSE_FORBIDDEN)
            return

        self.group_name = line_group(line_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Messages only go from server to browser; anything received is ignored."""

    async def live_message(self, event: dict[str, Any]) -> None:
        await self.send_json(event["message"])


class UserConsumer(AsyncJsonWebsocketConsumer):
    """/ws/me/?ticket=…: the signed-in user's notification count, on every page."""

    group_name: str | None = None

    async def connect(self) -> None:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        ticket = (query.get("ticket") or [None])[0]
        user = await database_sync_to_async(redeem_ticket)(ticket)
        if user is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.group_name = user_group(user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Messages only go from server to browser; anything received is ignored."""

    async def live_message(self, event: dict[str, Any]) -> None:
        await self.send_json(event["message"])
