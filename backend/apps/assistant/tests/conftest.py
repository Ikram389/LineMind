"""Assistant test fixtures. No test ever calls a real model: `fake(...)` scripts one."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, time
from typing import Any

import pytest

from apps.assistant.models import AssistantSettings, Conversation
from apps.assistant.providers import use_provider
from apps.assistant.providers.fake import FakeProvider, FakeTurn
from apps.assistant.tools.core import ToolContext
from apps.production.models import Shift
from tests.helpers import World
from tests.lines import Bottling

# labeler_jam.jsonl runs 10:00–10:15 UTC on Mon 12 Oct 2026; Plant B is in UTC.
JAM_START = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
JAM_END = datetime(2026, 10, 12, 10, 15, tzinfo=UTC)
AFTER_JAM = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_real_model() -> Iterator[None]:
    use_provider(FakeProvider([FakeTurn(text="(no script)")]))
    yield
    use_provider(None)


@pytest.fixture
def fake() -> Callable[..., FakeProvider]:
    """fake(FakeTurn(...), ...): the model's next replies, in order."""

    def _fake(*turns: FakeTurn, **kwargs: Any) -> FakeProvider:
        provider = FakeProvider(turns, **kwargs)
        use_provider(provider)
        return provider

    return _fake


@pytest.fixture
def enabled(world: World) -> AssistantSettings:
    return AssistantSettings.objects.create(organization=world.demo_org, enabled=True)


@pytest.fixture
def shifts(bottling: Bottling) -> list[Shift]:
    factory = bottling.line.factory
    return [
        Shift.objects.create(
            factory=factory, name="Morning", start_time=time(6), end_time=time(14)
        ),
        Shift.objects.create(
            factory=factory, name="Afternoon", start_time=time(14), end_time=time(22)
        ),
        Shift.objects.create(factory=factory, name="Night", start_time=time(22), end_time=time(6)),
    ]


@pytest.fixture
def ctx(world: World) -> Callable[..., ToolContext]:
    """ctx(role="production_supervisor", now=AFTER_JAM): a tool context for a world user."""

    def _ctx(role: str = "production_supervisor", now: datetime = AFTER_JAM) -> ToolContext:
        user = world.users[role]
        return ToolContext(user, user.membership.organization, now)

    return _ctx


@pytest.fixture
def conversation(world: World) -> Callable[..., Conversation]:
    def _conversation(role: str = "production_supervisor", **fields: Any) -> Conversation:
        user = world.users[role]
        return Conversation.objects.create(
            organization=user.membership.organization, user=user, **fields
        )

    return _conversation
