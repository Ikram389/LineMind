"""The assistant API: per-organization switch, daily limit, own conversations only,
feedback, status, and the streamed answer."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from apps.assistant.models import AnswerFeedback, AssistantSettings, Conversation, Message
from apps.assistant.providers.base import ProbeResult
from apps.assistant.providers.fake import FakeProvider, FakeTurn
from apps.audit.models import AuditLog
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

Fake = Callable[..., FakeProvider]
NewConversation = Callable[..., Conversation]
BASE = "/api/v1/assistant"


def events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    body = b"".join(response.streaming_content).decode()
    parsed = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if lines:
            parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def ask(client: Any, conversation_id: int, question: str = "Downtime today?") -> Any:
    return client.post(
        f"{BASE}/conversations/{conversation_id}/ask/", {"question": question}, format="json"
    )


def test_the_stream_sends_progress_text_and_the_final_answer(
    world: World, enabled: AssistantSettings, api: ApiFactory, fake: Fake, bottling: Bottling
) -> None:
    fake(
        FakeTurn(tool_calls=[("list_lines", {})]),
        FakeTurn(text="You can see 3 lines [1]."),
    )
    client = api(world.users["production_supervisor"])
    conv = client.post(f"{BASE}/conversations/", {"line": bottling.line.pk}, format="json").json()
    response = ask(client, conv["id"], "Which lines can I see?")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"

    stream = events(response)
    assert [name for name, _ in stream] == ["progress", "delta", "delta", "final"]
    assert stream[0][1]["tool"] == "list_lines"
    final = stream[-1][1]
    assert final["content"] == "You can see 3 lines [1]."
    assert final["sources"][0]["link"].startswith("/lines/")
    assert final["number_check"]["verified"] == 1

    detail = client.get(f"{BASE}/conversations/{conv['id']}/").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["tool_calls"][0]["name"] == "list_lines"
    assert detail["title"] == "Which lines can I see?"


def test_a_failure_is_streamed_as_an_error_event(
    world: World,
    enabled: AssistantSettings,
    api: ApiFactory,
    fake: Fake,
    conversation: NewConversation,
) -> None:
    fake(probe_result=ProbeResult(False, None, "m", "Cannot connect"))
    client = api(world.users["production_supervisor"])
    stream = events(ask(client, conversation().pk))
    assert stream[-1][0] == "error"
    assert stream[-1][1]["code"] == "unreachable"


def test_disabled_organization(
    world: World, api: ApiFactory, conversation: NewConversation
) -> None:
    response = ask(api(world.users["production_supervisor"]), conversation().pk)
    assert response.status_code == 403 and response.json()["code"] == "disabled"


def test_daily_limit(
    world: World,
    enabled: AssistantSettings,
    api: ApiFactory,
    fake: Fake,
    conversation: NewConversation,
) -> None:
    enabled.daily_question_limit = 1
    enabled.save()
    fake(FakeTurn(text="One."), FakeTurn(text="Two."))
    client = api(world.users["production_supervisor"])
    conv = conversation()
    assert events(ask(client, conv.pk))[-1][0] == "final"
    response = ask(client, conv.pk)
    assert response.status_code == 429
    assert response.json() == {
        "code": "daily_limit",
        "limit": 1,
        "detail": "Daily question limit reached.",
    }


def test_users_only_see_their_own_conversations(
    world: World,
    enabled: AssistantSettings,
    api: ApiFactory,
    fake: Fake,
    conversation: NewConversation,
) -> None:
    fake(FakeTurn(text="Mine."))
    owner = api(world.users["production_supervisor"])
    conv = conversation()
    answer = events(ask(owner, conv.pk))[-1][1]

    for intruder in ("factory_manager", "other_manager"):  # same organization, or another
        client = api(world.users[intruder])
        assert client.get(f"{BASE}/conversations/{conv.pk}/").status_code == 404
        assert client.get(f"{BASE}/conversations/").json() == []
        assert ask(client, conv.pk).status_code == 404
        assert client.delete(f"{BASE}/conversations/{conv.pk}/").status_code == 404
        response = client.post(
            f"{BASE}/messages/{answer['id']}/feedback/", {"helpful": False}, format="json"
        )
        assert response.status_code == 404
    assert owner.get(f"{BASE}/conversations/").json()[0]["id"] == conv.pk


def test_conversations_cannot_point_at_another_organizations_line(
    world: World, api: ApiFactory
) -> None:
    client = api(world.users["production_supervisor"])
    response = client.post(f"{BASE}/conversations/", {"line": world.other_line.pk}, format="json")
    assert response.status_code == 400
    limited = api(world.users["limited_operator"])
    assert (
        limited.post(f"{BASE}/conversations/", {"line": world.line_b.pk}, format="json").status_code
        == 400
    )


def test_create_and_delete_a_conversation(
    world: World, api: ApiFactory, bottling: Bottling
) -> None:
    client = api(world.users["machine_operator"])
    body = {
        "line": bottling.line.pk,
        "context_start": "2026-10-12T06:00:00Z",
        "context_end": "2026-10-12T14:00:00Z",
    }
    created = client.post(f"{BASE}/conversations/", body, format="json")
    assert created.status_code == 201
    conv = Conversation.objects.get(pk=created.json()["id"])
    assert (conv.organization, conv.user) == (world.demo_org, world.users["machine_operator"])
    assert created.json()["line_name"] == "Bottling Line"
    assert client.delete(f"{BASE}/conversations/{conv.pk}/").status_code == 204
    assert not Conversation.objects.exists()


def test_feedback_is_stored_and_can_change(
    world: World,
    enabled: AssistantSettings,
    api: ApiFactory,
    fake: Fake,
    conversation: NewConversation,
) -> None:
    fake(FakeTurn(text="An answer."))
    client = api(world.users["production_supervisor"])
    answer = events(ask(client, conversation().pk))[-1][1]
    url = f"{BASE}/messages/{answer['id']}/feedback/"
    assert client.post(url, {"helpful": False, "comment": "Wrong line"}, format="json").json()[
        "feedback"
    ] == {
        "helpful": False,
        "comment": "Wrong line",
    }
    client.post(url, {"helpful": True}, format="json")
    feedback = AnswerFeedback.objects.get()
    assert (feedback.helpful, feedback.comment, feedback.user) == (
        True,
        "",
        world.users["production_supervisor"],
    )
    question = Message.objects.get(role="user")
    assert (
        client.post(
            f"{BASE}/messages/{question.pk}/feedback/", {"helpful": True}, format="json"
        ).status_code
        == 404
    )


def test_status(world: World, api: ApiFactory, fake: Fake, enabled: AssistantSettings) -> None:
    client = api(world.users["analyst"])
    fake(model="open-model")
    body = client.get(f"{BASE}/status/").json()
    assert body["enabled"] is True and body["reachable"] is True and body["tool_calling"] is True
    assert (
        body["model"] == "open-model" and body["daily_limit"] == 30 and body["questions_today"] == 0
    )

    fake(
        probe_result=ProbeResult(
            False, None, "open-model", "The model server rejected the API key."
        )
    )
    body = client.get(f"{BASE}/status/?refresh=1").json()
    assert body["reachable"] is False and "API key" in body["error"]

    enabled.enabled = False
    enabled.save()
    assert client.get(f"{BASE}/status/").json()["reachable"] is None  # no probe when off


@pytest.mark.parametrize("user", ["no_membership", None])
def test_needs_a_member(world: World, api: ApiFactory, user: str | None) -> None:
    client = api(world.users[user] if user else None)
    assert client.get(f"{BASE}/status/").status_code in (401, 403)
    assert client.get(f"{BASE}/conversations/").status_code in (401, 403)


def test_turning_it_on_in_the_admin_is_audited(world: World, client: Any) -> None:
    from apps.accounts.models import User

    admin = User.objects.create_superuser(email="root@linemind.test", password="x")
    client.force_login(admin)
    response = client.post(
        "/admin/assistant/assistantsettings/add/",
        {"organization": world.demo_org.pk, "enabled": "on", "daily_question_limit": "5"},
    )
    assert response.status_code == 302
    entry = AuditLog.objects.get(action="assistantsettings.created")
    assert entry.after["enabled"] is True and entry.organization == world.demo_org
