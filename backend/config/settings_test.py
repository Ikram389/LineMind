"""Settings for pytest: everything in memory, so tests never need Redis."""

from config.settings import *  # noqa: F403

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = ""
CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
FRONTEND_URL = "http://linemind.test"
# Tests never call a real model: the fake provider is the default (tests script it).
ASSISTANT = {**ASSISTANT, "PROVIDER": "fake", "BASE_URL": "", "MODEL": "fake-model", "API_KEY": ""}  # noqa: F405
