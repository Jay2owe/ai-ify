"""Messages waiting to go: queued (after the current reply) or scheduled for a time.

Both are opt-in (``Agent(queue=True, schedule=True)``) and live only while the app
runs; a stopped app forgets them.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class Pending:
    id: str
    text: str
    at: float | None = None          # epoch seconds; None means "after the current reply"

    def to_dict(self) -> dict:
        when = datetime.fromtimestamp(self.at, timezone.utc).isoformat() if self.at is not None else None
        return {"id": self.id, "text": self.text, "at": when}


def when_to_epoch(at, now: float | None = None) -> float:
    """A send time: a datetime (naive means local time), a timedelta from now,
    epoch seconds, or an ISO 8601 string."""
    now = time.time() if now is None else now
    if isinstance(at, timedelta):
        return now + at.total_seconds()
    if isinstance(at, (int, float)):
        return float(at)
    if isinstance(at, str):
        text = at.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        at = datetime.fromisoformat(text)
    if isinstance(at, datetime):
        return at.timestamp()                    # a naive datetime is taken as local time
    raise ValueError(f"not a time: {at!r}")


class Outbox:
    """The queued and scheduled messages of one chat panel, in order."""

    def __init__(self):
        self.items: list[Pending] = []

    def add(self, text: str, at: float | None = None) -> Pending:
        item = Pending("m-" + uuid.uuid4().hex[:8], text, at)
        self.items.append(item)
        return item

    def remove(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        return len(self.items) != before

    def queued(self) -> list[Pending]:
        return [i for i in self.items if i.at is None]

    def next_time(self) -> float | None:
        times = [i.at for i in self.items if i.at is not None]
        return min(times) if times else None

    def take_next(self, now: float | None = None) -> Pending | None:
        """The message to send now: the earliest one due, else the first queued."""
        now = time.time() if now is None else now
        due = sorted((i for i in self.items if i.at is not None and i.at <= now), key=lambda i: i.at)
        pick = due[0] if due else next(iter(self.queued()), None)
        if pick is not None:
            self.remove(pick.id)
        return pick

    def clear_queued(self) -> list[Pending]:
        gone = self.queued()
        self.items = [i for i in self.items if i.at is not None]
        return gone

    def info(self) -> list[dict]:
        queued = [i.to_dict() for i in self.queued()]
        timed = sorted((i for i in self.items if i.at is not None), key=lambda i: i.at)
        return queued + [i.to_dict() for i in timed]
