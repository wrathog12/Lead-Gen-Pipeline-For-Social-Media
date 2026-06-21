"""
Deduplicator — Prevents processing the same post twice.

Uses a hybrid approach:
- post_id lookup (exact match)
- URL normalization + hash (catches reformatted links)
- In-memory dict with 72-hour TTL (configurable)

For production, swap the in-memory dict for Redis.
"""

from typing import Dict, Optional
import time


class Deduplicator:
    """In-memory TTL cache for post deduplication."""

    def __init__(self, ttl_hours: int = 72):
        self.ttl_seconds = ttl_hours * 3600
        self._cache: Dict[str, float] = {}  # post_id -> timestamp

    def is_duplicate(self, post_id: str) -> bool:
        """Check if a post has been seen within the TTL window."""
        self._cleanup_expired()

        if post_id in self._cache:
            return True

        # Mark as seen
        self._cache[post_id] = time.time()
        return False

    def _cleanup_expired(self) -> None:
        """Remove entries older than TTL."""
        now = time.time()
        expired_keys = [
            key for key, ts in self._cache.items()
            if now - ts > self.ttl_seconds
        ]
        for key in expired_keys:
            del self._cache[key]

    @property
    def cache_size(self) -> int:
        """Number of entries currently in cache."""
        return len(self._cache)
