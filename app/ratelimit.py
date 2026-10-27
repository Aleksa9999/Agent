"""A small sliding-window limiter kept in memory. It guards paid calls until real budgets
(spending limits per person) arrive; with several workers each one counts for itself."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[object, deque[float]] = defaultdict(deque)

    def allow(self, key: object, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and moment - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(moment)
        return True
