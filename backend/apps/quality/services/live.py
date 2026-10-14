"""The `quality_updated` live message: the current shift's defects for one line.

Sent after commit, when new defects were stored or a result was reviewed, at most
once per line every QUALITY_THROTTLE_SECONDS (extra ones are dropped, like count
messages). Because a dropped message can hide the very last change, the dashboard
also refreshes its quality card every minute.
"""

from collections.abc import Iterable
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.live.broadcast import after_commit, message, send_now
from apps.organizations.models import ProductionLine
from apps.production.services.counters import line_counts_between
from apps.production.services.shifts import current_shift
from apps.quality.services.metrics import QualityFilters, counted, rate, select_results

QUALITY_THROTTLE_SECONDS = 5


def shift_quality(line: ProductionLine) -> dict[str, Any]:
    """Defects, defect rate and unreviewed results of the line's current shift."""
    period = current_shift(line.factory, timezone.now())
    if period is None:
        return {"shift": None, "defects": 0, "defect_rate": None, "unreviewed": 0, "total_count": 0}
    filters = QualityFilters(start=period.start, end=period.end)
    results = select_results([line], filters)
    defects = counted(results).count()
    total = line_counts_between(line, period.start, period.end).total
    return {
        "shift": {"label": period.label, "start": period.start, "end": period.end},
        "defects": defects,
        "defect_rate": rate(defects, total),
        "unreviewed": results.filter(current_review__isnull=True).count(),
        "total_count": total,
    }


def publish_quality(line_id: int) -> None:
    if not cache.add(f"live:quality:{line_id}", 1, timeout=QUALITY_THROTTLE_SECONDS):
        return
    line = ProductionLine.objects.select_related("factory").filter(pk=line_id).first()
    if line is not None:
        send_now(line_id, message("quality_updated", line_id, shift_quality(line)))


def queue_quality_updates(line_ids: Iterable[int]) -> None:
    """After the current transaction commits, tell each line's dashboards (throttled)."""
    for line_id in set(line_ids):
        after_commit(lambda line_id=line_id: publish_quality(line_id))
