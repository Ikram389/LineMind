"""Creating and checking line API keys.

Key format: ``lm_<prefix>_<secret>``.
- ``prefix`` (8 hex characters) is stored in plain text and used to find the key.
- The whole key is stored only as a SHA-256 hash. A slow password hash is not
  needed: the secret is ~256 random bits, so it cannot be guessed, and every
  request must be checked quickly.
"""

import hashlib
import hmac
import secrets

from django.utils import timezone

from apps.organizations.models import ProductionLine
from apps.production.models import LineApiKey

KEY_PREFIX = "lm"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_line_api_key(line: ProductionLine, name: str) -> tuple[LineApiKey, str]:
    """Create a key and return it with its plain-text value (shown once, never stored)."""
    prefix = secrets.token_hex(4)
    while LineApiKey.objects.filter(prefix=prefix).exists():
        prefix = secrets.token_hex(4)
    raw_key = f"{KEY_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
    api_key = LineApiKey.objects.create(
        line=line, name=name, prefix=prefix, key_hash=hash_key(raw_key)
    )
    return api_key, raw_key


def find_active_key(raw_key: str) -> LineApiKey | None:
    """Return the active (not revoked) key matching `raw_key`, or None."""
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        return None
    api_key = (
        LineApiKey.objects.select_related("line")
        .filter(prefix=parts[1], revoked_at__isnull=True)
        .first()
    )
    if api_key is None or not hmac.compare_digest(api_key.key_hash, hash_key(raw_key)):
        return None
    return api_key


def mark_used(api_key: LineApiKey) -> None:
    now = timezone.now()
    LineApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
    api_key.last_used_at = now


def revoke(api_key: LineApiKey) -> None:
    LineApiKey.objects.filter(pk=api_key.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    api_key.refresh_from_db(fields=["revoked_at"])
