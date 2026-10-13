from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services.buckets import (
    GROUP_BY,
    Bucket,
    day_buckets,
    hour_buckets,
    shift_buckets,
)
from apps.analytics.services.oee import calculate, compute_inputs, result_to_dict, sum_inputs
from apps.analytics.services.oee_data import NoCountingMachineError, load_line_data
from apps.organizations.models import ProductionLine
from apps.organizations.oee_settings import with_defaults
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import scope_to_user
from apps.production.views import aware_datetime_param

MAX_RANGE = timedelta(days=92)
MAX_BUCKETS = 1000


class LineOEEView(APIView):
    """GET /api/v1/lines/{id}/oee/?start=&end=[&group_by=hour|day|shift]

    With group_by, the total is calculated from the summed inputs of the buckets,
    never by averaging bucket percentages.
    """

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request, line_id: int) -> Response:
        lines = scope_to_user(
            ProductionLine.objects.select_related("factory", "counting_machine"),
            request.user,
            "factory",
        )
        line = get_object_or_404(lines, pk=line_id)

        start = aware_datetime_param(request, "start")
        end = aware_datetime_param(request, "end")
        if start is None or end is None:
            raise ValidationError({"detail": "Both 'start' and 'end' are required."})
        if end <= start:
            raise ValidationError({"end": "Must be after start."})
        if end - start > MAX_RANGE:
            raise ValidationError({"detail": f"The range may be at most {MAX_RANGE.days} days."})
        group_by = request.query_params.get("group_by") or None
        if group_by is not None and group_by not in GROUP_BY:
            raise ValidationError({"group_by": f"Must be one of: {', '.join(GROUP_BY)}."})

        now = timezone.now()
        try:
            data, periods = load_line_data(line, start, end, now)
        except NoCountingMachineError as exc:
            raise ValidationError({"detail": str(exc)}) from None

        body: dict[str, Any] = {
            "line": {"id": line.id, "name": line.name},
            "counting_machine": line.output_machine().external_id,
            "factory_timezone": line.factory.timezone,
            "range": {"start": start, "end": end},
            "settings": with_defaults(line.factory.oee_settings),
        }
        if group_by is None:
            body["total"] = result_to_dict(calculate(compute_inputs(data, start, end)))
            return Response(body)

        buckets = self._buckets(
            group_by, start, min(end, now), periods, ZoneInfo(line.factory.timezone)
        )
        if len(buckets) > MAX_BUCKETS:
            raise ValidationError({"detail": f"Too many buckets (max {MAX_BUCKETS})."})
        bucket_inputs = [compute_inputs(data, b.start, b.end) for b in buckets]
        total_inputs = sum_inputs(bucket_inputs)
        if end > now:
            total_inputs.range_in_future = True
            total_inputs.computed_until = now
        body["group_by"] = group_by
        body["total"] = result_to_dict(calculate(total_inputs))
        body["buckets"] = [
            {"label": b.label, "start": b.start, "end": b.end, **result_to_dict(calculate(i))}
            for b, i in zip(buckets, bucket_inputs, strict=True)
        ]
        return Response(body)

    @staticmethod
    def _buckets(group_by: str, start: Any, end: Any, periods: Any, tz: ZoneInfo) -> list[Bucket]:
        if end <= start:
            return []
        if group_by == "hour":
            return hour_buckets(start, end, tz)
        if group_by == "day":
            return day_buckets(start, end, tz)
        return shift_buckets(start, end, periods)
