"""
Base Poster — Abstract base class for all execution spokes.

Provides built-in rate limiting logic. Each platform poster inherits
this and configures its own rate limit (requests per minute).
Posts are executed one-by-one, human-triggered from the dashboard.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import time


class BasePoster(ABC):
    """Abstract base class for throttled platform posters."""

    def __init__(self, platform_name: str, requests_per_minute: int = 1):
        self.platform_name = platform_name
        self.rpm_limit = requests_per_minute
        self._last_post_time: float = 0

    def _wait_for_rate_limit(self) -> None:
        """Block until the rate limit window allows the next request."""
        min_interval = 60.0 / self.rpm_limit
        elapsed = time.time() - self._last_post_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_post_time = time.time()

    @abstractmethod
    async def post_comment(self, post_url: str, comment_text: str) -> Dict[str, Any]:
        """
        Post a comment to the platform.

        Returns:
            {
                "success": bool,
                "platform": str,
                "post_url": str,
                "comment_url": str (if successful),
                "error": str (if failed)
            }
        """
        pass
