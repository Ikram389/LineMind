"""Production orders: which product a line makes when, and its ideal cycle time."""

from datetime import datetime
from fractions import Fraction

from django.db.models import QuerySet
from django.db.models.functions import Coalesce

from apps.organizations.models import ProductionLine
from apps.production.models import OrderStatus, Product, ProductionOrder


def active_orders(line: ProductionLine) -> QuerySet[ProductionOrder]:
    """Non-cancelled orders with their effective interval annotated."""
    return (
        ProductionOrder.objects.filter(line=line)
        .exclude(status=OrderStatus.CANCELLED)
        .annotate(
            effective_from=Coalesce("actual_start", "scheduled_start"),
            effective_to=Coalesce("actual_end", "scheduled_end"),
        )
    )


def overlapping_orders(
    line: ProductionLine, start: datetime, end: datetime, exclude_pk: int | None = None
) -> QuerySet[ProductionOrder]:
    orders = active_orders(line).filter(effective_from__lt=end, effective_to__gt=start)
    if exclude_pk is not None:
        orders = orders.exclude(pk=exclude_pk)
    return orders


def ideal_cycle_time(product: Product, line: ProductionLine) -> Fraction:
    """The line-specific override if there is one, otherwise the product's value (seconds)."""
    override = product.line_cycle_times.filter(line=line).first()
    value = override.ideal_cycle_time_seconds if override else product.ideal_cycle_time_seconds
    return Fraction(value)
