"""
Reddit Ingester — Fetches posts from Reddit using PRAW (OAuth2).

Searches target subreddits using financial keywords, filters to
posts from the last 7 days, and normalizes them into the standard
ingestion schema for the Central Hub pipeline.

Requires: client_id, client_secret, username, password, user_agent
from .env file.
"""

import praw
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from src.ingestion.base_ingester import BaseIngester
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("reddit_ingester")

# ── Default subreddits to monitor ────────────────────────────────
# Indian finance / investment communities with high lead potential
DEFAULT_SUBREDDITS = [
    "IndiaInvestments",
    "personalfinanceindia",
    "CreditCardsIndia",
    "indiapersonalfinance",
]

# ── Financial search queries ─────────────────────────────────────
# Broad enough to catch leads, narrow enough to avoid pure noise
DEFAULT_SEARCH_QUERIES = [
    "mutual fund",
    "SIP invest",
    "home loan",
    "personal loan",
    "credit card best",
    "fixed deposit",
    "tax saving investment",
    "where to invest",
    "best fund 2026",
    "NPS vs ELSS",
    "health insurance",
    "term insurance",
]


class RedditIngester(BaseIngester):
    """
    Fetches posts from Reddit subreddits via PRAW (OAuth2 authenticated).

    Flow:
    1. Authenticate using script-type OAuth2 credentials
    2. For each target subreddit, search using financial queries
    3. Filter to posts from the last 7 days
    4. Normalize each post into the standard IngestedPost schema
    5. Return deduplicated list of posts
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        user_agent: Optional[str] = None,
        subreddits: Optional[List[str]] = None,
        search_queries: Optional[List[str]] = None,
        max_age_days: int = 7,
    ):
        super().__init__(platform_name="reddit")

        # Use provided values or fall back to .env config
        self.reddit = praw.Reddit(
            client_id=client_id or settings.reddit_client_id,
            client_secret=client_secret or settings.reddit_client_secret,
            username=username or settings.reddit_username,
            password=password or settings.reddit_password,
            user_agent=user_agent or settings.reddit_user_agent,
        )

        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.search_queries = search_queries or DEFAULT_SEARCH_QUERIES
        self.max_age_days = max_age_days

        # Cutoff timestamp: only posts newer than this
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

    def _is_within_time_window(self, created_utc: float) -> bool:
        """Check if a post's creation time is within our 7-day window."""
        post_time = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        return post_time >= self._cutoff

    def normalize_post(self, submission) -> Dict[str, Any]:
        """
        Convert a PRAW Submission object into our standard schema.

        Combines title + selftext into the 'text' field since both
        carry intent signals for the filtering pipeline.
        """
        # Combine title and body — both are useful for intent detection
        full_text = submission.title
        if submission.selftext and submission.selftext.strip():
            full_text += "\n\n" + submission.selftext

        post_time = datetime.fromtimestamp(
            submission.created_utc, tz=timezone.utc
        )

        return {
            "platform": "reddit",
            "post_id": submission.id,
            "author": str(submission.author) if submission.author else "[deleted]",
            "source": str(submission.subreddit),
            "url": f"https://www.reddit.com{submission.permalink}",
            "timestamp": post_time.isoformat(),
            "title": submission.title,
            "text": full_text,
            "score": submission.score,               # upvotes (useful for prioritization)
            "num_comments": submission.num_comments,  # engagement signal
        }

    async def fetch_posts(
        self,
        query: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Fetch posts from Reddit matching financial queries.

        If 'query' is provided, searches only that query across all subreddits.
        Otherwise, iterates through all DEFAULT_SEARCH_QUERIES.

        Args:
            query: Optional single search query. If None, uses all default queries.
            limit: Max posts to fetch per query per subreddit.

        Returns:
            List of normalized post dicts, deduplicated by post_id.
        """
        queries = [query] if query else self.search_queries
        seen_ids = set()
        results = []

        for subreddit_name in self.subreddits:
            subreddit = self.reddit.subreddit(subreddit_name)

            for q in queries:
                try:
                    # Search within the subreddit
                    # time_filter="week" restricts to last 7 days on Reddit's side
                    search_results = subreddit.search(
                        query=q,
                        sort="new",
                        time_filter="week",
                        limit=limit,
                    )

                    for submission in search_results:
                        # Skip if already collected (dedup within this run)
                        if submission.id in seen_ids:
                            continue

                        # Double-check the 7-day window (belt and suspenders)
                        if not self._is_within_time_window(submission.created_utc):
                            continue

                        # Skip removed / deleted posts
                        if submission.removed_by_category or submission.selftext == "[removed]":
                            continue

                        seen_ids.add(submission.id)
                        normalized = self.normalize_post(submission)
                        results.append(normalized)

                        logger.info(
                            "post_fetched",
                            subreddit=subreddit_name,
                            query=q,
                            post_id=submission.id,
                            title=submission.title[:80],
                        )

                except Exception as e:
                    logger.error(
                        "search_failed",
                        subreddit=subreddit_name,
                        query=q,
                        error=str(e),
                    )
                    continue

        logger.info(
            "ingestion_complete",
            platform="reddit",
            total_posts=len(results),
            subreddits_searched=len(self.subreddits),
            queries_used=len(queries),
        )

        return results

    def fetch_posts_sync(
        self,
        query: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Synchronous version of fetch_posts for easy testing.

        PRAW itself is synchronous under the hood, so this avoids
        the need for asyncio when running quick tests.
        """
        queries = [query] if query else self.search_queries
        seen_ids = set()
        results = []

        for subreddit_name in self.subreddits:
            subreddit = self.reddit.subreddit(subreddit_name)

            for q in queries:
                try:
                    search_results = subreddit.search(
                        query=q,
                        sort="new",
                        time_filter="week",
                        limit=limit,
                    )

                    for submission in search_results:
                        if submission.id in seen_ids:
                            continue
                        if not self._is_within_time_window(submission.created_utc):
                            continue
                        if submission.removed_by_category or submission.selftext == "[removed]":
                            continue

                        seen_ids.add(submission.id)
                        normalized = self.normalize_post(submission)
                        results.append(normalized)

                except Exception as e:
                    print(f"[ERROR] Subreddit={subreddit_name}, Query={q}: {e}")
                    continue

        return results
