"""DRF authentication and permission for line API keys.

Header: ``Authorization: Api-Key <key>``. On success, ``request.auth`` is the
LineApiKey and ``request.user`` is anonymous (a key is not a person).
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.production.models import LineApiKey
from apps.production.services.api_keys import find_active_key, mark_used

KEYWORD = "Api-Key"


class LineApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[AnonymousUser, LineApiKey] | None:
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != KEYWORD.lower().encode():
            return None  # no key given; the permission check then answers 401
        if len(parts) != 2:
            raise AuthenticationFailed(
                "Invalid Api-Key header. Use 'Authorization: Api-Key <key>'."
            )
        try:
            raw_key = parts[1].decode()
        except UnicodeDecodeError:
            raise AuthenticationFailed("Invalid API key.") from None

        api_key = find_active_key(raw_key)
        if api_key is None:
            raise AuthenticationFailed("Invalid or revoked API key.")
        mark_used(api_key)
        return AnonymousUser(), api_key

    def authenticate_header(self, request: Request) -> str:
        # Makes DRF answer 401 (not 403) when the key is missing or wrong.
        return KEYWORD


class HasLineApiKey(BasePermission):
    message = "A valid line API key is required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.auth, LineApiKey)
