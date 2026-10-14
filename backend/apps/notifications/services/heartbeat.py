"""Is the alert engine running? If Celery beat or the worker stops, no alert is ever
created and nothing would say so. Each periodic evaluation records a heartbeat, the
worker records every finished task, and /api/v1/health/ reports "stale" after
ALERT_ENGINE_STALE_SECONDS without a periodic heartbeat."""

from datetime import datetime
from typing import Any

from django.conf import settings

from apps.notifications.models import Heartbeat

PERIODIC = "periodic"
WORKER = "worker"


def beat(name: str, now: datetime) -> None:
    Heartbeat.objects.update_or_create(name=name, defaults={"at": now})


def engine_health(now: datetime) -> dict[str, Any]:
    beats = dict(Heartbeat.objects.values_list("name", "at"))
    last = beats.get(PERIODIC)
    stale = last is None or (now - last).total_seconds() > settings.ALERT_ENGINE_STALE_SECONDS
    return {
        "status": "stale" if stale else "ok",
        "last_heartbeat": last,
        "worker_last_task": beats.get(WORKER),
    }
