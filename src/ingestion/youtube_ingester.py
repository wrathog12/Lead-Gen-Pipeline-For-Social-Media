"""
YouTube Ingester — Fetches video comments via YouTube Data API v3.

Strategy (quota-optimized):
  1. Search for recent finance videos using consolidated keyword groups
     (each search.list call = 100 units; we aim for 2-3 calls max)
  2. Fetch comment threads from discovered videos
     (each commentThreads.list call = 1 unit; very cheap)
  3. Filter comments to 7-day window, normalize to standard schema

Typical quota per run: ~200-300 units out of 10,000 daily limit.

Requires: YOUTUBE_API_KEY in .env
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from src.ingestion.base_ingester import BaseIngester
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("youtube_ingester")

# ── YouTube API base URLs ────────────────────────────────────────
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

# ── Consolidated search queries ──────────────────────────────────
# Grouped using | (OR) to minimize the number of search.list calls
# Each group costs 100 quota units, so we keep it to 2-3 groups
DEFAULT_SEARCH_GROUPS = [
    "mutual fund India | SIP invest | best fund 2026",
    "home loan India | personal loan tips | credit card best India",
    "tax saving investment | NPS vs ELSS | fixed deposit rate",
]

# ── Limit constants ──────────────────────────────────────────────
MAX_VIDEOS_PER_SEARCH = 10       # Videos per search query (default)
MAX_COMMENTS_PER_VIDEO = 30      # Top-level comments to fetch per video
RATE_LIMIT_DELAY_SEC = 0.5       # Small delay between API calls


class YouTubeIngester(BaseIngester):
    """
    Fetches comments from YouTube videos via Data API v3.

    Flow:
    1. Search for recent Indian finance videos (consolidated queries)
    2. Fetch top-level comment threads from each video
    3. Filter comments to 7-day window
    4. Normalize with video context into standard schema
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        search_groups: Optional[List[str]] = None,
        max_age_days: int = 7,
    ):
        super().__init__(platform_name="youtube")

        self.api_key = api_key or settings.youtube_api_key
        if not self.api_key or self.api_key == "your_youtube_api_key_here":
            raise ValueError(
                "YOUTUBE_API_KEY not configured. "
                "Set it in .env or pass api_key= to the constructor."
            )

        self.search_groups = search_groups or DEFAULT_SEARCH_GROUPS
        self.max_age_days = max_age_days

        # Cutoff: only content newer than this
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

    # ── Step 1: Discover Videos ──────────────────────────────────

    def _search_videos(
        self,
        query: str,
        max_results: int = MAX_VIDEOS_PER_SEARCH,
    ) -> List[Dict[str, Any]]:
        """
        Search YouTube for recent videos matching a query.

        Costs: 100 quota units per call.

        Returns list of dicts with keys:
          video_id, title, description, channel_title, published_at
        """
        # publishedAfter requires RFC 3339 format
        published_after = self._cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "key": self.api_key,
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "relevance",
            "publishedAfter": published_after,
            "relevanceLanguage": "en",
            "maxResults": min(max_results, 50),  # API max is 50
        }

        response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")

            if not video_id:
                continue

            videos.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
            })

        logger.info(
            "video_search_complete",
            query=query[:60],
            videos_found=len(videos),
        )

        return videos

    # ── Step 2: Fetch Comments ───────────────────────────────────

    def _fetch_comments(
        self,
        video_id: str,
        max_results: int = MAX_COMMENTS_PER_VIDEO,
    ) -> List[Dict[str, Any]]:
        """
        Fetch top-level comment threads for a video.

        Costs: 1 quota unit per call (very cheap).

        Returns list of dicts with keys:
          comment_id, author, text, like_count, published_at
        """
        params = {
            "key": self.api_key,
            "videoId": video_id,
            "part": "snippet",
            "textFormat": "plainText",
            "order": "relevance",
            "maxResults": min(max_results, 100),  # API max is 100
        }

        try:
            response = requests.get(YOUTUBE_COMMENTS_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            # Comments might be disabled on the video
            if response.status_code == 403:
                logger.warning(
                    "comments_disabled",
                    video_id=video_id,
                    error=str(e),
                )
                return []
            raise

        comments = []
        for item in data.get("items", []):
            top_comment = item.get("snippet", {}).get("topLevelComment", {})
            snippet = top_comment.get("snippet", {})

            comment_id = top_comment.get("id", "")
            published_at = snippet.get("publishedAt", "")

            # Check if comment is within our 7-day window
            if published_at:
                try:
                    comment_time = datetime.fromisoformat(
                        published_at.replace("Z", "+00:00")
                    )
                    if comment_time < self._cutoff:
                        continue  # Skip old comments
                except ValueError:
                    pass  # If we can't parse, include it

            comments.append({
                "comment_id": comment_id,
                "author": snippet.get("authorDisplayName", "[unknown]"),
                "text": snippet.get("textDisplay", ""),
                "like_count": snippet.get("likeCount", 0),
                "published_at": published_at,
            })

        return comments

    # ── Step 3: Normalize to Standard Schema ─────────────────────

    def normalize_post(
        self,
        comment: Dict[str, Any],
        video: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Convert a YouTube comment + its parent video metadata
        into our standard IngestedPost schema.

        Wraps video context into the text field so the Tier-1
        regex filter and Tier-2 LLM validator have full context.
        """
        # Build context-wrapped text
        video_title = video.get("title", "")
        video_desc = video.get("description", "")
        comment_text = comment.get("text", "")

        # Truncate description to avoid massive text blobs
        if len(video_desc) > 300:
            video_desc = video_desc[:300] + "..."

        full_text = (
            f"[Video Topic: {video_title}]\n"
            f"[Video Description: {video_desc}]\n\n"
            f"Commenter Question: {comment_text}"
        )

        # Parse timestamp
        published_at = comment.get("published_at", "")
        if published_at:
            timestamp = published_at.replace("Z", "+00:00")
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        video_id = video.get("video_id", "")
        comment_id = comment.get("comment_id", "")

        return {
            "platform": "youtube",
            "post_id": comment_id,
            "author": comment.get("author", "[unknown]"),
            "source": f"{video.get('channel_title', 'Unknown Channel')}",
            "url": f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
            "timestamp": timestamp,
            "title": f"Comment on: {video_title}",
            "text": full_text,
            "score": comment.get("like_count", 0),
            "video_id": video_id,             # Extra: for grouping
            "video_title": video_title,        # Extra: for dashboard display
        }

    # ── Main Fetch (Async interface) ─────────────────────────────

    async def fetch_posts(
        self,
        query: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Async wrapper — delegates to fetch_posts_sync since
        the YouTube API client uses synchronous requests.
        """
        return self.fetch_posts_sync(query=query, limit=limit)

    # ── Main Fetch (Sync) ────────────────────────────────────────

    def fetch_posts_sync(
        self,
        query: Optional[str] = None,
        limit: int = 25,
        max_videos: int = MAX_VIDEOS_PER_SEARCH,
    ) -> List[Dict[str, Any]]:
        """
        Full ingestion pipeline:
        1. Search for videos using consolidated query groups
        2. Fetch comments from each video
        3. Normalize and return

        Args:
            query: Optional single search query. If None, uses all groups.
            limit: Max comments to fetch per video.
            max_videos: Max videos per search query.

        Returns:
            List of normalized post dicts, deduplicated by comment_id.
        """
        import time

        queries = [query] if query else self.search_groups
        seen_comment_ids = set()
        seen_video_ids = set()
        results = []

        for q in queries:
            try:
                videos = self._search_videos(q, max_results=max_videos)
            except Exception as e:
                logger.error("video_search_failed", query=q[:60], error=str(e))
                continue

            for video in videos:
                vid_id = video["video_id"]

                # Skip if we already processed this video from another query
                if vid_id in seen_video_ids:
                    continue
                seen_video_ids.add(vid_id)

                # Small delay to be respectful of rate limits
                time.sleep(RATE_LIMIT_DELAY_SEC)

                try:
                    comments = self._fetch_comments(vid_id, max_results=limit)
                except Exception as e:
                    logger.error(
                        "comment_fetch_failed",
                        video_id=vid_id,
                        error=str(e),
                    )
                    continue

                for comment in comments:
                    cid = comment["comment_id"]
                    if cid in seen_comment_ids:
                        continue
                    seen_comment_ids.add(cid)

                    normalized = self.normalize_post(comment, video)
                    results.append(normalized)

                    logger.info(
                        "comment_fetched",
                        video_id=vid_id,
                        comment_id=cid,
                        author=comment["author"][:30],
                    )

        logger.info(
            "ingestion_complete",
            platform="youtube",
            total_comments=len(results),
            videos_searched=len(seen_video_ids),
            queries_used=len(queries),
        )

        return results
