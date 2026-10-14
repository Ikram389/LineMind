"""Load everything the OEE calculation needs for one line and range, in a few queries.

The calculation itself (services/oee.py) never touches the database.
"""

from datetime import datetime
from fractions import Fraction

from django.db.models import Max, Min
from django.utils import timezone

from apps.analytics.services.oee import DowntimeSpan, LineData, OrderSpan
from apps.downtime.models import DowntimeEvent
from apps.organizations.models import Machine, ProductionLine
from apps.organizations.oee_settings import with_defaults
from apps.production.models import IngestedEvent
from apps.production.services.counters import load_readings, upstream_machines
from apps.production.services.orders import active_orders, ideal_cycle_time
from apps.production.services.shifts import ShiftPeriod, shift_periods
from apps.production.services.timeset import TimeSet


class NoCountingMachineError(ValueError):
    pass


def load_line_data(
    line: ProductionLine, start: datetime, end: datetime, now: datetime | None = None
) -> tuple[LineData, list[ShiftPeriod]]:
    now = now or timezone.now()
    end = min(end, now)
    factory = line.factory
    machine = line.output_machine()
    if machine is None:
        raise NoCountingMachineError("This line has no machines.")

    periods = shift_periods(factory, start, end) if end > start else []
    shift_time = TimeSet.of((p.start, p.end) for p in periods)
    breaks = TimeSet.of(b for p in periods for b in p.breaks)

    downtime = tuple(
        DowntimeSpan(
            start=event.started_at,
            end=event.ended_at or now,
            category=event.category,
            is_changeover=bool(
                event.current_classification and event.current_classification.reason.is_changeover
            ),
        )
        for event in DowntimeEvent.objects.filter(machine=machine, is_obsolete=False)
        .filter(started_at__lt=end)
        .exclude(ended_at__lte=start)
        .select_related("current_classification__reason")
    )

    readings = load_readings(machine, start, end)
    upstream_readings = tuple(
        (m.external_id, tuple(load_readings(m, start, end))) for m in upstream_machines(line)
    )

    orders = tuple(
        OrderSpan(
            start=order.effective_from,
            end=order.effective_to,
            sku=order.product.sku,
            name=order.product.name,
            ideal_cycle_time=ideal_cycle_time(order.product, line),
        )
        for order in active_orders(line)
        .filter(effective_from__lt=end, effective_to__gt=start)
        .select_related("product")
    )

    slowest = Machine.objects.filter(line=line).aggregate(speed=Min("nominal_speed_per_hour"))[
        "speed"
    ]
    seen = IngestedEvent.objects.filter(machine=machine, timestamp__lte=now).aggregate(
        first=Min("timestamp"), last=Max("timestamp")
    )

    data = LineData(
        shift_time=shift_time,
        breaks=breaks,
        downtime=downtime,
        readings=tuple(readings),
        orders=orders,
        fallback_cycle_time=Fraction(3600, slowest) if slowest else None,
        first_seen=seen["first"],
        last_seen=seen["last"],
        stale_after_seconds=factory.stale_after_seconds,
        settings=with_defaults(factory.oee_settings),
        now=now,
        upstream_readings=upstream_readings,
    )
    return data, periods
