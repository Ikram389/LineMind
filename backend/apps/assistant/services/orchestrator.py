"""How a question becomes a grounded answer.

`ask()` is a generator of events for the streaming endpoint (and the evaluation):

    ("progress", {"tool", "label"})   a tool is about to run
    ("delta", {"text"})               a piece of the answer as the model writes it
    ("text_reset", {})                the streamed text was only a preamble to tool calls
    ("final", message)                the stored answer, with sources and checks
    ("error", {"code", "message", "answer"})   a clean ending with a clear message

The loop: the model sees the system prompt, the recent conversation and the question;
when it asks for tools, LineMind validates and runs them (as the user) and feeds the
results back; when it answers in text, the numbers are checked against the tool results
and everything is stored. Limits: ASSISTANT_MAX_TOOL_CALLS per question, one correction
after invalid tool arguments, a total timeout, and the concurrency slots.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant.models import Conversation, Message, MessageRole, MessageStatus, ToolCall
from apps.assistant.providers import get_provider
from apps.assistant.providers.base import (
    ChatMessage,
    ChatProvider,
    ChatResult,
    RawToolCall,
    TextDelta,
)
from apps.assistant.providers.errors import ModelOutputError, ProviderError, ProviderUnreachable
from apps.assistant.serializers import MessageSerializer
from apps.assistant.services.language import detect, message
from apps.assistant.services.limits import AllSlotsBusy, Slot
from apps.assistant.services.numbers import check_numbers
from apps.assistant.services.prompt import build_system_prompt
from apps.assistant.services.status import model_status
from apps.assistant.services.tool_runner import (
    CHARS_PER_TOKEN,
    Outcome,
    assign_numbers,
    dumps,
    for_model,
    numbered_sources,
    run_tool,
)
from apps.assistant.tools import BY_NAME, tool_specs
from apps.assistant.tools.core import ToolContext, iso, range_label

logger = logging.getLogger(__name__)

QUESTION_TIMEOUT_SECONDS = 120
HISTORY_SHARE = 0.25  # of the context window, for earlier questions and answers
MAX_KEY_METRICS = 8
MAX_WARNINGS = 8

Event = tuple[str, dict[str, Any]]

PROGRESS = {
    "list_lines": "Listing your lines…",
    "resolve_time_range": "Working out the time range…",
    "get_shifts": "Checking the shifts…",
    "get_line_status": "Checking the line status…",
    "get_oee": "Checking the OEE…",
    "get_downtime": "Checking the downtime…",
    "get_recurring_stops": "Looking for recurring stops…",
    "get_incidents": "Checking the line stops…",
    "get_quality": "Checking quality…",
    "get_alerts": "Checking alerts…",
    "get_maintenance": "Checking maintenance actions…",
    "get_production_orders": "Checking production orders…",
    "compare_periods": "Comparing the two periods…",
}

STATUS_FOR = {
    "busy": MessageStatus.BUSY,
    "unreachable": MessageStatus.UNREACHABLE,
    "no_tool_calling": MessageStatus.UNREACHABLE,
    "timeout": MessageStatus.TIMEOUT,
    "tool_limit": MessageStatus.TOOL_LIMIT,
    "invalid_tool_calls": MessageStatus.FAILED,
    "failed": MessageStatus.FAILED,
}


class RunError(Exception):
    code = "failed"


class QuestionTimeout(RunError):
    code = "timeout"


class ToolLimitReached(RunError):
    code = "tool_limit"


class TooManyInvalidCalls(RunError):
    code = "invalid_tool_calls"


class NoToolCalling(RunError):
    code = "no_tool_calling"


class EmptyAnswer(RunError):
    code = "failed"


@dataclass
class Run:
    conversation: Conversation
    question: str
    user: User
    now: datetime
    provider: ChatProvider
    language: str
    question_message: Message
    started: float = field(default_factory=time.monotonic)
    outcomes: list[Outcome] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    zone: str = "UTC"
    known_sources: dict[str, int] = field(default_factory=dict)
    next_number: int = 1
    calls_made: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add_tokens(self, result: ChatResult) -> None:
        self.prompt_tokens += result.prompt_tokens or 0
        self.completion_tokens += result.completion_tokens or 0

    def duration_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


class TextGate:
    """Streams text as it comes, except text that looks like a tool call written as JSON
    (some open models do that): it is held back until we know what it is."""

    def __init__(self) -> None:
        self.buffer = ""
        self.mode: str | None = None  # "stream" or "hold"

    @property
    def emitted(self) -> bool:
        return self.mode == "stream" and bool(self.buffer.strip())

    def feed(self, piece: str) -> str:
        self.buffer += piece
        if self.mode == "stream":
            return piece
        if self.mode == "hold":
            return ""
        stripped = self.buffer.lstrip()
        if not stripped:
            return ""
        if stripped[0] in "{[`<":
            self.mode = "hold"
            return ""
        self.mode = "stream"
        return self.buffer


# --- Tool calls written as text ------------------------------------------------------

FUNCTION_TAG = re.compile(r"<function=([\w-]+)>\s*(\{.*?\})\s*</function>", re.DOTALL)


def text_tool_calls(text: str) -> list[RawToolCall]:
    """Recognise tool calls a model wrote in its text instead of the tool-call field."""
    stripped = text.strip()
    if not stripped:
        return []
    calls = [
        RawToolCall(f"text_{i}", name, args)
        for i, (name, args) in enumerate(FUNCTION_TAG.findall(stripped))
        if name in BY_NAME
    ]
    if calls:
        return calls
    body = stripped.strip("`").removeprefix("json").strip()
    if not body.startswith(("{", "[")):
        return []
    try:
        value = json.loads(body)
    except ValueError:
        return []
    items = value if isinstance(value, list) else [value]
    found = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return []
        name = item.get("name") or item.get("tool") or item.get("function")
        args = item.get("arguments", item.get("parameters", {}))
        if not isinstance(name, str) or name not in BY_NAME:
            return []
        found.append(
            RawToolCall(f"text_{i}", name, args if isinstance(args, str) else json.dumps(args))
        )
    return found


# --- The question loop ---------------------------------------------------------------


def ask(
    conversation: Conversation,
    question: str,
    user: User,
    *,
    now: datetime | None = None,
    provider: ChatProvider | None = None,
    question_timeout: float = QUESTION_TIMEOUT_SECONDS,
) -> Iterator[Event]:
    question_message = Message.objects.create(
        conversation=conversation,
        role=MessageRole.USER,
        content=question,
        language=detect(question),
    )
    if not conversation.title:
        conversation.title = question[:80]
        conversation.save(update_fields=["title", "updated_at"])
    run = Run(
        conversation=conversation,
        question=question,
        user=user,
        now=now or timezone.now(),
        provider=provider or get_provider(),
        language=question_message.language,
        question_message=question_message,
    )
    try:
        with Slot():
            status = model_status(run.provider)
            if not status["reachable"]:
                raise ProviderUnreachable(status["error"])
            if status["tool_calling"] is False:
                raise NoToolCalling(status["error"])
            yield from _loop(run, question_timeout)
    except GeneratorExit:  # the browser went away: nothing more to send
        raise
    except (ProviderError, RunError, AllSlotsBusy) as exc:
        code = getattr(exc, "code", "failed")
        if code == "invalid_tool_call":
            code = "invalid_tool_calls"
        logger.info("Assistant question %s ended with %s: %s", question_message.pk, code, exc)
        yield _failure(run, code)
    except Exception:
        logger.exception("Assistant question %s failed", question_message.pk)
        yield _failure(run, "failed")


def _history(run: Run) -> list[ChatMessage]:
    """Earlier questions and answered replies (text only), newest kept, within budget."""
    budget = settings.ASSISTANT["CONTEXT_TOKENS"] * CHARS_PER_TOKEN * HISTORY_SHARE
    earlier = list(
        run.conversation.messages.exclude(pk=run.question_message.pk).order_by(
            "-created_at", "-id"
        )[:20]
    )
    pairs: list[ChatMessage] = []
    used = 0
    pending_answer: Message | None = None
    for msg in earlier:  # newest first
        if msg.role == MessageRole.ASSISTANT:
            pending_answer = msg if msg.status == MessageStatus.OK else None
            continue
        if pending_answer is None:
            continue
        size = len(msg.content) + len(pending_answer.content)
        if used + size > budget:
            break
        used += size
        pairs[:0] = [
            {"role": "user", "content": msg.content},
            {"role": "assistant", "content": pending_answer.content},
        ]
        pending_answer = None
    return pairs


def _loop(run: Run, question_timeout: float) -> Iterator[Event]:
    ctx = ToolContext(run.user, run.conversation.organization, run.now)
    lines = list(ctx.lines().order_by("factory__name", "name")[:50])
    focus_line = next((line for line in lines if line.pk == run.conversation.line_id), None)
    conv = run.conversation
    focus_range = (
        (conv.context_start, conv.context_end) if conv.context_start and conv.context_end else None
    )
    system, run.context = build_system_prompt(ctx, lines, focus_line, focus_range)
    home = focus_line or (lines[0] if lines else None)
    run.zone = home.factory.timezone if home else "UTC"
    messages: list[ChatMessage] = [
        {"role": "system", "content": system},
        *_history(run),
        {"role": "user", "content": run.question},
    ]
    specs = tool_specs()
    max_calls = int(settings.ASSISTANT["MAX_TOOL_CALLS"])
    invalid = 0

    while True:
        if time.monotonic() - run.started > question_timeout:
            raise QuestionTimeout
        gate = TextGate()
        result: ChatResult | None = None
        try:
            for item in run.provider.stream(messages, specs):
                if isinstance(item, TextDelta):
                    piece = gate.feed(item.text)
                    if piece:
                        yield ("delta", {"text": piece})
                else:
                    result = item.result
        except ModelOutputError as exc:
            invalid += 1
            run.outcomes.append(
                Outcome(
                    RawToolCall("malformed", "(malformed)", exc.generation[:2000]),
                    exc.generation[:2000],
                    False,
                    error="The model produced a malformed tool call.",
                )
            )
            if invalid > 1:
                raise TooManyInvalidCalls from exc
            if gate.emitted:
                yield ("text_reset", {})
            messages.append(
                {
                    "role": "user",
                    "content": "[LineMind] Your last tool call was malformed. Call the tool "
                    "again with arguments that match its parameters exactly.",
                }
            )
            continue
        if result is None:
            raise EmptyAnswer("The model sent no result.")
        run.add_tokens(result)

        calls = result.tool_calls or text_tool_calls(result.text)
        if not calls:
            text = result.text.strip()
            if not text:
                raise EmptyAnswer("The model returned an empty answer.")
            yield _finish(run, text)
            return

        if gate.emitted:
            yield ("text_reset", {})
        messages.append(
            {
                "role": "assistant",
                "content": result.text if result.tool_calls else "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in calls
                ],
            }
        )
        for call in calls:
            if run.calls_made >= max_calls:
                raise ToolLimitReached
            run.calls_made += 1
            yield (
                "progress",
                {"tool": call.name, "label": PROGRESS.get(call.name, "Looking up data…")},
            )
            outcome = run_tool(call, ctx)
            run.next_number = assign_numbers(outcome, run.next_number, run.known_sources)
            run.outcomes.append(outcome)
            if not outcome.valid:
                invalid += 1
                if invalid > 1:
                    raise TooManyInvalidCalls
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": for_model(outcome)}
            )


# --- Storing -------------------------------------------------------------------------


def _ranges_used(run: Run) -> list[dict[str, Any]]:
    """The ranges the tools actually used: what the answer is about."""
    ready = {(r["start"], r["end"]): r for r in run.context.get("ranges", {}).values()}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for outcome in run.outcomes:
        if not outcome.valid or outcome.result is None or outcome.result.error:
            continue
        if outcome.result.resolved_range:
            r = outcome.result.resolved_range
            found.setdefault((r["start"], r["end"]), {k: r[k] for k in ("start", "end", "label")})
            continue
        args = outcome.clean_args
        pairs = []
        if "start" in args and "end" in args:
            pairs.append((args["start"], args["end"]))
        for key in ("range_a", "range_b"):
            if key in args:
                pairs.append(args[key])
        for start, end in pairs:
            key = (iso(start), iso(min(end, run.now)))
            label = ready.get(key, {}).get("label") or range_label(
                start, min(end, run.now), run.zone
            )
            found.setdefault(key, {"start": key[0], "end": key[1], "label": label})
    return list(found.values())


def _summary(outcome: Outcome) -> dict[str, Any]:
    if not outcome.valid or outcome.result is None:
        return {"error": outcome.error}
    result = outcome.result
    return {
        "error": result.error,
        "warnings": result.warnings,
        "key_metrics": result.key_metrics,
        "sources": [s.as_dict() for s in result.sources],
        "message": result.data.get("message") if result.error else None,
    }


def _json_safe(value: Any) -> Any:
    return json.loads(dumps(value))


def _store(run: Run, **fields: Any) -> Message:
    msg = Message.objects.create(
        conversation=run.conversation,
        role=MessageRole.ASSISTANT,
        language=run.language,
        model=run.provider.model,
        prompt_tokens=run.prompt_tokens or None,
        completion_tokens=run.completion_tokens or None,
        duration_ms=run.duration_ms(),
        **fields,
    )
    ToolCall.objects.bulk_create(
        ToolCall(
            message=msg,
            order=i + 1,
            name=o.call.name,
            arguments=_json_safe(o.arguments)
            if isinstance(o.arguments, dict | list)
            else {"raw": str(o.arguments)[:2000]},
            invalid=not o.valid,
            error=o.error
            or (o.result.data.get("message", "") if o.result and o.result.error else ""),
            result_summary=_json_safe(_summary(o)),
            duration_ms=o.duration_ms,
        )
        for i, o in enumerate(run.outcomes)
    )
    run.conversation.save(update_fields=["updated_at"])
    return msg


def _finish(run: Run, text: str) -> Event:
    valid = [o for o in run.outcomes if o.valid and o.result is not None]
    evidence = [
        {
            "data": o.result.data,
            "warnings": o.result.warnings,
            "sources": [s.label for s in o.result.sources],
        }
        for o in valid
        if o.result is not None
    ]
    number_check = check_numbers(text, _json_safe(evidence), run.question, run.context)
    metrics: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for o in valid:
        assert o.result is not None
        for m in o.result.key_metrics:
            metrics[m["label"]] = m
        for w in o.result.warnings:
            if w not in warnings:
                warnings.append(w)
    msg = _store(
        run,
        content=text,
        status=MessageStatus.OK,
        resolved_ranges=_ranges_used(run),
        sources=numbered_sources(run.outcomes),
        key_metrics=_json_safe(list(metrics.values())[-MAX_KEY_METRICS:]),
        warnings=warnings[:MAX_WARNINGS],
        number_check=number_check,
    )
    if number_check["unverified"]:
        logger.warning(
            "Assistant answer %s has unverified numbers: %s",
            msg.pk,
            [i["text"] for i in number_check["items"] if i["status"] == "unverified"],
        )
    return ("final", MessageSerializer(msg).data)


def _failure(run: Run, code: str) -> Event:
    text = message(code, run.language)
    msg = _store(run, content=text, status=STATUS_FOR.get(code, MessageStatus.FAILED))
    return ("error", {"code": code, "message": text, "answer": MessageSerializer(msg).data})
