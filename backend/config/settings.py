"""Django settings for LineMind.

All secrets and environment-specific values come from environment variables
(see .env.example at the repository root). Nothing secret is hard-coded here.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    # daphne first: makes `manage.py runserver` serve HTTP and WebSockets through ASGI.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.organizations",
    "apps.production",
    "apps.audit",
    "apps.downtime",
    "apps.quality",
    "apps.notifications",
    "apps.maintenance",
    "apps.analytics",
    "apps.live",
    "apps.assistant",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# All timestamps are stored as timezone-aware UTC (CLAUDE.md rule 4).
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Every endpoint requires a valid JWT unless it explicitly opts out (like /health/).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# Live updates (apps/live): Redis for the channel layer and the cache (tickets, throttling).
# Without REDIS_URL everything stays in this process (fine for a single dev server).
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Background jobs (Celery, apps/notifications/tasks.py). Redis database 1 is the broker.
# Without REDIS_URL (tests, a plain dev server) tasks run immediately in the calling process.
CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL", REDIS_URL.rsplit("/", 1)[0] + "/1" if REDIS_URL else ""
)
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "evaluate-alerts": {"task": "notifications.evaluate_periodic", "schedule": 30.0},
}
# The alert engine is "stale" when its periodic evaluation has not run for this long.
ALERT_ENGINE_STALE_SECONDS = 120

# Email (alerts). In development Mailpit catches every message: http://localhost:8025
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "LineMind <alerts@linemind.local>")
# Links in emails point to the web app.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# Event ingestion (apps/production/services/ingestion.py)
EVENT_MAX_FUTURE_SECONDS = 300  # reject events stamped more than 5 minutes in the future
EVENT_BATCH_MAX_SIZE = 500

# Downtime CSV export (apps/downtime/views.py): larger requests must be narrowed.
DOWNTIME_EXPORT_MAX_ROWS = 50_000
QUALITY_EXPORT_MAX_ROWS = 50_000
MAINTENANCE_EXPORT_MAX_ROWS = 50_000

# Tokens are signed with SECRET_KEY (the simplejwt default).
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- AI production assistant (step 10c) --------------------------------------------------
# Any OpenAI-compatible chat server with tool calling: Groq for development, a local server
# (e.g. Ollama) in production. Switching provider = changing these variables only.
ASSISTANT = {
    "PROVIDER": os.environ.get("ASSISTANT_PROVIDER") or "openai_compatible",  # or "fake"
    "BASE_URL": os.environ.get("ASSISTANT_BASE_URL", "").rstrip("/"),
    "MODEL": os.environ.get("ASSISTANT_MODEL", ""),
    "API_KEY": os.environ.get("ASSISTANT_API_KEY", ""),
    "TEMPERATURE": float(os.environ.get("ASSISTANT_TEMPERATURE") or "0.1"),
    "CONTEXT_TOKENS": int(os.environ.get("ASSISTANT_CONTEXT_TOKENS") or "8192"),
    "TIMEOUT_SECONDS": int(os.environ.get("ASSISTANT_TIMEOUT_SECONDS") or "60"),
    "MAX_CONCURRENT": int(os.environ.get("ASSISTANT_MAX_CONCURRENT") or "2"),
    "MAX_TOOL_CALLS": int(os.environ.get("ASSISTANT_MAX_TOOL_CALLS") or "8"),
    "DAILY_QUESTIONS": int(os.environ.get("ASSISTANT_DAILY_QUESTIONS") or "30"),
    # Extra JSON merged into every chat request, e.g. {"reasoning_effort": "low"} for gpt-oss.
    "EXTRA_PARAMS": os.environ.get("ASSISTANT_EXTRA_PARAMS", ""),
}
