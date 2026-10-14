"""Who is told, how (in-app, email, live), and whether the engine itself is alive."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core import mail
from django.utils import timezone

from apps.live.broadcast import line_group, user_group
from apps.live.routing import websocket_urlpatterns
from apps.live.tests.test_broadcast import _drain
from apps.notifications.models import (
    Alert,
    AlertRule,
    Channel,
    DeliveryStatus,
    Heartbeat,
    Notification,
    NotificationPreference,
    RuleType,
    Severity,
)
from apps.notifications.services.heartbeat import engine_health
from apps.notifications.tasks import evaluate_periodic
from apps.organizations.models import Role
from apps.production.models import Shift
from tests.helpers import World, create_member
from tests.lines import Bottling

from .support import T

Send = Callable[..., str]


@pytest.fixture
def offline(day_shift: Shift, send: Send, make_rule: Callable[..., Any]) -> AlertRule:
    for machine in ("M01", "M02", "M03"):
        send(machine, "machine_started", T - timedelta(minutes=10))
    for machine in ("M01", "M02"):
        send(machine, "machine_started", T - timedelta(seconds=10))
    return make_rule(RuleType.MACHINE_OFFLINE, {"minutes": 2})


def told(channel: str = Channel.IN_APP) -> set[str]:
    return set(Notification.objects.filter(channel=channel).values_list("user__email", flat=True))


# --- Recipients and preferences ------------------------------------------------------------


def test_only_the_rule_roles_of_this_factory_and_organization_are_told(
    offline: AlertRule, world: World, bottling: Bottling, evaluate: Callable[..., Any]
) -> None:
    create_member(
        "plant-a.supervisor@demo.test",
        world.demo_org,
        Role.PRODUCTION_SUPERVISOR,
        factories=[world.factory_a],
    )
    create_member(
        "plant-b.supervisor@demo.test",
        world.demo_org,
        Role.PRODUCTION_SUPERVISOR,
        factories=[bottling.line.factory],
    )
    gone = create_member("gone@demo.test", world.demo_org, Role.PRODUCTION_SUPERVISOR)
    gone.is_active = False
    gone.save()
    create_member("supervisor@other.test", world.other_org, Role.PRODUCTION_SUPERVISOR)

    evaluate(T)

    assert told() == {"production_supervisor@demo.test", "plant-b.supervisor@demo.test"}


def test_preferences_decide_the_channels(
    offline: AlertRule, world: World, evaluate: Callable[..., Any]
) -> None:
    supervisor = world.users["production_supervisor"]
    NotificationPreference.objects.create(
        user=supervisor, in_app_min_severity=Severity.WARNING, email_min_severity=Severity.CRITICAL
    )

    evaluate(T)  # a warning

    assert told(Channel.IN_APP) == {supervisor.email}
    assert told(Channel.EMAIL) == set()


def test_in_app_respects_its_minimum_severity(
    offline: AlertRule, world: World, evaluate: Callable[..., Any]
) -> None:
    NotificationPreference.objects.create(
        user=world.users["production_supervisor"], in_app_min_severity=Severity.CRITICAL
    )

    evaluate(T)

    assert told(Channel.IN_APP) == set()


# --- Email ----------------------------------------------------------------------------------


def test_email_has_the_line_machine_what_since_and_link(
    offline: AlertRule, evaluate: Callable[..., Any], django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        [alert] = evaluate(T).opened

    [email] = mail.outbox
    assert email.to == ["production_supervisor@demo.test"]
    assert email.subject == "[LineMind] Warning: No data from Filler for more than 2 min."
    assert "Line: Bottling Line" in email.body
    assert "Machine: Filler" in email.body
    assert "Since: 2026-10-05 07:50 (UTC)" in email.body
    assert f"http://linemind.test/alerts?alert={alert.pk}" in email.body
    html, mime = email.alternatives[0]
    assert mime == "text/html" and f"/alerts?alert={alert.pk}" in html
    notification = Notification.objects.get(channel=Channel.EMAIL)
    assert (notification.status, notification.attempts) == (DeliveryStatus.SENT, 1)


def test_a_failing_email_is_retried_then_recorded_as_failed(
    offline: AlertRule, evaluate: Callable[..., Any], django_capture_on_commit_callbacks: Any
) -> None:
    with (
        patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("mail server down")
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        evaluate(T)

    notification = Notification.objects.get(channel=Channel.EMAIL)
    assert notification.status == DeliveryStatus.FAILED
    assert notification.attempts == 4  # the first try and 3 retries
    assert notification.error == "OSError: mail server down"
    assert mail.outbox == []


# --- Live messages ---------------------------------------------------------------------------


@pytest.fixture
def listen(bottling: Bottling, world: World) -> Iterator[Callable[[str], list[dict[str, Any]]]]:
    layer = get_channel_layer()
    channels = {}
    for name, group in (
        ("line", line_group(bottling.line.id)),
        ("user", user_group(world.users["production_supervisor"].pk)),
    ):
        channels[name] = async_to_sync(layer.new_channel)()
        async_to_sync(layer.group_add)(group, channels[name])
    yield lambda name: async_to_sync(_drain)(layer, channels[name])
    async_to_sync(layer.flush)()


def test_alert_messages_are_sent_after_commit_with_the_unread_count(
    offline: AlertRule,
    send: Send,
    listen: Callable[[str], list[dict[str, Any]]],
    evaluate: Callable[..., Any],
    django_capture_on_commit_callbacks: Any,
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        [alert] = evaluate(T).opened
    assert listen("line") == [] and listen("user") == []

    for callback in callbacks:
        callback()
    [opened] = listen("line")
    assert (opened["type"], opened["data"]["alert_id"]) == ("alert_opened", alert.pk)
    assert opened["data"]["message_key"] == "alert.machine_offline"
    [count] = listen("user")
    assert (count["type"], count["data"]["unread_count"]) == ("notifications_changed", 1)

    send("M03", "machine_started", T + timedelta(seconds=30))
    with django_capture_on_commit_callbacks(execute=True):
        evaluate(T + timedelta(seconds=40))
    assert [m["type"] for m in listen("line")] == ["alert_resolved"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_user_socket_needs_a_valid_ticket() -> None:
    communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/me/?ticket=nope")
    connected, code = await communicator.connect()

    assert not connected and code == 4401
    await asyncio.sleep(0)


# --- Heartbeat -------------------------------------------------------------------------------


def test_the_periodic_task_writes_the_heartbeat(world: World) -> None:
    before = timezone.now()

    evaluate_periodic.delay()  # through Celery, as beat runs it

    beats = dict(Heartbeat.objects.values_list("name", "at"))
    assert beats["periodic"] >= before
    assert beats["worker"] >= before  # the task finished: the worker heartbeat too


def test_health_reports_a_stale_engine_after_two_minutes(world: World, api: Any) -> None:
    now = timezone.now()
    Heartbeat.objects.create(name="periodic", at=now - timedelta(seconds=110))
    assert engine_health(now)["status"] == "ok"
    assert engine_health(now + timedelta(seconds=11))["status"] == "stale"

    Heartbeat.objects.filter(name="periodic").update(at=now - timedelta(minutes=3))
    body = api(None).get("/api/v1/health/").json()
    assert body["alerts"] == "stale"
    assert body["alerts_last_heartbeat"] is not None

    Heartbeat.objects.filter(name="periodic").update(at=timezone.now())
    assert api(None).get("/api/v1/health/").json()["alerts"] == "ok"


def test_alert_count_is_unchanged_by_the_heartbeat(world: World) -> None:
    evaluate_periodic.delay()
    evaluate_periodic.delay()

    assert Alert.objects.count() == 0
