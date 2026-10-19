"""The provider interface: what the assistant needs from any language model.

Messages and tool specs use the OpenAI chat format (a de-facto standard that Groq, Ollama,
vLLM and llama.cpp servers all speak). A provider *streams*: it yields text pieces as they
arrive and finishes with one `Completed` item. Nothing here knows about LineMind data.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

# {"role": ..., "content": ..., "tool_calls"?: ..., "tool_call_id"?: ...}
ChatMessage = dict[str, Any]
ToolSpec = dict[str, Any]  # {"type": "function", "function": {"name", "description", "parameters"}}


@dataclass(frozen=True)
class RawToolCall:
    """A tool call as the model wrote it. `arguments` is the raw JSON text: validated later."""

    id: str
    name: str
    arguments: str


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[RawToolCall] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Completed:
    result: ChatResult


StreamItem = TextDelta | Completed


@dataclass(frozen=True)
class ProbeResult:
    """Is the configured model usable? `tool_calling` is None when it could not be tested."""

    reachable: bool
    tool_calling: bool | None
    model: str
    error: str = ""


class ChatProvider(Protocol):
    name: str
    model: str

    def stream(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> Iterator[StreamItem]:
        """Yield TextDelta pieces, then exactly one Completed. Raises providers.errors.*"""
        ...

    def probe(self) -> ProbeResult: ...


def collect(stream: Iterator[StreamItem]) -> ChatResult:
    """Consume a stream and return its result (for callers that don't need the pieces)."""
    for item in stream:
        if isinstance(item, Completed):
            return item.result
    raise RuntimeError("The provider stream ended without a result.")
