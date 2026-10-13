"""Recompute downtime events and incidents for a line from the raw observations.

    docker compose exec backend python manage.py rebuild_downtime --line 1
    docker compose exec backend python manage.py rebuild_downtime --line 1 \
        --start 2026-10-05T06:00:00Z --end 2026-10-05T07:00:00Z

Safe to run any number of times: rows keep their identity and classifications.
Run it after changing a factory's minimum stop or stale threshold.
"""

from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.downtime.services.derivation import rebuild_line
from apps.organizations.models import ProductionLine


def aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CommandError(f"'{value}' is not an ISO date-time.") from None
    if parsed.tzinfo is None:
        raise CommandError(f"'{value}' must include a timezone, e.g. 'Z'.")
    return parsed


class Command(BaseCommand):
    help = "Rebuild downtime events and line stop incidents for a production line."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--line", type=int, required=True, help="Production line id")
        parser.add_argument(
            "--start", type=aware_datetime, help="Window start (ISO, with timezone)"
        )
        parser.add_argument("--end", type=aware_datetime, help="Window end (ISO, with timezone)")

    def handle(self, *args: Any, **options: Any) -> None:
        line = ProductionLine.objects.select_related("factory").filter(pk=options["line"]).first()
        if line is None:
            raise CommandError(f"No production line with id {options['line']}.")
        start, end = options["start"], options["end"]
        if start and end and start > end:
            raise CommandError("--start must be before --end.")

        rebuild_line(line, start, end)

        events = DowntimeEvent.objects.filter(line=line, is_obsolete=False).count()
        incidents = LineStopIncident.objects.filter(line=line).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt line '{line.name}': {events} downtime event(s), {incidents} incident(s)."
            )
        )
