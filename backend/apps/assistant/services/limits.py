"""Who may ask, how often, and how many at once.

- The assistant is off for an organization until a platform operator turns it on.
- Each user has a daily question limit (the organization's, or ASSISTANT_DAILY_QUESTIONS),
  counted from midnight in their factory's timezone. Replies that ended "busy" or
  "unreachable" don't count.
- At most ASSISTANT_MAX_CONCURRENT questions run at once (all processes): slots are cache
  keys with an expiry, so a crashed request frees its slot by itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from types import TracebackType
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

from apps.accounts.models import User
from apps.assistant.models import AssistantSettings, Message, MessageRole, MessageStatus
from apps.organizations.models import Organization
from apps.organizations.tenancy import permitted_factories

SLOT_SECONDS = 300  # longer than any question may take


class AllSlotsBusy(Exception):
    code = "busy"


def settings_for(organization: Organization) -> AssistantSettings:
    found = AssistantSettings.objects.filter(organization=organization).first()
    return found or AssistantSettings(organization=organization)


def is_enabled(organization: Organization) -> bool:
    return settings_for(organization).enabled


def daily_limit(organization: Organization) -> int:
    custom = settings_for(organization).daily_question_limit
    return custom if custom is not None else int(settings.ASSISTANT["DAILY_QUESTIONS"])


def user_timezone(user: User) -> ZoneInfo:
    factory = permitted_factories(user).order_by("pk").first()
    return ZoneInfo(factory.timezone if factory else "UTC")


def questions_today(user: User, now: datetime) -> int:
    tz = user_timezone(user)
    midnight = datetime.combine(now.astimezone(tz).date(), time(0), tzinfo=tz)
    # Replies that never reached the model (busy, unreachable) don't use up the quota.
    return (
        Message.objects.filter(
            conversation__user=user, role=MessageRole.ASSISTANT, created_at__gte=midnight
        )
        .exclude(status__in=[MessageStatus.BUSY, MessageStatus.UNREACHABLE])
        .count()
    )


class Slot:
    """`with Slot():` holds one of the concurrent-question slots or raises AllSlotsBusy."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit if limit is not None else int(settings.ASSISTANT["MAX_CONCURRENT"])
        self.token = uuid.uuid4().hex
        self.key: str | None = None

    def __enter__(self) -> Slot:
        for index in range(max(self.limit, 1)):
            key = f"assistant:slot:{index}"
            if cache.add(key, self.token, timeout=SLOT_SECONDS):
                self.key = key
                return self
        raise AllSlotsBusy

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.key and cache.get(self.key) == self.token:
            cache.delete(self.key)
