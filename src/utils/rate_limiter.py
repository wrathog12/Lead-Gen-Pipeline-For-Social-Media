"""
Rate Limiter Utility
====================
Provides a token-bucket based rate limiter that can be shared across
multiple scraper threads to avoid hammering platform APIs.

Each platform (Reddit, Quora, X/Twitter, YouTube) has different
tolerance for request frequency — this module lets us configure
per-platform limits centrally and enforces them in a thread-safe way.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class _Bucket:
    """Internal token bucket representation."""
    capacity: int            # max tokens the bucket can hold
    refill_rate: float       # tokens added per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()


# ──────────────────────────────────────────────
# Default per-platform limits (requests / sec)
# These were tuned empirically after observing
# 429 responses during large batch runs.
# ──────────────────────────────────────────────
_DEFAULT_LIMITS: Dict[str, dict] = {
    "reddit":  {"capacity": 10, "refill_rate": 1.0},
    "quora":   {"capacity": 5,  "refill_rate": 0.5},
    "x":       {"capacity": 15, "refill_rate": 1.5},
    "youtube": {"capacity": 8,  "refill_rate": 0.8},
}


class RateLimiter:
    """
    Thread-safe, per-platform rate limiter using a token-bucket algorithm.

    Usage::

        limiter = RateLimiter()

        # Before each request:
        limiter.acquire("reddit")       # blocks until a token is available

        # Or with a timeout:
        if limiter.try_acquire("quora", timeout=2.0):
            ...
        else:
            logger.warning("Rate limit — backing off")
    """

    def __init__(self, overrides: Optional[Dict[str, dict]] = None):
        """
        Parameters
        ----------
        overrides : dict, optional
            Per-platform overrides for capacity / refill_rate.
            Example: ``{"reddit": {"capacity": 20, "refill_rate": 2.0}}``
        """
        self._buckets: Dict[str, _Bucket] = {}
        merged = {**_DEFAULT_LIMITS, **(overrides or {})}

        for platform, cfg in merged.items():
            self._buckets[platform.lower()] = _Bucket(
                capacity=cfg["capacity"],
                refill_rate=cfg["refill_rate"],
            )

    # ── public API ──────────────────────────────

    def acquire(self, platform: str) -> None:
        """Block until a token is available for *platform*."""
        bucket = self._get_bucket(platform)
        while True:
            with bucket.lock:
                self._refill(bucket)
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return
            # Couldn't get a token — sleep briefly and retry
            time.sleep(0.05)

    def try_acquire(self, platform: str, timeout: float = 1.0) -> bool:
        """
        Try to acquire a token within *timeout* seconds.
        Returns ``True`` if successful, ``False`` on timeout.
        """
        bucket = self._get_bucket(platform)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with bucket.lock:
                self._refill(bucket)
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return True
            time.sleep(0.05)
        return False

    def available(self, platform: str) -> int:
        """Return the current number of available tokens (approximate)."""
        bucket = self._get_bucket(platform)
        with bucket.lock:
            self._refill(bucket)
            return int(bucket.tokens)

    # ── internals ───────────────────────────────

    def _get_bucket(self, platform: str) -> _Bucket:
        key = platform.lower()
        if key not in self._buckets:
            raise ValueError(
                f"Unknown platform '{platform}'. "
                f"Known: {list(self._buckets.keys())}"
            )
        return self._buckets[key]

    @staticmethod
    def _refill(bucket: _Bucket) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        new_tokens = elapsed * bucket.refill_rate
        bucket.tokens = min(bucket.capacity, bucket.tokens + new_tokens)
        bucket.last_refill = now
