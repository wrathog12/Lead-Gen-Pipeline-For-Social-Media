"""
X (Twitter) Ingester — Fetches tweets via X API v2 search.

Free tier is limited to 1,500 posts/month, so queries must be
surgical and narrow. Runs 1-2x daily with high-intent keywords.
"""

from typing import List, Dict, Any
from src.ingestion.base_ingester import BaseIngester


class XIngester(BaseIngester):
    """Fetches tweets from X/Twitter via API v2 recent search."""

    def __init__(self):
        super().__init__(platform_name="x")

    async def fetch_posts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        # TODO: Implement X API v2 recent search endpoint
        # Use narrow queries to conserve the 1,500/month budget
        raise NotImplementedError("X ingestion not yet implemented")

    def normalize_post(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Map X API v2 response to standard schema
        raise NotImplementedError
