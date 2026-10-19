"""A scripted provider: for tests, and for running LineMind without any model.

Each `FakeTurn` is one model reply: some text, some tool calls, or an error to raise.
Every request is recorded in `requests`, so tests can check exactly what the model saw.
"""

from __future__ import annotations

import copy
import json
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from apps.assistant.providers.base import (
    ChatMessage,
    ChatResult,
    Completed,
    ProbeResult,
    RawToolCall,
    StreamItem,
    TextDelta,
    ToolSpec,
)

NO_MODEL_ANSWER = (
    "The assistant is running without a language model (ASSISTANT_PROVIDER=fake), so it "
    "cannot answer questions yet. Ask an administrator to configure a model."
)


@dataclass
class FakeTurn:
    text: str = ""
    # (name, arguments): a dict is sent as JSON, a string as-is (to test broken JSON).
    tool_calls: list[tuple[str, dict[str, Any] | str]] = field(default_factory=list)
    error: Exception | None = None
    prompt_tokens: int = 100
    completion_tokens: int = 20


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        turns: Iterable[FakeTurn] = (),
        model: str = "fake-model",
        probe_result: ProbeResult | None = None,
    ) -> None:
        self.model = model
        self.turns: deque[FakeTurn] = deque(turns)
        self.requests: list[dict[str, Any]] = []
        self._probe = probe_result or ProbeResult(True, True, model)
        self._calls = 0

    def stream(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> Iterator[StreamItem]:
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        turn = self.turns.popleft() if self.turns else FakeTurn(text=NO_MODEL_ANSWER)
        if turn.error is not None:
            raise turn.error
        # Stream the text in two pieces, like a real model would.
        middle = len(turn.text) // 2
        for piece in (turn.text[:middle], turn.text[middle:]):
            if piece:
                yield TextDelta(piece)
        calls = []
        for name, arguments in turn.tool_calls:
            self._calls += 1
            raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
            calls.append(RawToolCall(id=f"call_{self._calls}", name=name, arguments=raw))
        yield Completed(ChatResult(turn.text, calls, turn.prompt_tokens, turn.completion_tokens))

    def probe(self) -> ProbeResult:
        return self._probe
