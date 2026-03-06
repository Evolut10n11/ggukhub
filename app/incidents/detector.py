from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable


class SpikeDetector:
    def __init__(self, window_minutes: int = 15, threshold: int = 5):
        self.window = timedelta(minutes=window_minutes)
        self.threshold = threshold

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def count_in_window(self, timestamps: Iterable[datetime], now: datetime | None = None) -> int:
        point = self._as_utc(now or datetime.now(timezone.utc))
        left = point - self.window
        return sum(1 for item in timestamps if left <= self._as_utc(item) <= point)

    def is_spike(self, timestamps: Iterable[datetime], now: datetime | None = None) -> bool:
        return self.count_in_window(timestamps, now=now) >= self.threshold
