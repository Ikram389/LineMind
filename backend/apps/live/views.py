from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.live.tickets import TICKET_TTL_SECONDS, issue_ticket
from apps.organizations.permissions import HasMembership


class WsTicketView(APIView):
    """POST /api/v1/ws-ticket/ -> a single-use ticket for opening a WebSocket."""

    permission_classes = [IsAuthenticated, HasMembership]

    def post(self, request: Request) -> Response:
        return Response(
            {"ticket": issue_ticket(request.user), "expires_in": TICKET_TTL_SECONDS},
            status=status.HTTP_201_CREATED,
        )
