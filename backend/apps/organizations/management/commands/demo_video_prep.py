"""Get the Demo Beverages data ready for recording the demo video.

    docker compose exec backend python manage.py demo_video_prep

1. demo_reset (seed_demo, open alerts resolved, notifications read, conversations deleted).
2. The "Long line stop" alert rule fires after 1 minute instead of 10.
3. Makes sure the verified "Labeler · E-204" maintenance action exists with an "improved"
   before/after result (built on the first run, see demo_video.ensure_effectiveness_action)
   and prints its URL. The Maintenance list shows open actions by default, so open the URL.
4. Reports the unreviewed defects (demo_jam adds a few more while recording).

Afterwards: demo_video_restore puts the rule back to 10 minutes.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.organizations import demo_video

DEMO_MINUTES = 1


class Command(BaseCommand):
    help = "Prepare the Demo Beverages data for recording the demo video."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            counts = demo_video.reset()
            demo_video.set_long_stop_minutes(DEMO_MINUTES)
        except RuntimeError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            "Demo reset: {alerts_resolved} alert(s) resolved, {notifications_read} "
            "notification(s) marked read, {conversations_deleted} assistant "
            "conversation row(s) deleted.".format(**counts)
        )
        self.stdout.write(f"Long line stop alert: now after {DEMO_MINUTES} minute.")

        try:
            action, result = demo_video.ensure_effectiveness_action()
        except RuntimeError as error:
            raise CommandError(str(error)) from error
        if result["status"] != "improved":
            raise CommandError(
                f'Maintenance action #{action.pk}: the before/after result is "{result["status"]}"'
                f' ({result.get("reason", "")}), not "improved".'
            )
        before, after = result["before"], result["after"]
        self.stdout.write(
            f'Maintenance action #{action.pk} "{action.title}" ({action.status}): improved. '
            f"Jams per 10 run hours {before['occurrences_per_10h']} -> "
            f"{after['occurrences_per_10h']}, downtime per 10 run hours "
            f"{before['downtime_minutes_per_10h']} -> {after['downtime_minutes_per_10h']} min."
        )
        self.stdout.write(f"Open it before recording: {demo_video.action_url(action)}")
        self.stdout.write(f"Unreviewed defects: {demo_video.unreviewed_defects()}.")
        self.stdout.write(
            self.style.SUCCESS("Ready. After recording, run: python manage.py demo_video_restore")
        )
