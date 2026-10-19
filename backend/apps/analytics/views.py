from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services.buckets import GROUP_BY
from apps.analytics.services.oee_data import NoCountingMachineError
from apps.analytics.services.report import TooManyBucketsError, oee_report
from apps.organizations.models import ProductionLine
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import scope_to_user
from apps.production.views import aware_datetime_param

MAX_RANGE = timedelta(days=92)


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

        try:
            body = oee_report(line, start, end, group_by, timezone.now())
        except NoCountingMachineError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        except TooManyBucketsError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response(body)
