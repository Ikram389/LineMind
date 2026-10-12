"""Create an API key that can send events for one production line.

    docker compose exec backend python manage.py create_line_api_key <line_id> "<name>"

The key is printed once and cannot be shown again (only its hash is stored).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.organizations.models import ProductionLine
from apps.production.services.api_keys import create_line_api_key


class Command(BaseCommand):
    help = "Create an API key for a production line and print it once."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("line_id", type=int, help="ID of the production line")
        parser.add_argument("name", help="What will use the key, e.g. 'Simulator'")

    def handle(self, *args: Any, **options: Any) -> None:
        line = (
            ProductionLine.objects.select_related("factory__organization")
            .filter(pk=options["line_id"])
            .first()
        )
        if line is None:
            raise CommandError(f"No production line with id {options['line_id']}.")

        api_key, raw_key = create_line_api_key(line, options["name"])

        self.stdout.write(
            f"Created API key '{api_key.name}' for line '{line.name}' "
            f"({line.factory.name}, {line.factory.organization.name})."
        )
        self.stdout.write(self.style.WARNING("Copy it now. It will not be shown again:"))
        self.stdout.write(raw_key)
