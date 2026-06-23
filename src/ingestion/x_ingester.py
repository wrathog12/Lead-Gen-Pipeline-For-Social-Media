"""
X (Twitter) Ingester — Fetches tweets via X API v2 recent search.

Pay-per-use model: $0.005 per tweet read.
Design: fetch once, persist to DB, never re-fetch the same tweets.

This ingester bypasses Tier-1 regex filter — tweets go directly
to Tier-2 LLM validation (with lenient scoring for X).

Requires: X_BEARER_TOKEN in .env
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from src.ingestion.base_ingester import BaseIngester
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("x_ingester")

# ── X API v2 endpoints ───────────────────────────────────────────
X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

# ── Single consolidated search query ─────────────────────────────
# One query to minimize paid reads. Covers key Indian finance topics.
# Two-group structure: (financial terms) AND (India geo terms)
# ensures every result is India-relevant.
# -is:retweet avoids duplicates, lang:en focuses on English tweets.
DEFAULT_QUERY = (
    '("mutual fund" OR SIP OR "home loan" OR "personal loan" '
    'OR "credit card" OR "fixed deposit" OR "tax saving" '
    'OR NPS OR ELSS OR PPF OR "health insurance" OR "term insurance" '
    'OR "savings account" OR "demat account" OR ITR) '
    '(India OR Indian OR lakh OR crore OR rupee OR ICICI OR HDFC '
    'OR Zerodha OR Groww OR Nifty OR Sensex) '
    'lang:en -is:retweet'
)

# ── Fetch limit ──────────────────────────────────────────────────
DEFAULT_MAX_RESULTS = 100  # Costs 100 × $0.005 = $0.50 per run


class XIngester(BaseIngester):
    """
    Fetches tweets from X/Twitter via API v2 recent search.

    Flow:
    1. Single consolidated query to fetch 30 tweets
    2. Normalize to standard schema
    3. Persist to DB (handled by caller) — never re-fetch
    """

    def __init__(
        self,
        bearer_token: Optional[str] = None,
        query: Optional[str] = None,
        max_age_days: int = 7,
    ):
        super().__init__(platform_name="x")

        self.bearer_token = bearer_token or settings.x_bearer_token
        if not self.bearer_token or self.bearer_token == "your_x_bearer_token":
            raise ValueError(
                "X_BEARER_TOKEN not configured. "
                "Set it in .env or pass bearer_token= to the constructor."
            )

        self.query = query or DEFAULT_QUERY
        self.max_age_days = max_age_days
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    # ── Core: Search recent tweets ───────────────────────────────

    def _search_tweets(
        self,
        query: Optional[str] = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """
        Search for recent tweets using X API v2.

        Cost: $0.005 per tweet returned.

        Returns raw tweet data with author info expanded.
        """
        search_query = query or self.query

        # 7-day window
        start_time = self._cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "query": search_query,
            "max_results": min(max(max_results, 10), 100),  # API: 10-100
            "start_time": start_time,
            "tweet.fields": "created_at,public_metrics,author_id,lang",
            "expansions": "author_id",
            "user.fields": "username,name",
        }

        response = requests.get(
            X_SEARCH_URL,
            headers=self._get_headers(),
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        # Build author lookup from includes
        authors = {}
        for user in data.get("includes", {}).get("users", []):
            authors[user["id"]] = {
                "username": user.get("username", "unknown"),
                "name": user.get("name", "Unknown"),
            }

        # Parse tweets
        tweets = []
        for tweet in data.get("data", []):
            author_id = tweet.get("author_id", "")
            author_info = authors.get(author_id, {"username": "unknown", "name": "Unknown"})

            tweets.append({
                "tweet_id": tweet["id"],
                "text": tweet.get("text", ""),
                "author_username": author_info["username"],
                "author_name": author_info["name"],
                "created_at": tweet.get("created_at", ""),
                "like_count": tweet.get("public_metrics", {}).get("like_count", 0),
                "retweet_count": tweet.get("public_metrics", {}).get("retweet_count", 0),
                "reply_count": tweet.get("public_metrics", {}).get("reply_count", 0),
            })

        logger.info(
            "tweet_search_complete",
            query=search_query[:60],
            tweets_found=len(tweets),
        )

        return tweets

    # ── Normalize to standard schema ─────────────────────────────

    def normalize_post(self, tweet: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an X API tweet dict into our standard IngestedPost schema."""

        timestamp = tweet.get("created_at", "")
        if timestamp:
            timestamp = timestamp.replace("Z", "+00:00")
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        tweet_id = tweet["tweet_id"]
        username = tweet.get("author_username", "unknown")

        return {
            "platform": "x",
            "post_id": tweet_id,
            "author": f"@{username}",
            "source": "X (Twitter)",
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "timestamp": timestamp,
            "title": f"Tweet by @{username}",
            "text": tweet.get("text", ""),
            "score": tweet.get("like_count", 0),
            "retweet_count": tweet.get("retweet_count", 0),
            "reply_count": tweet.get("reply_count", 0),
        }

    # ── Main fetch (async interface) ─────────────────────────────

    async def fetch_posts(
        self,
        query: Optional[str] = None,
        limit: int = DEFAULT_MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """Async wrapper — delegates to sync since we use requests."""
        return self.fetch_posts_sync(query=query, limit=limit)

    # ── Main fetch (sync) ────────────────────────────────────────

    def fetch_posts_sync(
        self,
        query: Optional[str] = None,
        limit: int = DEFAULT_MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """
        Fetch and normalize tweets in one call.

        This is the main entry point. Fetches tweets, normalizes them,
        and returns the list. Caller is responsible for persisting to DB.
        """
        try:
            raw_tweets = self._search_tweets(query=query, max_results=limit)
        except requests.exceptions.HTTPError as e:
            logger.error("x_search_failed", error=str(e), status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("x_search_failed", error=str(e))
            raise

        results = [self.normalize_post(t) for t in raw_tweets]

        logger.info(
            "ingestion_complete",
            platform="x",
            total_tweets=len(results),
        )

        return results
