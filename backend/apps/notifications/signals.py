"""The worker's heartbeat: every finished task records when the worker last did something."""

import logging
from typing import Any

from celery.signals import task_postrun
from django.utils import timezone

from apps.notifications.services.heartbeat import WORKER, beat

logger = logging.getLogger(__name__)


@task_postrun.connect
def record_worker_heartbeat(**kwargs: Any) -> None:
    try:
        beat(WORKER, timezone.now())
    except Exception:  # the heartbeat must never break a task
        logger.exception("Could not record the worker heartbeat.")
