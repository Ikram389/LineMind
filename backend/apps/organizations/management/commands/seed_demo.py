"""Create demo data for development. Safe to run any number of times.

    docker compose exec backend python manage.py seed_demo

Every demo user gets the password from the DEMO_USER_PASSWORD environment variable.
"""

import os
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.downtime.default_reasons import ensure_default_reasons
from apps.notifications.defaults import ensure_default_rules
from apps.organizations.models import (
    Factory,
    Machine,
    Membership,
    Organization,
    ProductionLine,
    Role,
)
from apps.production.models import (
    OrderStatus,
    Product,
    ProductionOrder,
    Shift,
    ShiftBreak,
    all_days,
)
from apps.production.services.orders import overlapping_orders
from apps.quality.defaults import ensure_default_defect_types, ensure_demo_stations
from apps.quality.services.processing import rebuild_quality

DEMO_ORGANIZATION = "Demo Beverages"
DEMO_FACTORY = ("Algiers Plant", "Africa/Algiers")
DEMO_LINE = "Bottling Line 1"
DEMO_EMAIL_DOMAIN = "demo-beverages.test"

# (name, start, end, (break start, break end)) in factory time, every day.
DEMO_SHIFTS = [
    ("Morning", time(6), time(14), (time(10), time(10, 30))),
    ("Afternoon", time(14), time(22), (time(18), time(18, 30))),
    ("Night", time(22), time(6), (time(2), time(2, 30))),
]
# (sku, name, ideal cycle time in seconds)
DEMO_PRODUCTS = [
    ("W050", "Water 0.5 L", Decimal("0.6")),
    ("W150", "Water 1.5 L", Decimal("0.9")),
]
DEMO_ORDER_QUANTITY = 135_000  # 22.5 h of planned time at 6,000/h

OTHER_ORGANIZATION = "Other Company"
OTHER_FACTORY = ("Lyon Plant", "Europe/Paris")
OTHER_LINE = "Line A"
OTHER_EMAIL_DOMAIN = "other-company.test"

# (external_id, name, machine_type), in line order; position = index + 1.
DEMO_MACHINES = [
    ("M01", "Bottle feeder", "bottle_feeder"),
    ("M02", "Rinser", "rinser"),
    ("M03", "Filler", "filler"),
    ("M04", "Capper", "capper"),
    ("M05", "Labeler", "labeler"),
    ("M06", "Packer", "packer"),
]
DEMO_SPEED_PER_HOUR = 6000

OTHER_MACHINES = [
    ("M01", "Bottle feeder", "bottle_feeder"),
    ("M02", "Filler", "filler"),
    ("M03", "Capper", "capper"),
]
OTHER_SPEED_PER_HOUR = 4000


class Command(BaseCommand):
    help = "Create (or update) the demo organizations, factories, lines, machines and users."

    def handle(self, *args: Any, **options: Any) -> None:
        password = os.environ.get("DEMO_USER_PASSWORD", "")
        if not password:
            raise CommandError("Set DEMO_USER_PASSWORD in your .env file before running seed_demo.")

        with transaction.atomic():
            demo_org = self._create_site(
                DEMO_ORGANIZATION, DEMO_FACTORY, DEMO_LINE, DEMO_MACHINES, DEMO_SPEED_PER_HOUR
            )
            other_org = self._create_site(
                OTHER_ORGANIZATION, OTHER_FACTORY, OTHER_LINE, OTHER_MACHINES, OTHER_SPEED_PER_HOUR
            )
            self._create_planning(demo_org)
            self._create_quality(demo_org)
            ensure_default_rules(Factory.objects.get(organization=demo_org, name=DEMO_FACTORY[0]))

            emails = [
                self._create_member(f"{role.value}@{DEMO_EMAIL_DOMAIN}", password, demo_org, role)
                for role in Role
            ]
            emails.append(
                self._create_member(
                    f"{Role.FACTORY_MANAGER.value}@{OTHER_EMAIL_DOMAIN}",
                    password,
                    other_org,
                    Role.FACTORY_MANAGER,
                )
            )

        self.stdout.write(self.style.SUCCESS("Demo data is ready. Users (password from .env):"))
        for email in emails:
            self.stdout.write(f"  {email}")

    def _create_quality(self, organization: Organization) -> None:
        """Defect types Q01-Q06 and inspection stations where the simulator injects defects."""
        factory = Factory.objects.get(organization=organization, name=DEMO_FACTORY[0])
        line = ProductionLine.objects.get(factory=factory, name=DEMO_LINE)
        ensure_default_defect_types(Organization.objects.get(name=OTHER_ORGANIZATION))
        if ensure_demo_stations(line, ensure_default_defect_types(organization)):
            # Defects received before the stations existed get their station now.
            rebuild_quality(line)

    def _create_planning(self, organization: Organization) -> None:
        """Shifts, products and today's production order for Algiers Plant."""
        factory = Factory.objects.get(organization=organization, name=DEMO_FACTORY[0])
        line = ProductionLine.objects.get(factory=factory, name=DEMO_LINE)

        for name, start, end, (break_start, break_end) in DEMO_SHIFTS:
            shift, _ = Shift.objects.update_or_create(
                factory=factory,
                name=name,
                defaults={"start_time": start, "end_time": end, "days_of_week": all_days()},
            )
            ShiftBreak.objects.update_or_create(
                shift=shift,
                name="Break",
                defaults={"start_time": break_start, "end_time": break_end},
            )

        products = {}
        for sku, name, cycle_time in DEMO_PRODUCTS:
            products[sku], _ = Product.objects.update_or_create(
                organization=organization,
                sku=sku,
                defaults={"name": name, "ideal_cycle_time_seconds": cycle_time},
            )

        # Today's three shifts in factory time: today 06:00 until tomorrow 06:00.
        tz = ZoneInfo(factory.timezone)
        today = timezone.now().astimezone(tz).date()
        order_start = datetime.combine(today, time(6), tzinfo=tz)
        order_end = order_start + timedelta(days=1)
        if not overlapping_orders(line, order_start, order_end).exists():
            ProductionOrder.objects.create(
                line=line,
                product=products["W050"],
                planned_quantity=DEMO_ORDER_QUANTITY,
                scheduled_start=order_start,
                scheduled_end=order_end,
                status=OrderStatus.RUNNING,
            )

    def _create_site(
        self,
        organization_name: str,
        factory: tuple[str, str],
        line_name: str,
        machines: list[tuple[str, str, str]],
        speed_per_hour: int,
    ) -> Organization:
        organization, _ = Organization.objects.get_or_create(name=organization_name)
        factory_name, timezone = factory
        factory_obj, _ = Factory.objects.update_or_create(
            organization=organization, name=factory_name, defaults={"timezone": timezone}
        )
        ensure_default_reasons(factory_obj)
        line, _ = ProductionLine.objects.get_or_create(factory=factory_obj, name=line_name)
        for index, (external_id, name, machine_type) in enumerate(machines):
            Machine.objects.update_or_create(
                line=line,
                external_id=external_id,
                defaults={
                    "name": name,
                    "machine_type": machine_type,
                    "position": index + 1,
                    "nominal_speed_per_hour": speed_per_hour,
                },
            )
        return organization

    def _create_member(
        self, email: str, password: str, organization: Organization, role: Role
    ) -> str:
        user, _ = User.objects.get_or_create(
            email=email, defaults={"full_name": f"Demo {role.label}"}
        )
        user.set_password(password)
        user.save()
        Membership.objects.update_or_create(
            user=user,
            defaults={"organization": organization, "role": role, "all_factories": True},
        )
        return email
