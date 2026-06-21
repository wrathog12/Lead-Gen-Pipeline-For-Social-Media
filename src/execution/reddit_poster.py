"""
Reddit Poster — Posts comments via Reddit OAuth2 API.

Human-triggered from the dashboard. Uses PRAW for OAuth2
authentication and comment posting. Rate limited to 1 req/sec.
PoC uses a sandbox subreddit (r/test or custom PoC sub).
"""

from typing import Dict, Any
from src.execution.base_poster import BasePoster


class RedditPoster(BasePoster):
    """Posts comments to Reddit via OAuth2 API (PRAW)."""

    def __init__(self):
        super().__init__(platform_name="reddit", requests_per_minute=60)
        # TODO: Initialize PRAW Reddit instance with OAuth2 credentials

    async def post_comment(self, post_url: str, comment_text: str) -> Dict[str, Any]:
        # TODO: Implement using PRAW submission.reply()
        raise NotImplementedError("Reddit posting not yet implemented")
