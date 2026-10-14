from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import QuerySet
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import Factory, Machine, ProductionLine
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import scope_to_user
from apps.production.authentication import HasLineApiKey, LineApiKeyAuthentication
from apps.production.models import MachineStateEvent, ProductionEvent
from apps.production.serializers import (
    AwareDateTimeField,
    MachineStateEventSerializer,
    ProductionEventSerializer,
)
from apps.production.services.ingestion import ingest_batch, ingest_event
from apps.production.services.line_status import get_line_status
from apps.production.services.shifts import current_shift, shift_periods

STATUS_CODES = {
    "created": status.HTTP_201_CREATED,
    "duplicate": status.HTTP_200_OK,
    "rejected": status.HTTP_400_BAD_REQUEST,
}


# --- Ingestion (line API key only) -----------------------------------------------------


class EventIngestionView(APIView):
    authentication_classes = [LineApiKeyAuthentication]
    permission_classes = [HasLineApiKey]
    parser_classes = [JSONParser]


class EventView(EventIngestionView):
    """POST /api/v1/events/ — one event."""

    def post(self, request: Request) -> Response:
        result = ingest_event(request.auth, request.data)
        return Response(result.as_dict(), status=STATUS_CODES[result.status])


class EventBatchView(EventIngestionView):
    """POST /api/v1/events/batch/ — a JSON list of events; one result per event."""

    def post(self, request: Request) -> Response:
        events = request.data
        max_size = settings.EVENT_BATCH_MAX_SIZE
        if not isinstance(events, list):
            raise ValidationError({"detail": "The body must be a JSON list of events."})
        if not 1 <= len(events) <= max_size:
            raise ValidationError({"detail": f"A batch must contain 1 to {max_size} events."})

        results = ingest_batch(request.auth, events)
        summary = {"created": 0, "duplicate": 0, "rejected": 0}
        for result in results:
            summary[result.status] += 1
        return Response(
            {
                "summary": summary,
                "results": [{"index": i, **r.as_dict()} for i, r in enumerate(results)],
            }
        )


# --- Reading (users, tenant-scoped) ----------------------------------------------------


class EventPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


def aware_datetime_param(request: Request, name: str) -> datetime | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        return AwareDateTimeField().to_internal_value(raw)
    except ValidationError as exc:
        raise ValidationError({name: exc.detail}) from None


class MachineEventListView(generics.ListAPIView):
    """Events of one machine, ordered by timestamp; filter with ?start=&end= (end excluded)."""

    permission_classes = [IsAuthenticated, HasMembership]
    pagination_class = EventPagination
    event_model: type[MachineStateEvent] | type[ProductionEvent]

    def get_queryset(self) -> QuerySet:
        machines = scope_to_user(Machine.objects.all(), self.request.user, "line__factory")
        machine = get_object_or_404(machines, pk=self.kwargs["machine_id"])

        queryset = self.event_model.objects.filter(machine=machine)
        start = aware_datetime_param(self.request, "start")
        end = aware_datetime_param(self.request, "end")
        if start is not None:
            queryset = queryset.filter(timestamp__gte=start)
        if end is not None:
            queryset = queryset.filter(timestamp__lt=end)
        return queryset.order_by("timestamp", "id")


class MachineStateEventListView(MachineEventListView):
    event_model = MachineStateEvent
    serializer_class = MachineStateEventSerializer


class ProductionEventListView(MachineEventListView):
    event_model = ProductionEvent
    serializer_class = ProductionEventSerializer


class LineStatusView(APIView):
    """GET /api/v1/lines/{id}/status/ — current state of every machine on the line."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request, line_id: int) -> Response:
        lines = scope_to_user(
            ProductionLine.objects.select_related("factory"), request.user, "factory"
        )
        line = get_object_or_404(lines, pk=line_id)
        return Response(get_line_status(line))


class CurrentShiftView(APIView):
    """GET /api/v1/factories/{id}/current-shift/ -> the shift running now, or null."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request, factory_id: int) -> Response:
        factories = scope_to_user(Factory.objects.all(), request.user, "pk")
        factory = get_object_or_404(factories, pk=factory_id)
        shift = current_shift(factory, timezone.now())
        if shift is None:
            return JsonResponse(None, safe=False)  # a JSON `null` body
        return Response(
            {
                "shift_id": shift.shift_id,
                "name": shift.shift_name,
                "label": shift.label,
                "local_date": shift.local_date,
                "start": shift.start,
                "end": shift.end,
                "breaks": [{"start": start, "end": end} for start, end in shift.breaks],
                "factory_timezone": factory.timezone,
            }
        )


class ShiftOccurrencesView(APIView):
    """GET /api/v1/factories/{id}/shift-occurrences/?start=&end= — concrete shift periods
    (for range pickers such as "last shift"), computed by the shift service."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request, factory_id: int) -> Response:
        factories = scope_to_user(Factory.objects.all(), request.user, "pk")
        factory = get_object_or_404(factories, pk=factory_id)
        start = aware_datetime_param(request, "start")
        end = aware_datetime_param(request, "end")
        if start is None or end is None or end <= start:
            raise ValidationError({"detail": "start and end (with a timezone) are required."})
        if end - start > timedelta(days=31):
            raise ValidationError({"detail": "The range may be at most 31 days."})
        return Response(
            [
                {
                    "shift_id": p.shift_id,
                    "name": p.shift_name,
                    "label": p.label,
                    "local_date": p.local_date,
                    "start": p.start,
                    "end": p.end,
                }
                for p in shift_periods(factory, start, end)
            ]
        )
