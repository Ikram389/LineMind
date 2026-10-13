"""Time windows used by the derivation and incident grouping."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q


@dataclass(frozen=True)
class Window:
    """A closed time window; None means unbounded on that side."""

    start: datetime | None
    end: datetime | None

    def overlaps(self, started_at: datetime, ended_at: datetime | None) -> bool:
        if self.end is not None and started_at > self.end:
            return False
        return not (self.start is not None and ended_at is not None and ended_at < self.start)

    def overlap_q(self, start_field: str = "started_at", end_field: str = "ended_at") -> Q:
        """ORM filter: rows whose [start_field, end_field] interval touches the window."""
        q = Q()
        if self.end is not None:
            q &= Q(**{f"{start_field}__lte": self.end})
        if self.start is not None:
            q &= Q(**{f"{end_field}__isnull": True}) | Q(**{f"{end_field}__gte": self.start})
        return q

    def widen(self, started_at: datetime, ended_at: datetime | None) -> "Window":
        start = None if self.start is None else min(self.start, started_at)
        end = None if self.end is None or ended_at is None else max(self.end, ended_at)
        return Window(start, end)


def union(windows: Sequence[Window]) -> Window:
    starts = [w.start for w in windows]
    ends = [w.end for w in windows]
    start = None if None in starts else min(s for s in starts if s is not None)
    end = None if None in ends else max(e for e in ends if e is not None)
    return Window(start, end)
