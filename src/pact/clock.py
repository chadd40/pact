from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    def __init__(self, current: datetime) -> None:
        self._current = current

    def now(self) -> datetime:
        return self._current

    def set(self, dt: datetime) -> None:
        self._current = dt

    def advance(self, *, hours: float = 0, days: float = 0, minutes: float = 0) -> None:
        self._current = self._current + timedelta(hours=hours, days=days, minutes=minutes)
