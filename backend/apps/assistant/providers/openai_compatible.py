"""A chat provider for any OpenAI-compatible server with tool calling (Groq, Ollama, vLLM...).

Plain HTTP with httpx, no vendor SDK: base URL, model, key and options come from settings.
- Streams the answer (server-sent events) and assembles tool calls from their pieces.
- HTTP 429: waits `retry-after` (capped) or backs off 2 → 4 → 8 s, then gives up as "busy".
- Server errors and timeouts: one retry. A rejected key, unknown model or no network:
  "unreachable" at once (retrying would not help).
- Remembers the rate-limit headers, so the evaluation can pace itself.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from apps.assistant.providers.base import (
    ChatMessage,
    ChatResult,
    Completed,
    ProbeResult,
    RawToolCall,
    StreamItem,
    TextDelta,
    ToolSpec,
    collect,
)
from apps.assistant.providers.errors import (
    ModelOutputError,
    ProviderBusy,
    ProviderError,
    ProviderUnavailable,
    ProviderUnreachable,
)

RATE_LIMIT_RETRIES = 3
BACKOFF_SECONDS = (2.0, 4.0, 8.0)
MAX_WAIT_SECONDS = 20.0
SERVER_ERROR_RETRIES = 1

PING_TOOL: ToolSpec = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Answers pong. Call it when asked to ping.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


def parse_duration(value: str | None) -> float | None:
    """Rate-limit header durations: "12", "7.66s", "2m59.56s", "350ms"."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    total, found = 0.0, False
    for amount, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        found = True
        total += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total if found else None


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        temperature: float = 0.1,
        timeout_seconds: float = 60,
        extra_params: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.extra_params = extra_params or {}
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter
        # Latest rate-limit headers (tokens per minute), for pacing the evaluation.
        self.remaining_tokens: int | None = None
        self.reset_tokens_seconds: float | None = None

    # --- HTTP ----------------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
            transport=self._transport,
        )

    def _remember_limits(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining-tokens")
        if remaining and remaining.isdigit():
            self.remaining_tokens = int(remaining)
        reset = parse_duration(response.headers.get("x-ratelimit-reset-tokens"))
        if reset is not None:
            self.reset_tokens_seconds = reset

    def _check_configured(self) -> None:
        if not self.base_url or not self.model:
            raise ProviderUnreachable(
                "The assistant's model is not configured (ASSISTANT_BASE_URL, ASSISTANT_MODEL)."
            )

    @staticmethod
    def _error_body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            return {"message": response.text[:300]}
        error = body.get("error") if isinstance(body, dict) else None
        return error if isinstance(error, dict) else {"message": str(body)[:300]}

    def _raise_for(self, response: httpx.Response) -> None:
        """Turn a failed (non-429, non-5xx) response into the right provider error."""
        error = self._error_body(response)
        message = str(error.get("message") or response.reason_phrase)
        if response.status_code in (401, 403):
            raise ProviderUnreachable(f"The model server rejected the API key ({message}).")
        if response.status_code == 404:
            raise ProviderUnreachable(f"Model or URL not found ({message}).")
        if error.get("code") == "tool_use_failed":
            raise ModelOutputError(message, str(error.get("failed_generation") or ""))
        raise ProviderError(f"The model server refused the request ({message}).")

    # --- Chat ----------------------------------------------------------------------------

    def stream(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> Iterator[StreamItem]:
        self._check_configured()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
            **self.extra_params,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        rate_limited = server_errors = 0
        while True:
            try:
                with (
                    self._client() as client,
                    client.stream("POST", "/chat/completions", json=payload) as response,
                ):
                    self._remember_limits(response)
                    if response.status_code == 429:
                        response.read()
                        wait = self._wait_for_rate_limit(response, rate_limited)
                        rate_limited += 1
                        self._sleep(wait)
                        continue
                    if response.status_code >= 500:
                        response.read()
                        if server_errors >= SERVER_ERROR_RETRIES:
                            raise ProviderUnavailable(
                                f"The model server failed ({response.status_code})."
                            )
                        server_errors += 1
                        self._sleep(BACKOFF_SECONDS[0])
                        continue
                    if response.status_code != 200:
                        response.read()
                        self._raise_for(response)
                    yield from self._read_stream(response)
                    return
            except httpx.TimeoutException as exc:
                if server_errors >= SERVER_ERROR_RETRIES:
                    raise ProviderUnavailable("The model did not answer in time.") from exc
                server_errors += 1
            except httpx.TransportError as exc:  # no network, DNS, connection refused
                raise ProviderUnreachable(f"Cannot connect to the model server ({exc}).") from exc

    def _wait_for_rate_limit(self, response: httpx.Response, attempt: int) -> float:
        retry_after = parse_duration(response.headers.get("retry-after"))
        if attempt >= RATE_LIMIT_RETRIES:
            raise ProviderBusy(retry_after=retry_after)
        if retry_after is not None:
            return min(retry_after, MAX_WAIT_SECONDS)
        base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        return base + self._jitter()  # jitter: concurrent requests don't retry in lockstep

    def _read_stream(self, response: httpx.Response) -> Iterator[StreamItem]:
        text_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("error"):
                error = chunk["error"]
                if isinstance(error, dict) and error.get("code") == "tool_use_failed":
                    raise ModelOutputError(
                        str(error.get("message", "")), str(error.get("failed_generation", ""))
                    )
                raise ProviderError(f"The model server reported an error ({error}).")
            usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage") or usage
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    text_parts.append(piece)
                    yield TextDelta(piece)
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(
                        int(call.get("index", len(calls))), {"id": "", "name": "", "arguments": ""}
                    )
                    slot["id"] = call.get("id") or slot["id"]
                    function = call.get("function") or {}
                    slot["name"] += function.get("name") or ""
                    slot["arguments"] += function.get("arguments") or ""
        yield Completed(
            ChatResult(
                text="".join(text_parts),
                tool_calls=[
                    RawToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"])
                    for i, c in sorted(calls.items())
                ],
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        )

    # --- Probe ---------------------------------------------------------------------------

    def probe(self) -> ProbeResult:
        """Reachable and listed? Then one tiny call: does it call a tool when asked?"""
        try:
            self._check_configured()
            with self._client() as client:
                response = client.get("/models")
            if response.status_code in (401, 403, 404):
                self._raise_for(response)
            if response.status_code == 200:
                listed = [m.get("id") for m in (response.json().get("data") or [])]
                if listed and self.model not in listed:
                    return ProbeResult(
                        False, None, self.model, f"Model {self.model} is not offered."
                    )
            result = collect(
                self.stream(
                    [
                        {"role": "system", "content": "You test tools. Call the ping tool now."},
                        {"role": "user", "content": "ping"},
                    ],
                    [PING_TOOL],
                )
            )
        except ProviderBusy:
            return ProbeResult(True, None, self.model, "Rate limited while testing.")
        except ModelOutputError:
            return ProbeResult(True, False, self.model, "The model produced a malformed tool call.")
        except (ProviderUnreachable, ProviderUnavailable, httpx.HTTPError) as exc:
            return ProbeResult(False, None, self.model, str(exc))
        except ProviderError as exc:
            return ProbeResult(True, None, self.model, str(exc))
        called = any(c.name == "ping" for c in result.tool_calls) or '"ping"' in result.text
        error = "" if called else "The model did not call the test tool."
        return ProbeResult(True, called, self.model, error)
