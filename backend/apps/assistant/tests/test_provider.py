"""The OpenAI-compatible provider against a mock HTTP server (no network, no real model)."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from apps.assistant.providers import build_provider
from apps.assistant.providers.base import Completed, TextDelta, collect
from apps.assistant.providers.errors import (
    ModelOutputError,
    ProviderBusy,
    ProviderUnavailable,
    ProviderUnreachable,
)
from apps.assistant.providers.fake import FakeProvider
from apps.assistant.providers.openai_compatible import OpenAICompatibleProvider, parse_duration

Handler = Callable[[httpx.Request], httpx.Response]


def sse(*chunks: dict[str, Any]) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return body.encode()


def provider(handler: Handler, sleeps: list[float] | None = None) -> OpenAICompatibleProvider:
    record = sleeps if sleeps is not None else []
    return OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        model="open-model",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        sleep=record.append,
        jitter=lambda: 0.0,
    )


TEXT = sse(
    {"choices": [{"delta": {"content": "OEE was "}}]},
    {"choices": [{"delta": {"content": "78.4%."}}]},
    {"choices": [], "x_groq": {"usage": {"prompt_tokens": 120, "completion_tokens": 8}}},
)
TOOL = sse(
    {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "c1",
                            "function": {"name": "get_oee", "arguments": '{"line_'},
                        }
                    ]
                }
            }
        ]
    },
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'id": 1}'}}]}}]},
)


def test_streams_text_and_reads_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=TEXT)

    items = list(provider(handler).stream([{"role": "user", "content": "OEE?"}], []))
    assert [i.text for i in items if isinstance(i, TextDelta)] == ["OEE was ", "78.4%."]
    result = items[-1]
    assert isinstance(result, Completed)
    assert (result.result.text, result.result.prompt_tokens, result.result.completion_tokens) == (
        "OEE was 78.4%.",
        120,
        8,
    )
    body = json.loads(seen[0].content)
    assert body["model"] == "open-model" and body["stream"] is True and "tools" not in body
    assert seen[0].headers["Authorization"] == "Bearer secret"
    assert str(seen[0].url) == "https://models.example/v1/chat/completions"


def test_assembles_streamed_tool_calls() -> None:
    result = collect(
        provider(lambda r: httpx.Response(200, content=TOOL)).stream([], [{"type": "function"}])
    )
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("c1", "get_oee", '{"line_id": 1}')
    ]


def test_rate_limit_waits_for_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    answers = iter(
        [
            httpx.Response(429, headers={"retry-after": "3"}),
            httpx.Response(429, headers={"retry-after": "60"}),  # capped at 20 s
            httpx.Response(200, content=TEXT),
        ]
    )
    result = collect(provider(lambda r: next(answers), sleeps).stream([], []))
    assert result.text == "OEE was 78.4%."
    assert sleeps == [3.0, 20.0]


def test_rate_limit_backs_off_then_reports_busy() -> None:
    sleeps: list[float] = []
    with pytest.raises(ProviderBusy):
        collect(provider(lambda r: httpx.Response(429), sleeps).stream([], []))
    assert sleeps == [2.0, 4.0, 8.0]  # three retries, then busy


def test_server_errors_are_retried_once() -> None:
    sleeps: list[float] = []
    with pytest.raises(ProviderUnavailable):
        collect(provider(lambda r: httpx.Response(503), sleeps).stream([], []))
    assert len(sleeps) == 1


@pytest.mark.parametrize("status", [401, 403, 404])
def test_wrong_key_or_model_is_unreachable(status: int) -> None:
    with pytest.raises(ProviderUnreachable):
        collect(
            provider(lambda r: httpx.Response(status, json={"error": {"message": "no"}})).stream(
                [], []
            )
        )


def test_no_network_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ProviderUnreachable, match="Cannot connect"):
        collect(provider(handler).stream([], []))


def test_not_configured_is_unreachable() -> None:
    with pytest.raises(ProviderUnreachable, match="not configured"):
        collect(OpenAICompatibleProvider(base_url="", model="").stream([], []))


def test_a_malformed_tool_call_is_a_model_output_error() -> None:
    body = {
        "error": {
            "code": "tool_use_failed",
            "message": "Failed to call a function",
            "failed_generation": "<fn>",
        }
    }
    with pytest.raises(ModelOutputError) as caught:
        collect(provider(lambda r: httpx.Response(400, json=body)).stream([], []))
    assert caught.value.generation == "<fn>"


def test_probe_checks_the_model_list_and_tool_calling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "open-model"}]})
        return httpx.Response(
            200,
            content=sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "p",
                                        "function": {"name": "ping", "arguments": "{}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
        )

    result = provider(handler).probe()
    assert (result.reachable, result.tool_calling) == (True, True)

    def unlisted(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "another-model"}]})

    result = provider(unlisted).probe()
    assert not result.reachable and "not offered" in result.error

    def no_tools(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, content=TEXT)

    assert provider(no_tools).probe().tool_calling is False

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert provider(down).probe().reachable is False


def test_rate_limit_headers_are_remembered() -> None:
    p = provider(
        lambda r: httpx.Response(
            200,
            content=TEXT,
            headers={"x-ratelimit-remaining-tokens": "2500", "x-ratelimit-reset-tokens": "7.66s"},
        )
    )
    collect(p.stream([], []))
    assert (p.remaining_tokens, p.reset_tokens_seconds) == (2500, 7.66)
    assert parse_duration("2m59.5s") == 179.5
    assert parse_duration("350ms") == pytest.approx(0.35)


def test_switching_vendor_is_only_settings(settings: Any) -> None:
    settings.ASSISTANT = {
        **settings.ASSISTANT,
        "PROVIDER": "openai_compatible",
        "BASE_URL": "http://ollama:11434/v1/",
        "MODEL": "gpt-oss:20b",
        "EXTRA_PARAMS": '{"reasoning_effort": "low"}',
    }
    built = build_provider()
    assert isinstance(built, OpenAICompatibleProvider)
    assert (built.base_url, built.model, built.extra_params) == (
        "http://ollama:11434/v1",
        "gpt-oss:20b",
        {"reasoning_effort": "low"},
    )
    settings.ASSISTANT = {**settings.ASSISTANT, "PROVIDER": "fake"}
    assert isinstance(build_provider(), FakeProvider)
