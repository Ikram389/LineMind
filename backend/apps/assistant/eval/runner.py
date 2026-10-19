"""Runs the question set against one or more models and scores each answer.

Scores per answer:
- numbers: how many expected numbers appear in the answer (rounded as written);
- texts: required words present (e.g. "Labeler");
- language: the answer is in the question's language;
- no_data: for questions without data, the answer has no unverified number;
- sources: the answer cites a source [n] and has links;
plus unverified numbers, invalid tool calls, tools used, time and tokens.

Free tiers have rate limits: requests are paced (a pause between questions, and a wait
when the provider reports few tokens left for this minute).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from apps.assistant.eval.data import EvalWorld
from apps.assistant.eval.questions import Question
from apps.assistant.models import Conversation
from apps.assistant.providers.base import ChatProvider
from apps.assistant.services.language import detect
from apps.assistant.services.numbers import ValueSet, find_numbers
from apps.assistant.services.orchestrator import ask

LOW_TOKENS = 3000


@dataclass
class Score:
    question: str
    model: str
    language: str
    status: str
    answer: str
    expected: list[float] = field(default_factory=list)
    numbers_found: int = 0
    numbers_expected: int = 0
    texts_ok: bool = True
    language_ok: bool = True
    no_data: bool = False
    no_data_ok: bool | None = None
    sources_cited: bool = False
    unverified: int = 0
    from_question: int = 0
    invalid_tool_calls: int = 0
    tools: list[str] = field(default_factory=list)
    duration_ms: int = 0
    tokens: int = 0
    error: str = ""

    @property
    def numbers_ok(self) -> bool:
        return self.numbers_found == self.numbers_expected

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "numbers_ok": self.numbers_ok}


def numbers_in(answer: str) -> list[tuple[Decimal, int]]:
    return [reading for found in find_numbers(answer) for reading in found.readings]


def best_match(answer: str, alternatives: list[list[float]]) -> tuple[list[float], int]:
    readings = numbers_in(answer)
    best: tuple[list[float], int] = (alternatives[0] if alternatives else [], -1)
    for expected in alternatives:
        found = 0
        for value in expected:
            target = ValueSet([Decimal(str(value))])
            if any(target.matches(v, d) for v, d in readings):
                found += 1
        if found > best[1]:
            best = (expected, found)
    return best[0], max(best[1], 0)


def score(
    question: Question, world: EvalWorld, model: str, event: tuple[str, dict[str, Any]]
) -> Score:
    name, body = event
    answer = body if name == "final" else body["answer"]
    text = answer["content"]
    calls = answer.get("tool_calls", [])
    check = answer.get("number_check") or {}
    result = Score(
        question=question.id,
        model=model,
        language=question.language,
        status=answer["status"],
        answer=text,
        no_data=question.no_data,
        unverified=check.get("unverified", 0),
        from_question=check.get("from_question", 0),
        invalid_tool_calls=sum(1 for c in calls if c["invalid"]),
        tools=[c["name"] for c in calls],
        duration_ms=answer.get("duration_ms") or 0,
        tokens=(answer.get("prompt_tokens") or 0) + (answer.get("completion_tokens") or 0),
        error="" if name == "final" else body["code"],
        sources_cited="[" in text and bool(answer.get("sources")),
        language_ok=detect(text) == question.language,
    )
    if question.expect is not None:
        expected, found = best_match(text, question.expect(world, question.now))
        result.expected, result.numbers_found, result.numbers_expected = (
            expected,
            found,
            len(expected),
        )
        result.texts_ok = all(t.lower() in text.lower() for t in question.texts)
    else:
        result.no_data_ok = answer["status"] == "ok" and result.unverified == 0
    return result


def run(
    questions: Iterable[Question],
    world: EvalWorld,
    provider: ChatProvider,
    pause_seconds: float = 4.0,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = lambda message: None,
) -> list[Score]:
    scores = []
    for index, question in enumerate(questions):
        if index:
            sleep(pause_seconds)
        remaining = getattr(provider, "remaining_tokens", None)
        if remaining is not None and remaining < LOW_TOKENS:
            sleep(getattr(provider, "reset_tokens_seconds", None) or 10.0)
        conversation = Conversation.objects.create(
            organization=world.organization, user=world.user, title=f"[eval] {question.id}"
        )
        last: tuple[str, dict[str, Any]] | None = None
        for event in ask(
            conversation, question.text, world.user, now=question.now, provider=provider
        ):
            if event[0] in ("final", "error"):
                last = event
        assert last is not None
        result = score(question, world, provider.model, last)
        progress(
            f"{provider.model} {question.id}: {result.status}, numbers {result.numbers_found}/"
            f"{result.numbers_expected}, unverified {result.unverified}"
        )
        scores.append(result)
    return scores
