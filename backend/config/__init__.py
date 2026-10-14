# Load Celery with Django, so @shared_task functions use this project's app.
from config.celery import app as celery_app

__all__ = ("celery_app",)
