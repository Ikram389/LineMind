"""Create demo data for development. Safe to run any number of times.

    docker compose exec backend python manage.py seed_demo

Every demo user gets the password from the DEMO_USER_PASSWORD environment variable.
"""

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.downtime.default_reasons import ensure_default_reasons
from apps.organizations.models import (
    Factory,
    Machine,
    Membership,
    Organization,
    ProductionLine,
    Role,
)

DEMO_ORGANIZATION = "Demo Beverages"
DEMO_FACTORY = ("Algiers Plant", "Africa/Algiers")
DEMO_LINE = "Bottling Line 1"
DEMO_EMAIL_DOMAIN = "demo-beverages.test"

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
