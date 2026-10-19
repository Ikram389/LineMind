"""The number check: is every number in an answer backed by LineMind's data?

1. Find the numbers in the answer (Arabic-Indic digits, "1,234", "1 234", "12.5", the French
   "12,5"; times and dates split into their parts; "[1]" source markers skipped).
2. Collect the allowed values from this question's tool results, with derived forms:
   seconds ↔ minutes ↔ hours and their "1 h 20 min" parts.
3. A number is *verified* if it is one of those values rounded at the precision written
   ("78.4" or "78" for 78.396; not "79").
4. Otherwise, if it appears in the user's question it is *from the question*: shown apart,
   never counted as verified ("Was OEE above 85%?" → "OEE was 85%" is not confirmed).
   Numbers from LineMind's own context (current time, shift times, line ids) count as
   verified. Everything else is *unverified*: marked in the UI and logged.
   Numbers inside user-written text (⟦…⟧: comments, titles) never verify anything.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
# Digits, optionally grouped by , . or (thin/non-breaking) spaces: "1,234.5", "1 234", "12,5".
TOKEN = re.compile(r"\d+(?:(?:[.,]|[   ](?=\d{3}(?!\d)))\d+)*")
SPACES = "   "


@dataclass(frozen=True)
class Found:
    text: str
    start: int
    end: int
    # Possible readings: (value, decimals written). "1,500" may be 1500 or 1.5.
    readings: tuple[tuple[Decimal, int], ...]


def normalize(text: str) -> str:
    """Arabic-Indic digits and separators to ASCII. Keeps every character's position."""
    return text.translate(DIGITS)


def _readings(token: str) -> tuple[tuple[Decimal, int], ...]:
    parts = re.split(r"([.,   ])", token)
    numbers, seps = parts[0::2], parts[1::2]
    if not seps:
        return ((Decimal(token), 0),)
    readings: list[tuple[Decimal, int]] = []
    groups_of_three = all(len(n) == 3 for n in numbers[1:])
    if groups_of_three and len(numbers[0]) <= 3:
        readings.append((Decimal("".join(numbers)), 0))  # all separators are thousands
    last = seps[-1]
    if last in ".,":
        head = numbers[:-1]
        head_ok = len(head) == 1 or (len(head[0]) <= 3 and all(len(n) == 3 for n in head[1:]))
        if head_ok:
            try:
                value = Decimal("".join(head) + "." + numbers[-1])
                readings.append((value, len(numbers[-1])))
            except InvalidOperation:
                pass
    if not readings:  # e.g. "1 2 3": separate numbers
        readings = [(Decimal(n), 0) for n in numbers]
    return tuple(dict.fromkeys(readings))


def find_numbers(text: str) -> list[Found]:
    clean = normalize(text)
    found = []
    for match in TOKEN.finditer(clean):
        start, end = match.span()
        token = match.group().rstrip(SPACES + ".,")
        end = start + len(token)
        if not token:
            continue
        if start > 0 and clean[start - 1] == "[" and clean[end : end + 1] == "]":
            continue  # a source marker like [2]
        before = clean[start - 1] if start > 0 else ""
        if before == "_" or (before.isascii() and before.isalpha()):
            # A code like M05 or Q03, not a quantity. (Arabic letters are fine: "و٥٣٣٥"
            # is "and 5335", the conjunction is written attached to the number.)
            continue
        found.append(Found(text[start:end], start, end, _readings(token)))
    return found


# --- Allowed values ----------------------------------------------------------------


def _with_derived(value: Decimal, key: str) -> Iterable[Decimal]:
    yield value
    yield abs(value)
    key = key.lower()
    if "second" in key:
        yield value / 60
        yield value / 3600
        yield from _parts(abs(value))
    elif "minute" in key:
        yield value / 60
        yield value * 60
        yield from _parts(abs(value) * 60)
    elif "hour" in key:
        yield value * 60
        yield from _parts(abs(value) * 3600)


def _parts(seconds: Decimal) -> Iterable[Decimal]:
    """The pieces of "2 d 3 h 20 min 5 s", as people write durations."""
    total = int(seconds)
    days, rest = divmod(total, 86400)
    hrs, rest = divmod(rest, 3600)
    mins, secs = divmod(rest, 60)
    yield from (Decimal(days), Decimal(hrs), Decimal(mins), Decimal(secs))
    yield Decimal(total // 3600)  # "26 h 5 min" without days
    yield Decimal(total // 60)


def collect_values(obj: Any, key: str = "", out: set[Decimal] | None = None) -> set[Decimal]:
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, int | float | Decimal):
        try:
            out.update(_with_derived(Decimal(str(obj)), key))
        except InvalidOperation:
            pass
    elif isinstance(obj, str):
        if obj.startswith("⟦"):
            return out  # text typed by people is data, never evidence for a number
        for found in find_numbers(obj):
            for value, _ in found.readings:
                out.add(value)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            collect_values(v, str(k), out)
    elif isinstance(obj, list | tuple):
        for item in obj:
            collect_values(item, key, out)
    return out


class ValueSet:
    def __init__(self, values: Iterable[Decimal]) -> None:
        self.values = sorted(set(values))

    def matches(self, value: Decimal, decimals: int) -> bool:
        """Is some allowed value equal to `value` once rounded to `decimals` places?"""
        tolerance = Decimal(5).scaleb(-(decimals + 1)) + Decimal("1e-9")
        i = bisect.bisect_left(self.values, value - tolerance)
        return i < len(self.values) and self.values[i] <= value + tolerance


def check_numbers(
    answer: str, tool_data: Any, question: str, context: Any = None
) -> dict[str, Any]:
    tools = ValueSet(collect_values(tool_data))
    trusted_context = ValueSet(collect_values(context)) if context is not None else ValueSet([])
    asked = ValueSet(collect_values(question))
    items = []
    for found in find_numbers(answer):

        def any_match(values: ValueSet, found: Found = found) -> bool:
            return any(values.matches(v, d) for v, d in found.readings)

        if any_match(tools) or any_match(trusted_context):
            status = "verified"
        elif any_match(asked):
            status = "from_question"
        else:
            status = "unverified"
        items.append({"text": found.text, "start": found.start, "end": found.end, "status": status})
    counts = {
        s: sum(1 for i in items if i["status"] == s)
        for s in ("verified", "from_question", "unverified")
    }
    return {"items": items, **counts}
