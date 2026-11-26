import asyncio
import time
from collections import defaultdict
from app.config import settings
from app.utils.logger import logger


class InMemoryRateLimiter:
    """In-memory sliding window rate limiter per client key."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self.request_timestamps: dict[str, list[float]] = defaultdict(list)
        self.lock = asyncio.Lock()
        self._last_cleanup = time.time()

    async def is_allowed(self, client_key: str) -> tuple[bool, int]:
        """
        Check if the request is permitted within the sliding window.
        Returns:
            (is_allowed: bool, retry_after_seconds: int)
        """
        if not settings.rate_limit_enabled or self.requests_per_minute <= 0:
            return True, 0

        current_time = time.time()
        window_start = current_time - self.window_seconds

        async with self.lock:
            # Periodically remove stale entries across all keys
            if current_time - self._last_cleanup > 300:
                self._cleanup_stale_keys(window_start)
                self._last_cleanup = current_time

            # Filter timestamps outside the sliding 60s window
            timestamps = [
                ts for ts in self.request_timestamps.get(client_key, [])
                if ts > window_start
            ]

            if len(timestamps) >= self.requests_per_minute:
                # Oldest timestamp in window determines when the client can retry
                oldest_in_window = timestamps[0]
                retry_after = max(1, int(oldest_in_window + self.window_seconds - current_time) + 1)
                logger.warning(
                    "Rate limit exceeded",
                    client_key=client_key,
                    requests_in_window=len(timestamps),
                    limit=self.requests_per_minute,
                    retry_after=retry_after,
                )
                self.request_timestamps[client_key] = timestamps
                return False, retry_after

            timestamps.append(current_time)
            self.request_timestamps[client_key] = timestamps
            return True, 0

    def _cleanup_stale_keys(self, window_start: float) -> None:
        """Prune client entries that have no requests in the active window."""
        stale_keys = [
            k for k, ts_list in self.request_timestamps.items()
            if not ts_list or ts_list[-1] <= window_start
        ]
        for key in stale_keys:
            self.request_timestamps.pop(key, None)


rate_limiter = InMemoryRateLimiter(requests_per_minute=settings.rate_limit_rpm)

