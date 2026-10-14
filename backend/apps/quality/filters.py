"""Query parameters of the quality endpoints -> (permitted lines, QualityFilters)."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from apps.downtime.filters import (
    MAX_ANALYSIS_RANGE,
    bool_query_param,
    choice_query_param,
    time_window,
)
from apps.organizations.models import ProductionLine
from apps.organizations.tenancy import scope_to_user
from apps.organizations.views import integer_query_param
from apps.quality.models import Severity, Verdict
from apps.quality.services.metrics import QualityFilters

ORDERINGS = {
    "timestamp": ("timestamp", "id"),
    "-timestamp": ("-timestamp", "-id"),
    "confidence": ("confidence", "timestamp", "id"),
    "-confidence": ("-confidence", "-timestamp", "-id"),
}


def quality_scope(
    request: Request, require_line: bool = False
) -> tuple[list[ProductionLine], QualityFilters]:
    """The lines the user may see (?line= narrows; 404 if not permitted) and the filters.

    A range is required: start and end, or shift and date (factory time), at most 92 days.
    """
    lines = scope_to_user(ProductionLine.objects.select_related("factory"), request.user, "factory")
    line_id = integer_query_param(request, "line")
    if line_id is not None:
        lines = lines.filter(pk=get_object_or_404(lines, pk=line_id).pk)
    elif require_line:
        raise ValidationError({"line": "Is required."})

    window = time_window(request)
    if window.start is None or window.end is None:
        raise ValidationError({"detail": "A range is required: start and end, or shift and date."})
    if window.end <= window.start:
        raise ValidationError({"end": "Must be after start."})
    if window.end - window.start > MAX_ANALYSIS_RANGE:
        raise ValidationError({"detail": "The range can be at most 92 days."})

    defect_type = request.query_params.get("defect_type") or None
    filters = QualityFilters(
        start=window.start,
        end=window.end,
        station_id=integer_query_param(request, "station"),
        machine_id=integer_query_param(request, "machine"),
        defect_type=defect_type.strip() if defect_type else None,
        severity=choice_query_param(request, "severity", list(Severity.values)),
        product_id=integer_query_param(request, "product"),
        reviewed=bool_query_param(request, "reviewed"),
        verdict=choice_query_param(request, "verdict", list(Verdict.values)),
    )
    return list(lines), filters


def ordering_param(request: Request) -> tuple[str, ...]:
    ordering = request.query_params.get("ordering") or "-timestamp"
    if ordering not in ORDERINGS:
        raise ValidationError({"ordering": f"Must be one of: {', '.join(ORDERINGS)}."})
    return ORDERINGS[ordering]
