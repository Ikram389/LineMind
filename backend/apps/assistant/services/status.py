"""Is the configured model usable? Checked on first use and by the status endpoint.

The probe (reachability + one tiny tool call) is cached: 10 minutes when it worked, one
minute when it failed, so a fixed key or network is noticed quickly without spending
the free tier's requests on every question.
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.assistant.providers import config, get_provider
from apps.assistant.providers.base import ChatProvider

OK_SECONDS = 600
FAILED_SECONDS = 60


def _key(provider: ChatProvider) -> str:
    cfg = config()
    raw = f"{provider.name}|{provider.model}|{cfg.get('BASE_URL')}|{cfg.get('API_KEY')}"
    return "assistant:probe:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def model_status(provider: ChatProvider | None = None, refresh: bool = False) -> dict[str, Any]:
    provider = provider or get_provider()
    key = _key(provider)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached
    result = provider.probe()
    status = {
        "provider": provider.name,
        "model": result.model,
        "reachable": result.reachable,
        "tool_calling": result.tool_calling,
        "error": result.error,
        "checked_at": timezone.now().isoformat(),
    }
    usable = result.reachable and result.tool_calling is not False
    cache.set(key, status, OK_SECONDS if usable else FAILED_SECONDS)
    return status
