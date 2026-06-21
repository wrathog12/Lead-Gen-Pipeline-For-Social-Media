"""
X Poster — Posts replies via X API v2.

Human-triggered from the dashboard. Free tier is severely
limited (1,500 posts/month read, posting limits apply).
"""

from typing import Dict, Any
from src.execution.base_poster import BasePoster


class XPoster(BasePoster):
    """Posts replies to X/Twitter via API v2."""

    def __init__(self):
        super().__init__(platform_name="x", requests_per_minute=5)
        # TODO: Initialize X API v2 client

    async def post_comment(self, post_url: str, comment_text: str) -> Dict[str, Any]:
        # TODO: Implement using X API v2 tweet creation endpoint
        raise NotImplementedError("X posting not yet implemented")
