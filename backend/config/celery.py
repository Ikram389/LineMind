"""Celery application: `celery -A config worker` and `celery -A config beat` (compose.yaml)."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("linemind")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
