"""Short-lived, single-use WebSocket tickets.

Browsers cannot send an Authorization header when opening a WebSocket, and a
JWT in the URL could end up in logs. So the browser first asks for a ticket
(with its JWT) and connects with ?ticket=<ticket>. A ticket is valid for
TICKET_TTL_SECONDS and can be used once.
"""

import secrets

from django.core.cache import cache

from apps.accounts.models import User

TICKET_TTL_SECONDS = 30
_PREFIX = "live:ws-ticket:"


def issue_ticket(user: User, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
    ticket = secrets.token_urlsafe(32)
    cache.set(_PREFIX + ticket, user.pk, timeout=ttl_seconds)
    return ticket


def redeem_ticket(ticket: str | None) -> User | None:
    """The ticket's user, or None if it is missing, unknown, expired or already used."""
    if not ticket:
        return None
    key = _PREFIX + ticket
    user_id = cache.get(key)
    # delete() succeeds only once, so two connections can never use the same ticket.
    if user_id is None or not cache.delete(key):
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()
