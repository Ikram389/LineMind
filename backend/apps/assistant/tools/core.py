"""The building blocks of assistant tools.

- `Param`s describe arguments once: they produce both the strict JSON schema the model sees
  and the validation of what it sends back, so the two can never disagree.
- `ToolContext` carries the *authenticated* user. Tools never take a user, organization or
  factory from their arguments; every id the model passes is looked up through the tenant
  helpers, so another organization's line is simply "not found".
- `ToolResult` is what a tool returns: compact data, the sources it is built on (with
  frontend links), the service's warnings and the key metrics for the answer's table.
- User-written text (comments, reason names, titles) goes through `untrusted()`: it is
  wrapped in ⟦ ⟧ and the system prompt tells the model never to follow it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db.models import QuerySet

from apps.accounts.models import User
from apps.organizations.models import Machine, Organization, ProductionLine
from apps.organizations.tenancy import scope_to_user

MAX_RANGE = timedelta(days=92)  # the same limit as the analysis endpoints
UNTRUSTED_MAX = 200


class ArgumentError(ValueError):
    """The model's arguments are invalid. The message goes back to the model."""


class NotFound(LookupError):
    """An id the user may not see, or that does not exist (the same answer for both)."""


# --- Parameters ------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    name: str
    description: str
    required: bool = True

    def schema(self) -> dict[str, Any]:
        raise NotImplementedError

    def clean(self, value: Any) -> Any:
        raise NotImplementedError


@dataclass(frozen=True)
class IntParam(Param):
    def schema(self) -> dict[str, Any]:
        return {"type": "integer", "minimum": 1, "description": self.description}

    def clean(self, value: Any) -> int:
        # Small models often send "3" for 3: accept digits, nothing fancier.
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ArgumentError(f"{self.name} must be a positive whole number (an id).")
        return value


@dataclass(frozen=True)
class ChoiceParam(Param):
    choices: tuple[str, ...] = ()
    default: str | None = None

    def schema(self) -> dict[str, Any]:
        return {"type": "string", "enum": list(self.choices), "description": self.description}

    def clean(self, value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in self.choices:
            raise ArgumentError(f"{self.name} must be one of: {', '.join(self.choices)}.")
        return value.strip()


@dataclass(frozen=True)
class TextParam(Param):
    max_length: int = 50

    def schema(self) -> dict[str, Any]:
        return {"type": "string", "maxLength": self.max_length, "description": self.description}

    def clean(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > self.max_length:
            raise ArgumentError(f"{self.name} must be a short text.")
        return value.strip()


def parse_instant(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise ArgumentError(f"{name} must be an ISO date-time like 2026-10-12T06:00:00Z.")
    try:
        moment = datetime.fromisoformat(value.strip().replace("z", "Z"))
    except ValueError:
        raise ArgumentError(
            f"{name} must be an ISO date-time like 2026-10-12T06:00:00Z. "
            "Use the start and end returned by resolve_time_range."
        ) from None
    if moment.tzinfo is None:
        raise ArgumentError(
            f"{name} needs a timezone (end it with Z). Use the values from resolve_time_range."
        )
    return moment


@dataclass(frozen=True)
class InstantParam(Param):
    def schema(self) -> dict[str, Any]:
        return {"type": "string", "format": "date-time", "description": self.description}

    def clean(self, value: Any) -> datetime:
        return parse_instant(self.name, value)


@dataclass(frozen=True)
class DateParam(Param):
    def schema(self) -> dict[str, Any]:
        return {"type": "string", "format": "date", "description": self.description}

    def clean(self, value: Any) -> date:
        try:
            return date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            raise ArgumentError(f"{self.name} must be a date like 2026-10-12.") from None


@dataclass(frozen=True)
class RangeParam(Param):
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "description": self.description,
            "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
            },
            "required": ["start", "end"],
            "additionalProperties": False,
        }

    def clean(self, value: Any) -> tuple[datetime, datetime]:
        if not isinstance(value, dict) or set(value) != {"start", "end"}:
            raise ArgumentError(f"{self.name} must be an object with start and end.")
        return parse_instant(f"{self.name}.start", value["start"]), parse_instant(
            f"{self.name}.end", value["end"]
        )


LINE = IntParam("line_id", "The line id (from list_lines).")
RANGE_ID = TextParam(
    "range_id",
    "The range_id from resolve_time_range or a ready-made range (e.g. today, this_week).",
    required=False,
    max_length=40,
)
# Data tools take a range_id (preferred) or exactly the start/end LineMind returned.
START = InstantParam("start", "Only if exactly the start returned by LineMind.", required=False)
END = InstantParam("end", "Only if exactly the end returned by LineMind.", required=False)


# --- Context, sources, results -------------------------------------------------------


@dataclass(frozen=True)
class KnownRange:
    range_id: str
    start: datetime
    end: datetime
    label: str


@dataclass
class RangeBook:
    """The ranges LineMind resolved during one question: from resolve_time_range, the
    prompt's ready-made ranges, the screen the user asked from, or a changeover. Data tools
    only accept these, so the model can never invent timestamps."""

    entries: dict[str, KnownRange] = field(default_factory=dict)

    def add(
        self, start: datetime, end: datetime, label: str, range_id: str | None = None
    ) -> KnownRange:
        for known in self.entries.values():  # the same span keeps one id
            if known.start == start and known.end == end:
                return known
        rid = (
            range_id
            or f"r{sum(1 for k in self.entries if k.startswith('r') and k[1:].isdigit()) + 1}"
        )
        known = KnownRange(rid, start, end, label)
        self.entries[rid] = known
        return known

    def get(self, range_id: str) -> KnownRange | None:
        return self.entries.get(range_id.strip())

    def match(self, start: datetime, end: datetime) -> KnownRange | None:
        return next((k for k in self.entries.values() if k.start == start and k.end == end), None)


NOT_RESOLVED = (
    "This time range was not resolved by LineMind. Call resolve_time_range first (or use a "
    "ready-made range) and pass its range_id."
)


@dataclass
class ToolContext:
    user: User
    organization: Organization
    now: datetime
    ranges: RangeBook = field(default_factory=RangeBook)

    def lines(self) -> QuerySet[ProductionLine]:
        return scope_to_user(
            ProductionLine.objects.select_related("factory", "counting_machine"),
            self.user,
            "factory",
        )

    def line(self, line_id: int) -> ProductionLine:
        line = self.lines().filter(pk=line_id).first()
        if line is None:
            raise NotFound(f"No line with id {line_id} is available to you.")
        return line

    def machine(self, line: ProductionLine, machine_id: int) -> Machine:
        machine = scope_to_user(Machine.objects.filter(line=line), self.user, "line__factory")
        found = machine.filter(pk=machine_id).first()
        if found is None:
            raise NotFound(f"No machine with id {machine_id} on line {line.pk} is available.")
        return found


@dataclass(frozen=True)
class Source:
    type: str  # line, downtime, incident, quality, maintenance_action, alert, machine
    id: int | None
    label: str
    link: str

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id, "label": self.label, "link": self.link}


@dataclass
class ToolResult:
    data: dict[str, Any]
    sources: list[Source] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # [{"label": "OEE", "value": 78.4, "unit": "%"}]: the answer's small metrics table.
    key_metrics: list[dict[str, Any]] = field(default_factory=list)
    resolved_range: dict[str, Any] | None = None
    error: str | None = None  # "not_found", "no_data", "invalid_range", "failed"


@dataclass(frozen=True)
class RangeSlot:
    """Where a tool takes a time range: a range id, or a start/end pair that must match a
    range LineMind resolved. The resolved range is put back as `start`/`end` (or as the
    `pair` argument, e.g. compare_periods' range_a)."""

    id_param: str = "range_id"
    pair: str | None = None  # None: the "start" and "end" arguments
    required: bool = True


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[tuple[Param, ...]] = ()
    ranges: ClassVar[tuple[RangeSlot, ...]] = ()

    def range_required(self, args: dict[str, Any], slot: RangeSlot) -> bool:
        """Some tools need a range only in some cases (e.g. a list, not one item)."""
        return slot.required

    def resolve_ranges(self, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        """Replace range ids (or matching start/end) by the ranges LineMind resolved."""
        args = dict(args)
        for slot in self.ranges:
            rid = args.pop(slot.id_param, None)
            if slot.pair is None:
                pair = (
                    (args.get("start"), args.get("end"))
                    if "start" in args or "end" in args
                    else None
                )
            else:
                pair = args.get(slot.pair)
            known: KnownRange | None = None
            if rid is not None:
                known = ctx.ranges.get(rid)
                if known is None:
                    raise ArgumentError(f"Unknown {slot.id_param} {rid!r}. {NOT_RESOLVED}")
            elif pair is not None:
                start, end = pair
                if start is None or end is None:
                    raise ArgumentError(f"Give both start and end, or a range_id. {NOT_RESOLVED}")
                known = ctx.ranges.match(start, end)
                if known is None:
                    raise ArgumentError(NOT_RESOLVED)
            elif self.range_required(args, slot):
                raise ArgumentError(f"{slot.id_param} is required. {NOT_RESOLVED}")
            if known is not None:
                if slot.pair is None:
                    args["start"], args["end"] = known.start, known.end
                else:
                    args[slot.pair] = (known.start, known.end)
        return args

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {p.name: p.schema() for p in self.params},
                    "required": [p.name for p in self.params if p.required],
                    "additionalProperties": False,
                },
            },
        }

    def validate(self, raw: Any) -> dict[str, Any]:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ArgumentError("Arguments must be a JSON object.")
        known = {p.name: p for p in self.params}
        unknown = sorted(set(raw) - set(known))
        if unknown:
            raise ArgumentError(
                f"Unknown argument(s): {', '.join(unknown)}. Allowed: {', '.join(known)}."
            )
        args: dict[str, Any] = {}
        for param in self.params:
            value = raw.get(param.name)
            if value is None or value == "":
                if param.required:
                    raise ArgumentError(f"{param.name} is required: {param.description}")
                default = getattr(param, "default", None)
                if default is not None:
                    args[param.name] = default
                continue
            args[param.name] = param.clean(value)
        self.check(args)
        return args

    def check(self, args: dict[str, Any]) -> None:
        """Rules between arguments (e.g. end after start). Raise ArgumentError."""
        if "start" in args and "end" in args:
            check_range(args["start"], args["end"])

    def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


def check_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ArgumentError("end must be after start.")
    if end - start > MAX_RANGE:
        raise ArgumentError("The range may be at most 92 days.")


# --- Formatting ------------------------------------------------------------------------


def untrusted(text: str | None) -> str | None:
    """User-written text, delimited so the model treats it as data (see the system prompt)."""
    if text is None or text == "":
        return None
    clean = " ".join(str(text).replace("⟦", "[").replace("⟧", "]").split())
    if len(clean) > UNTRUSTED_MAX:
        clean = clean[: UNTRUSTED_MAX - 1] + "…"
    return f"⟦{clean}⟧"


def local(moment: datetime | None, zone: str) -> str | None:
    """A UTC instant in factory time, e.g. "Mon 12 Oct 2026 10:05"."""
    if moment is None:
        return None
    return moment.astimezone(ZoneInfo(zone)).strftime("%a %d %b %Y %H:%M")


def range_label(start: datetime, end: datetime, zone: str) -> str:
    tz = ZoneInfo(zone)
    a, b = start.astimezone(tz), end.astimezone(tz)
    if a.date() == b.date():
        return f"{a:%a %d %b %Y %H:%M}–{b:%H:%M} ({zone})"
    return f"{a:%a %d %b %Y %H:%M} – {b:%a %d %b %Y %H:%M} ({zone})"


def iso(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def pct(ratio: float | None, digits: int = 1) -> float | None:
    return None if ratio is None else round(ratio * 100, digits)


def minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def hours(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 3600, 2)


# --- Links (the frontend screens a source opens) ---------------------------------------


def _query(**params: Any) -> str:
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return f"?{urlencode(clean)}" if clean else ""


def overview_link(line_id: int) -> str:
    return f"/lines/{line_id}"


def machine_link(line_id: int, machine_id: int) -> str:
    return f"/lines/{line_id}/machines/{machine_id}"


def downtime_link(line_id: int, start: datetime, end: datetime, **filters: Any) -> str:
    view = filters.pop("view", None)
    return f"/lines/{line_id}/downtime" + _query(
        start=iso(start), end=iso(end), view=None if view == "line" else view, **filters
    )


def incident_link(line_id: int, incident_id: int, start: datetime, end: datetime) -> str:
    return f"/lines/{line_id}/downtime" + _query(
        start=iso(start), end=iso(end), incident=incident_id
    )


def quality_link(line_id: int, start: datetime, end: datetime, **filters: Any) -> str:
    return f"/lines/{line_id}/quality" + _query(start=iso(start), end=iso(end), **filters)


def action_link(action_id: int) -> str:
    return f"/maintenance/{action_id}"


def alert_link(alert_id: int) -> str:
    return f"/alerts{_query(alert=alert_id)}"


def metric(label: str, value: Any, unit: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit}
