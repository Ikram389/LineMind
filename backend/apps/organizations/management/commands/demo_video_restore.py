"""Undo demo_video_prep's rule change: the "Long line stop" alert fires after 10 minutes again.

docker compose exec backend python manage.py demo_video_restore
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.organizations import demo_video

NORMAL_MINUTES = 10


class Command(BaseCommand):
    help = "Put the Demo Beverages long-stop alert back to 10 minutes after recording."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            demo_video.set_long_stop_minutes(NORMAL_MINUTES)
        except RuntimeError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(f"Long line stop alert: back to {NORMAL_MINUTES} minutes.")
        )
