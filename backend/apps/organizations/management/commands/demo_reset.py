"""Tidy the Demo Beverages data before a demo. History is kept. Safe to run any number of times.

    docker compose exec backend python manage.py demo_reset

Runs seed_demo, resolves open alerts, marks the demo users' notifications read and deletes
assistant conversations. Raw events, stops, defects and maintenance actions are not touched.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.organizations import demo_video


class Command(BaseCommand):
    help = "Tidy the Demo Beverages data before a demo (keeps history)."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            counts = demo_video.reset()
        except RuntimeError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Demo reset: {alerts_resolved} alert(s) resolved, {notifications_read} "
                "notification(s) marked read, {conversations_deleted} assistant "
                "conversation row(s) deleted.".format(**counts)
            )
        )
