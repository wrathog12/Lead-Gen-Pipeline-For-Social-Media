"""
Tests for the token-bucket rate limiter.

Verifies core acquire/try_acquire semantics, refill behaviour,
and thread-safety under concurrent access.
"""

import time
import threading
import pytest

from src.utils.rate_limiter import RateLimiter


# ────────────────────────────────────────
#  Basic functionality
# ────────────────────────────────────────

class TestRateLimiterBasics:
    """Sanity-check the public API with default platform configs."""

    def test_acquire_does_not_block_when_tokens_available(self):
        """First N acquires (up to bucket capacity) should return instantly."""
        limiter = RateLimiter()
        start = time.monotonic()
        # Reddit default capacity is 10 — grab them all
        for _ in range(10):
            limiter.acquire("reddit")
        elapsed = time.monotonic() - start
        # All 10 should drain in well under a second
        assert elapsed < 0.5, f"Took {elapsed:.2f}s — should be near-instant"

    def test_try_acquire_returns_false_on_timeout(self):
        """Once the bucket is drained, try_acquire should time out."""
        limiter = RateLimiter(overrides={
            "reddit": {"capacity": 2, "refill_rate": 0.1}
        })
        # Drain the bucket
        assert limiter.try_acquire("reddit", timeout=0.1)
        assert limiter.try_acquire("reddit", timeout=0.1)
        # Third attempt should fail within the timeout window
        assert not limiter.try_acquire("reddit", timeout=0.2)

    def test_available_returns_correct_count(self):
        """available() should reflect how many tokens are left."""
        limiter = RateLimiter(overrides={
            "quora": {"capacity": 5, "refill_rate": 0.0}  # no refill
        })
        assert limiter.available("quora") == 5
        limiter.acquire("quora")
        assert limiter.available("quora") == 4

    def test_unknown_platform_raises(self):
        """Requesting a token for an unregistered platform should error."""
        limiter = RateLimiter()
        with pytest.raises(ValueError, match="Unknown platform"):
            limiter.acquire("tiktok")


# ────────────────────────────────────────
#  Refill behaviour
# ────────────────────────────────────────

class TestRefillBehaviour:
    """Make sure tokens replenish at the configured rate."""

    def test_tokens_refill_over_time(self):
        """After draining, waiting should yield new tokens."""
        limiter = RateLimiter(overrides={
            "x": {"capacity": 2, "refill_rate": 10.0}  # 10 tok/s → fast
        })
        limiter.acquire("x")
        limiter.acquire("x")
        assert limiter.available("x") == 0
        # Wait long enough for at least 1 token to refill
        time.sleep(0.15)
        assert limiter.available("x") >= 1


# ────────────────────────────────────────
#  Thread-safety smoke test
# ────────────────────────────────────────

class TestConcurrentAccess:
    """Run multiple threads against the same limiter to check for races."""

    def test_concurrent_acquires_do_not_exceed_capacity(self):
        """
        Spawn N threads that each try to acquire a token.
        Total successful acquires should never exceed bucket capacity
        (since refill_rate is 0 here).
        """
        capacity = 8
        limiter = RateLimiter(overrides={
            "youtube": {"capacity": capacity, "refill_rate": 0.0}
        })
        successes = []
        lock = threading.Lock()

        def _worker():
            ok = limiter.try_acquire("youtube", timeout=0.2)
            with lock:
                successes.append(ok)

        threads = [threading.Thread(target=_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(1 for s in successes if s)
        assert granted == capacity, (
            f"Expected exactly {capacity} grants, got {granted}"
        )
