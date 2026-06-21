"""
YouTube Ingester — Fetches video comments via YouTube Data API v3.

Uses search endpoint to find relevant videos, then fetches
comment threads for analysis by the Central Hub pipeline.
"""

from typing import List, Dict, Any
from src.ingestion.base_ingester import BaseIngester


class YouTubeIngester(BaseIngester):
    """Fetches comments from YouTube videos via Data API v3."""

    def __init__(self):
        super().__init__(platform_name="youtube")

    async def fetch_posts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        # TODO: Implement YouTube Data API v3 search + commentThreads.list
        raise NotImplementedError("YouTube ingestion not yet implemented")

    def normalize_post(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Map YouTube API response to standard schema
        raise NotImplementedError
