"""quality_updated: sent after commit with the shift's numbers, throttled per line."""

import time
from collections.abc import Callable, Iterator
from datetime import time as clock
from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from apps.live.broadcast import line_group
from apps.live.tests.test_broadcast import _drain
from apps.production.models import Shift
from apps.quality.models import DefectType, InspectionResult
from apps.quality.services import live
from tests.helpers import ApiFactory, World
from tests.lines import Bottling


@pytest.fixture
def listen(bottling: Bottling) -> Iterator[Callable[[], list[dict[str, Any]]]]:
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(line_group(bottling.line.id), channel)
    yield lambda: [
        m for m in async_to_sync(_drain)(layer, channel) if m["type"] == "quality_updated"
    ]
    async_to_sync(layer.flush)()


@pytest.fixture
def all_day_shift(bottling: Bottling) -> Shift:
    """A shift that is always running (UTC factory), so "the current shift" exists."""
    return Shift.objects.create(
        factory=bottling.line.factory, name="All day", start_time=clock(0), end_time=clock(0)
    )


def test_sent_after_commit_with_the_shift_numbers(
    catalogue: dict[str, DefectType],
    all_day_shift: Shift,
    defect: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        defect("M05", "Q02", timezone.now() - timedelta(seconds=10))
        assert listen() == []  # nothing before the commit

    for callback in callbacks:
        callback()
    [message] = listen()
    data = message["data"]
    assert (data["defects"], data["unreviewed"]) == (1, 1)
    assert data["shift"]["label"].startswith("All day")


def test_throttled_per_line_and_sent_after_a_review(
    catalogue: dict[str, DefectType],
    all_day_shift: Shift,
    defect: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    api: ApiFactory,
) -> None:
    monkeypatch.setattr(live, "QUALITY_THROTTLE_SECONDS", 1)
    now = timezone.now()

    with django_capture_on_commit_callbacks(execute=True):
        defect("M05", "Q02", now - timedelta(seconds=30))
    with django_capture_on_commit_callbacks(execute=True):
        defect("M05", "Q03", now - timedelta(seconds=20))  # within the throttle: dropped
    assert [m["data"]["defects"] for m in listen()] == [1]

    time.sleep(1.1)
    result = InspectionResult.objects.order_by("timestamp").first()
    assert result is not None
    with django_capture_on_commit_callbacks(execute=True):
        response = api(world.users["quality_inspector"]).post(
            f"/api/v1/inspection-results/{result.id}/reviews/",
            {"verdict": "false_reject"},
            format="json",
        )
    assert response.status_code == 201
    [message] = listen()
    assert (message["data"]["defects"], message["data"]["unreviewed"]) == (1, 1)


def test_without_a_current_shift_the_numbers_are_empty(
    catalogue: dict[str, DefectType],
    defect: Callable[..., str],
    listen: Callable[[], list[dict[str, Any]]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        defect("M05", "Q02", timezone.now() - timedelta(seconds=10))

    [message] = listen()
    assert message["data"]["shift"] is None
