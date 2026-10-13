"""The one place where downtime durations are calculated (CLAUDE.md rule 3)."""

from datetime import datetime

from django.utils import timezone


def duration_seconds(
    started_at: datetime, ended_at: datetime | None, now: datetime | None = None
) -> float:
    """Length of an interval in seconds. An open interval (ended_at=None) runs until `now`."""
    end = ended_at if ended_at is not None else (now or timezone.now())
    return max(0.0, (end - started_at).total_seconds())


def exceeds_threshold(
    started_at: datetime, ended_at: datetime | None, threshold_seconds: int, now: datetime
) -> bool:
    """True when the interval lasts (or has lasted so far) longer than the threshold."""
    return duration_seconds(started_at, ended_at, now) > threshold_seconds
