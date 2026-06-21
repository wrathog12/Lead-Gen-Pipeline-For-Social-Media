"""
Base Ingester — Abstract base class for all platform ingesters.

All ingestion spokes inherit from this class to ensure a consistent
interface: fetch posts, normalize to standard schema, return list of dicts.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseIngester(ABC):
    """Abstract base class for platform-specific ingesters."""

    def __init__(self, platform_name: str):
        self.platform_name = platform_name

    @abstractmethod
    async def fetch_posts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch raw posts from the platform matching the query.

        Returns a list of normalized post dicts following the standard schema:
        {
            "platform": str,
            "post_id": str,
            "author": str,
            "source": str,        # subreddit, channel, etc.
            "url": str,
            "timestamp": str,     # ISO 8601
            "title": str,
            "text": str           # Full body/content
        }
        """
        pass

    def normalize_post(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Override this to map platform-specific fields to standard schema."""
        raise NotImplementedError
