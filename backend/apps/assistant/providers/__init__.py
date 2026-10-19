"""Model providers. `get_provider()` builds the one configured in settings.ASSISTANT.

Tests replace it with `use_provider(FakeProvider([...]))` (see tests/conftest.py).
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings

from apps.assistant.providers.base import ChatProvider
from apps.assistant.providers.fake import FakeProvider
from apps.assistant.providers.openai_compatible import OpenAICompatibleProvider

_override: ChatProvider | None = None


def use_provider(provider: ChatProvider | None) -> None:
    """Force a provider (tests and the evaluation). None goes back to the settings."""
    global _override
    _override = provider


def current_override() -> ChatProvider | None:
    return _override


def config() -> dict[str, Any]:
    return dict(settings.ASSISTANT)


def build_provider(**overrides: Any) -> ChatProvider:
    """A provider from settings, with optional overrides (e.g. model= for the evaluation)."""
    cfg = {**config(), **{k.upper(): v for k, v in overrides.items()}}
    if cfg["PROVIDER"] == "fake":
        return FakeProvider(model=cfg.get("MODEL") or "fake-model")
    extra: dict[str, Any] = {}
    if cfg.get("EXTRA_PARAMS"):
        try:
            extra = json.loads(cfg["EXTRA_PARAMS"])
        except ValueError:
            extra = {}
    return OpenAICompatibleProvider(
        base_url=cfg["BASE_URL"],
        model=cfg["MODEL"],
        api_key=cfg["API_KEY"],
        temperature=float(cfg["TEMPERATURE"]),
        timeout_seconds=float(cfg["TIMEOUT_SECONDS"]),
        extra_params=extra if isinstance(extra, dict) else {},
    )


def get_provider() -> ChatProvider:
    return _override if _override is not None else build_provider()
