from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils.dateparse import parse_datetime

from apps.organizations.models import ProductionLine
from apps.quality.services.processing import rebuild_quality


class Command(BaseCommand):
    help = (
        "Re-derive inspection results from the raw quality_defect_detected events "
        "(idempotent; reviews stay attached; raw events are never changed)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--line", type=int, required=True, help="Production line id.")
        parser.add_argument("--start", help="ISO date-time with timezone (inclusive).")
        parser.add_argument("--end", help="ISO date-time with timezone (exclusive).")

    def handle(self, *args: Any, **options: Any) -> None:
        line = ProductionLine.objects.filter(pk=options["line"]).first()
        if line is None:
            raise CommandError(f"Line {options['line']} does not exist.")
        bounds = []
        for name in ("start", "end"):
            raw = options[name]
            value = parse_datetime(raw) if raw else None
            if raw and (value is None or value.tzinfo is None):
                raise CommandError(f"--{name} must be an ISO date-time with a timezone.")
            bounds.append(value)
        changed = rebuild_quality(line, bounds[0], bounds[1])
        self.stdout.write(self.style.SUCCESS(f"{changed} inspection result(s) created or updated."))
