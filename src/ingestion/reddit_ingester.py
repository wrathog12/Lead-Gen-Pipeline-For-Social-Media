"""
Reddit Ingester — Fetches posts from Reddit using the .json endpoint.

No API keys required for reading. Normalizes Reddit post data
into the standard ingestion schema for the Central Hub.
"""

from typing import List, Dict, Any
from src.ingestion.base_ingester import BaseIngester


class RedditIngester(BaseIngester):
    """Fetches posts from Reddit subreddits via the public .json endpoint."""

    def __init__(self):
        super().__init__(platform_name="reddit")

    async def fetch_posts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        # TODO: Implement .json endpoint fetching
        # GET https://www.reddit.com/r/{subreddit}/search.json?q={query}&limit={limit}
        raise NotImplementedError("Reddit ingestion not yet implemented")

    def normalize_post(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Map Reddit JSON fields to standard schema
        raise NotImplementedError
