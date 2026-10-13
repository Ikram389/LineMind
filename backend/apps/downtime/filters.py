"""Query-parameter filters for downtime lists.

Everything time-based goes through a single (start, end) window; `?shift=&date=`
turns one shift occurrence into that window.
"""

from datetime import date
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from apps.downtime.models import DowntimeCategory, IncidentOrigin
from apps.downtime.services.windows import Window
from apps.organizations.tenancy import scope_to_user
from apps.organizations.views import integer_query_param
from apps.production.models import Shift
from apps.production.services.shifts import occurrence
from apps.production.views import aware_datetime_param


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

    category = choice_query_param(request, "category", DowntimeCategory.values)
    if category:
        queryset = queryset.filter(category=category)

    reason = request.query_params.get("reason")
    if reason:
        queryset = queryset.filter(current_classification__reason__code=reason)

    classified = bool_query_param(request, "classified")
    if classified is not None:
        queryset = queryset.filter(current_classification__isnull=not classified)

    first = bool_query_param(request, "is_first_stop")
    if first is not None:
        queryset = queryset.filter(is_first_stop=first)

    return queryset.filter(time_window(request).overlap_q())


def filter_incidents(queryset: QuerySet, request: Request) -> QuerySet:
    line = integer_query_param(request, "line")
    if line is not None:
        queryset = queryset.filter(line_id=line)
    origin = choice_query_param(request, "origin", IncidentOrigin.values)
    if origin:
        queryset = queryset.filter(origin=origin)
    return queryset.filter(time_window(request).overlap_q())
