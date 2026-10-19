"""Running one tool call from the model, safely.

- The arguments are parsed leniently (code fences, double-encoded JSON) but validated
  strictly by the tool's parameters. Invalid → a short message the model can act on.
- The tool runs read-only inside a transaction with a database statement timeout.
- "Not found" (another tenant's id, or no such id) is a normal result, not an error.
- The result is turned into compact JSON for the model, cut to fit the context budget.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from apps.assistant.providers.base import RawToolCall
from apps.assistant.tools import BY_NAME
from apps.assistant.tools.core import ArgumentError, NotFound, ToolContext, ToolResult

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 10
CHARS_PER_TOKEN = 3.5


@dataclass
class Outcome:
    call: RawToolCall
    arguments: Any  # what the model sent (parsed if possible), for "How I got this"
    valid: bool
    result: ToolResult | None = None
    error: str = ""
    duration_ms: int = 0
    source_numbers: list[int] = field(default_factory=list)
    clean_args: dict[str, Any] = field(default_factory=dict)


def parse_arguments(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    if not text:
        return {}
    value = json.loads(text)
    if isinstance(value, str):  # some models double-encode
        value = json.loads(value)
    return value


def run_tool(call: RawToolCall, ctx: ToolContext) -> Outcome:
    started = time.monotonic()
    tool = BY_NAME.get(call.name)
    try:
        arguments: Any = parse_arguments(call.arguments)
    except ValueError:
        arguments = call.arguments
        return _invalid(call, arguments, "The arguments are not valid JSON.", started)
    if tool is None:
        known = ", ".join(BY_NAME)
        return _invalid(
            call, arguments, f"There is no tool named {call.name!r}. Tools: {known}.", started
        )
    try:
        args = tool.validate(arguments)
    except ArgumentError as exc:
        return _invalid(call, arguments, str(exc), started)

    try:
        result = _run_with_timeout(tool, ctx, args)
    except ArgumentError as exc:  # e.g. an unknown shift name, found while running
        return _invalid(call, arguments, str(exc), started)
    except NotFound as exc:
        result = ToolResult({"error": "not_found", "message": str(exc)}, error="not_found")
    except DatabaseError:
        logger.warning("Assistant tool %s timed out", call.name)
        result = ToolResult(
            {"error": "failed", "message": "This took too long. Try a shorter range."},
            error="failed",
        )
    except Exception:
        logger.exception("Assistant tool %s failed", call.name)
        result = ToolResult({"error": "failed", "message": "The tool failed."}, error="failed")
    return Outcome(call, arguments, True, result, duration_ms=_ms(started), clean_args=args)


def _run_with_timeout(tool: Any, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [TOOL_TIMEOUT_SECONDS * 1000])
        return tool.run(ctx, args)


def _invalid(call: RawToolCall, arguments: Any, message: str, started: float) -> Outcome:
    return Outcome(call, arguments, False, error=message, duration_ms=_ms(started))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# --- What the model sees -------------------------------------------------------------


def result_cap_chars() -> int:
    """About a sixth of the context window per tool result."""
    return int(settings.ASSISTANT["CONTEXT_TOKENS"] * CHARS_PER_TOKEN / 6)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _longest_list(node: Any) -> list[Any] | None:
    best: list[Any] | None = None

    def visit(value: Any) -> None:
        nonlocal best
        if isinstance(value, list):
            if len(value) > 1 and (best is None or len(dumps(value)) > len(dumps(best))):
                best = value
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(node)
    return best


def fit(payload: dict[str, Any], cap: int) -> str:
    """Halve the longest list until the JSON fits; mark the result as truncated."""
    text = dumps(payload)
    while len(text) > cap:
        longest = _longest_list(payload)
        if longest is None:
            return text[: cap - 1] + "…"
        del longest[(len(longest) + 1) // 2 :]
        payload["truncated"] = "Some rows were left out to keep this short."
        text = dumps(payload)
    return text


def for_model(outcome: Outcome) -> str:
    if not outcome.valid:
        return dumps(
            {
                "error": "invalid_arguments",
                "message": f"{outcome.error} Fix the arguments and call the tool again.",
            }
        )
    result = outcome.result
    assert result is not None
    payload: dict[str, Any] = {"tool": outcome.call.name}
    if result.error:
        payload.update(result.data)
    else:
        payload["data"] = json.loads(dumps(result.data))
    if result.warnings:
        payload["warnings"] = result.warnings
    if result.sources:
        payload["sources"] = [
            {"n": n, "label": s.label}
            for n, s in zip(outcome.source_numbers, result.sources, strict=False)
        ]
    return fit(payload, result_cap_chars())


def numbered_sources(outcomes: list[Outcome]) -> list[dict[str, Any]]:
    """Every source of the valid calls with its number, once per link."""
    seen: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if not outcome.valid or outcome.result is None:
            continue
        for n, source in zip(outcome.source_numbers, outcome.result.sources, strict=False):
            if source.link not in seen:
                seen[source.link] = {"n": n, **source.as_dict()}
    return list(seen.values())


def assign_numbers(outcome: Outcome, next_number: int, known: dict[str, int]) -> int:
    """Give each new source the next number; a link seen before keeps its number."""
    if not outcome.valid or outcome.result is None:
        return next_number
    numbers = []
    for source in outcome.result.sources:
        if source.link not in known:
            known[source.link] = next_number
            next_number += 1
        numbers.append(known[source.link])
    outcome.source_numbers = numbers
    return next_number
