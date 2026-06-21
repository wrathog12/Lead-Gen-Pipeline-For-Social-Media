"""
YouTube Poster — Posts comments via YouTube Data API v3.

Human-triggered from the dashboard. Uses commentThreads.insert
(costs 50 quota units per comment, ~200 comments/day max on free tier).
"""

from typing import Dict, Any
from src.execution.base_poster import BasePoster


class YouTubePoster(BasePoster):
    """Posts comments to YouTube videos via Data API v3."""

    def __init__(self):
        super().__init__(platform_name="youtube", requests_per_minute=10)
        # TODO: Initialize YouTube API client

    async def post_comment(self, post_url: str, comment_text: str) -> Dict[str, Any]:
        # TODO: Implement using commentThreads.insert
        raise NotImplementedError("YouTube posting not yet implemented")
