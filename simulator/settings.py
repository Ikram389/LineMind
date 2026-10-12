"""Settings from environment variables (set in compose.yaml from your .env)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str | None
    queue_path: Path


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        api_url=env.get("LINEMIND_API_URL", "http://backend:8000").rstrip("/"),
        api_key=env.get("SIMULATOR_API_KEY") or None,
        queue_path=Path(env.get("SIMULATOR_QUEUE_PATH", "data/queue.sqlite")),
    )
