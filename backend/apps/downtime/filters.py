"""Query-parameter filters for downtime lists and analysis.

Everything time-based goes through a single (start, end) window; `?shift=&date=`
turns one shift occurrence into that window. The analysis endpoints and the
events list read the same parameters, so a view can be bookmarked and the CSV
export matches the table.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import DurationField, ExpressionWrapper, F, Q, QuerySet
from django.db.models.functions import Coalesce, Now
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from apps.downtime.models import DowntimeCategory, IncidentOrigin
from apps.downtime.services.analysis import (
    LINE_VIEW,
    OPTIONAL_CATEGORIES,
    VIEWS,
    AnalysisFilters,
    needs_reason_ids,
    select_entries,
)
from apps.downtime.services.windows import Window
from apps.organizations.models import ProductionLine
from apps.organizations.tenancy import scope_to_user
from apps.organizations.views import integer_query_param
from apps.production.models import Shift
from apps.production.services.shifts import occurrence
from apps.production.views import aware_datetime_param

MAX_ANALYSIS_RANGE = timedelta(days=92)
ORDERINGS = {
    "started_at": ("started_at", "machine__position", "id"),
    "-started_at": ("-started_at", "machine__position", "-id"),
    "duration": ("duration", "started_at", "id"),
    "-duration": ("-duration", "started_at", "id"),
    "machine": ("machine__position", "started_at", "id"),
    "-machine": ("-machine__position", "started_at", "id"),
}


def time_window(request: Request) -> Window:
    """The (start, end) window from ?start=&end=, narrowed by ?shift=<id>&date=YYYY-MM-DD."""
    start = aware_datetime_param(request, "start")
    end = aware_datetime_param(request, "end")
    shift_window = _shift_window(request)
    if shift_window is not None:
        start = shift_window.start if start is None else max(start, shift_window.start)
        end = shift_window.end if end is None else min(end, shift_window.end)
    return Window(start, end)


def _shift_window(request: Request) -> Window | None:
    shift_id = integer_query_param(request, "shift")
    if shift_id is None:
        return None
    raw_date = request.query_params.get("date")
    if not raw_date:
        raise ValidationError({"date": "Is required with 'shift' (YYYY-MM-DD, factory time)."})
    try:
        local_date = date.fromisoformat(raw_date)
    except ValueError:
        raise ValidationError({"date": "Must be a date like 2026-10-13."}) from None
    shift = (
        scope_to_user(Shift.objects.select_related("factory"), request.user, "factory")
        .prefetch_related("breaks")
        .filter(pk=shift_id)
        .first()
    )
    if shift is None:
        raise ValidationError({"shift": "Unknown shift."})
    period = occurrence(shift, local_date, ZoneInfo(shift.factory.timezone))
    return Window(period.start, period.end)


def bool_query_param(request: Request, name: str) -> bool | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    if raw.lower() in {"true", "1", "yes"}:
        return True
    if raw.lower() in {"false", "0", "no"}:
        return False
    raise ValidationError({name: "Must be true or false."})


def choice_query_param(request: Request, name: str, choices: list[str]) -> str | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        raise ValidationError({name: f"Must be one of: {', '.join(choices)}."})
    return raw


def list_query_param(request: Request, name: str, choices: list[str]) -> frozenset[str] | None:
    """Comma-separated values, e.g. ?category=breakdown,blocked."""
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    values = frozenset(v.strip() for v in raw.split(",") if v.strip())
    unknown = sorted(values - set(choices))
    if unknown:
        raise ValidationError({name: f"Unknown value(s): {', '.join(unknown)}."})
    return values


def float_query_param(request: Request, name: str) -> float | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValidationError({name: "Must be a number of seconds."}) from None
    if value < 0:
        raise ValidationError({name: "Cannot be negative."})
    return value


# --- Analysis (pareto, summary, recurring, view=line lists) -----------------------------


def analysis_scope(request: Request) -> tuple[list[ProductionLine], AnalysisFilters]:
    """The lines the user may analyse (?line= narrows) and the filters from the URL."""
    lines = scope_to_user(ProductionLine.objects.select_related("factory"), request.user, "factory")
    line_id = integer_query_param(request, "line")
    if line_id is not None:
        lines = lines.filter(pk=get_object_or_404(lines, pk=line_id).pk)

    window = time_window(request)
    if window.start is None or window.end is None:
        raise ValidationError({"detail": "A range is required: start and end, or shift and date."})
    if window.end <= window.start:
        raise ValidationError({"end": "Must be after start."})
    if window.end - window.start > MAX_ANALYSIS_RANGE:
        raise ValidationError(
            {"detail": f"The range may be at most {MAX_ANALYSIS_RANGE.days} days."}
        )

    include = list_query_param(request, "include", sorted(OPTIONAL_CATEGORIES)) or frozenset()
    filters = AnalysisFilters(
        start=window.start,
        end=window.end,
        now=timezone.now(),
        view=choice_query_param(request, "view", list(VIEWS)) or LINE_VIEW,
        include=include,
        machine_id=integer_query_param(request, "machine"),
        categories=list_query_param(request, "category", DowntimeCategory.values),
        reason=request.query_params.get("reason") or None,
        alarm=request.query_params.get("alarm") or None,
        classified=bool_query_param(request, "classified"),
        min_duration=float_query_param(request, "min_duration"),
        max_duration=float_query_param(request, "max_duration"),
    )
    return list(lines), filters


# --- Events list -----------------------------------------------------------------------


def with_duration(queryset: QuerySet) -> QuerySet:
    """Annotate the full duration (ongoing stops: up to now) as `duration`."""
    return queryset.annotate(
        duration=ExpressionWrapper(
            Coalesce(F("ended_at"), Now()) - F("started_at"), output_field=DurationField()
        )
    )


def filter_downtime_events(queryset: QuerySet, request: Request) -> QuerySet:
    for param, field in [
        ("line", "line_id"),
        ("machine", "machine_id"),
        ("factory", "line__factory_id"),
        ("incident", "incident_id"),
    ]:
        value = integer_query_param(request, param)
        if value is not None:
            queryset = queryset.filter(**{field: value})

    categories = list_query_param(request, "category", DowntimeCategory.values)
    if categories:
        queryset = queryset.filter(category__in=categories)

    reason = request.query_params.get("reason")
    if reason == "unclassified":
        queryset = queryset.filter(current_classification__isnull=True)
    elif reason:
        queryset = queryset.filter(current_classification__reason__code=reason)

    alarm = request.query_params.get("alarm")
    if alarm == "none":
        queryset = queryset.filter(Q(alarm_code__isnull=True) | Q(alarm_code=""))
    elif alarm:
        queryset = queryset.filter(alarm_code=alarm)

    classified = bool_query_param(request, "classified")
    if classified is not None:
        queryset = queryset.filter(current_classification__isnull=not classified)

    first = bool_query_param(request, "is_first_stop")
    if first is not None:
        queryset = queryset.filter(is_first_stop=first)

    queryset = with_duration(queryset)
    for param, lookup in (("min_duration", "gte"), ("max_duration", "lte")):
        seconds = float_query_param(request, param)
        if seconds is not None:
            queryset = queryset.filter(**{f"duration__{lookup}": timedelta(seconds=seconds)})

    window = time_window(request)
    queryset = queryset.filter(window.overlap_q())

    # The line view and the "needs a reason" queue are defined by the analysis service.
    view = choice_query_param(request, "view", list(VIEWS))
    needs_reason = bool_query_param(request, "needs_reason")
    if view == LINE_VIEW or needs_reason:
        lines, filters = analysis_scope(request)
        if view == LINE_VIEW:
            ids = [e.attributed.pk for e in select_entries(lines, filters)]
            queryset = queryset.filter(pk__in=ids)
        if needs_reason:
            queryset = queryset.filter(
                pk__in=needs_reason_ids(lines, filters.start, filters.end, filters.now)
            )

    ordering = request.query_params.get("ordering") or "started_at"
    if ordering not in ORDERINGS:
        raise ValidationError({"ordering": f"Must be one of: {', '.join(ORDERINGS)}."})
    return queryset.order_by(*ORDERINGS[ordering])


def filter_incidents(queryset: QuerySet, request: Request) -> QuerySet:
    line = integer_query_param(request, "line")
    if line is not None:
        queryset = queryset.filter(line_id=line)
    origin = choice_query_param(request, "origin", IncidentOrigin.values)
    if origin:
        queryset = queryset.filter(origin=origin)
    return queryset.filter(time_window(request).overlap_q())


def range_from(request: Request) -> tuple[datetime | None, datetime | None]:
    window = time_window(request)
    return window.start, window.end
