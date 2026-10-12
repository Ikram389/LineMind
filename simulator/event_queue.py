"""A file-based queue of events waiting to be sent (SQLite, from the standard library).

Events are written here before any attempt to send them and removed only after
the backend has answered for them, so nothing is lost if the simulator or the
backend stops. Each event is stored as its exact JSON, so a retry sends the
same event_id.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from events import Event


class EventQueue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS queue ("
                " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                " event_id TEXT NOT NULL UNIQUE,"
                " body TEXT NOT NULL)"
            )

    def put(self, events: Iterable[Event]) -> None:
        rows = [(e.event_id, json.dumps(e.to_json())) for e in events]
        if not rows:
            return
        with self._conn:  # one transaction: all or nothing
            self._conn.executemany(
                "INSERT OR IGNORE INTO queue (event_id, body) VALUES (?, ?)", rows
            )

    def peek(self, limit: int) -> list[tuple[int, dict[str, object]]]:
        """The oldest `limit` events as (queue sequence, event JSON), without removing them."""
        cursor = self._conn.execute("SELECT seq, body FROM queue ORDER BY seq LIMIT ?", (limit,))
        return [(seq, json.loads(body)) for seq, body in cursor.fetchall()]

    def ack(self, sequences: Sequence[int]) -> None:
        """Remove events the backend has answered for."""
        if not sequences:
            return
        with self._conn:
            self._conn.executemany("DELETE FROM queue WHERE seq = ?", [(s,) for s in sequences])

    def __len__(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0])

    def close(self) -> None:
        self._conn.close()
