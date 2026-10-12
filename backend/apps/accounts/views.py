from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import MeSerializer


class MeView(APIView):
    """GET /api/v1/me/ — who am I, and which factories can I see?"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data)
