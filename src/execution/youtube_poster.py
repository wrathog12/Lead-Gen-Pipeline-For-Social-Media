"""
YouTube Poster — Posts comment replies via YouTube Data API v3.

Human-triggered from the dashboard. When the user clicks "Post Comment"
or "Queue All Posts", this module handles the actual YouTube API calls.

Features:
  - OAuth 2.0 Bearer token authentication for write operations
  - Built-in rate limiting (1 comment per 15 seconds — quota conservative)
  - Queue processor: drains all 'queued' drafts sequentially with delays
  - Error isolation: one failed post doesn't block the rest of the queue
  - Video ID / Comment ID extraction from YouTube URL formats

YouTube Data API v3 Quota:
  - Daily quota: 10,000 units
  - commentThreads.insert: 50 units per call → max ~200 comments/day
  - comments.insert (reply): 50 units per call
  - We use 15s delay between posts to pace ourselves

Auth Note:
  YouTube write operations require OAuth 2.0 user authorization.
  A plain API key (YOUTUBE_API_KEY) only works for read operations.
  For posting, set YOUTUBE_OAUTH_TOKEN in .env with a valid access token.

  To obtain an OAuth token for the PoC:
    1. Create OAuth 2.0 credentials in Google Cloud Console
    2. Enable YouTube Data API v3
    3. Use the OAuth playground (https://developers.google.com/oauthplayground/)
       to authorize with scope: https://www.googleapis.com/auth/youtube.force-ssl
    4. Copy the access token to .env as YOUTUBE_OAUTH_TOKEN

Requires: YOUTUBE_OAUTH_TOKEN in .env (YOUTUBE_API_KEY is read-only)
"""

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import requests

from src.execution.base_poster import BasePoster
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("youtube_poster")

# ── YouTube Data API v3 endpoints ────────────────────────────────
YT_COMMENT_THREADS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
YT_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/comments"

# ── Rate limit: 50 quota units per insert, 10,000 daily quota.
# 15 seconds between posts → max 5,760/day (capped at 200 by quota).
YT_COMMENT_DELAY_SEC = 15


class YouTubePoster(BasePoster):
    """
    Posts comments/replies to YouTube via Data API v3.

    Supports two posting modes:
      1. Top-level comment on a video (commentThreads.insert)
      2. Reply to an existing comment (comments.insert)

    The mode is determined by whether a parent comment ID is found
    in the post URL (the &lc= parameter from the ingester).

    Usage:
        poster = YouTubePoster()
        result = await poster.post_comment(youtube_url, comment_text)
        results = await poster.process_queue(db_session)
    """

    def __init__(self):
        super().__init__(platform_name="youtube", requests_per_minute=4)

        self.api_key = settings.youtube_api_key
        self.oauth_token = getattr(settings, "youtube_oauth_token", "")

        if self.oauth_token and self.oauth_token != "your_youtube_oauth_token_here":
            self._auth_ready = True
            logger.info("youtube_poster_initialized", auth="oauth2")
        else:
            self._auth_ready = False
            logger.warning(
                "youtube_poster_no_oauth",
                detail=(
                    "YOUTUBE_OAUTH_TOKEN not set. "
                    "YouTube posting requires OAuth 2.0. "
                    "Set YOUTUBE_OAUTH_TOKEN in .env to enable posting."
                ),
            )

    def _get_auth_headers(self) -> Dict[str, str]:
        """Build authorization headers for YouTube API write operations."""
        return {
            "Authorization": f"Bearer {self.oauth_token}",
            "Content-Type": "application/json",
        }

    # ── Extract video ID and comment ID from URL ─────────────────

    @staticmethod
    def _extract_ids(url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract video ID and (optional) parent comment ID from YouTube URLs.

        Handles:
          - https://www.youtube.com/watch?v=VIDEO_ID
          - https://www.youtube.com/watch?v=VIDEO_ID&lc=COMMENT_ID
          - https://youtu.be/VIDEO_ID
          - https://www.youtube.com/embed/VIDEO_ID
          - Bare video IDs like 'dQw4w9WgXcQ'

        Returns:
            Tuple of (video_id, comment_id). comment_id may be None.
        """
        video_id = None
        comment_id = None

        # Parse the URL
        parsed = urlparse(url)

        # Standard watch URL: youtube.com/watch?v=VIDEO_ID
        if "youtube.com" in parsed.netloc and parsed.path == "/watch":
            params = parse_qs(parsed.query)
            video_id = params.get("v", [None])[0]
            comment_id = params.get("lc", [None])[0]

        # Short URL: youtu.be/VIDEO_ID
        elif "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/")

        # Embed URL: youtube.com/embed/VIDEO_ID
        elif "youtube.com" in parsed.netloc and "/embed/" in parsed.path:
            video_id = parsed.path.split("/embed/")[-1].split("/")[0]

        # Bare video ID (11 chars, alphanumeric + _ -)
        elif re.match(r"^[a-zA-Z0-9_-]{11}$", url):
            video_id = url

        # Clean up video ID (remove any trailing params)
        if video_id:
            video_id = video_id.split("&")[0].split("?")[0]

        return video_id, comment_id

    # ── Core: Post a comment or reply ────────────────────────────

    async def post_comment(
        self, post_url: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Post a comment to a YouTube video or a reply to an existing comment.

        If the URL contains a &lc= parameter (parent comment ID),
        posts a reply to that comment. Otherwise, posts a new
        top-level comment on the video.

        Args:
            post_url: Full YouTube URL (from the ingester).
            comment_text: The draft comment text to post.

        Returns:
            Dict with keys: success, platform, post_url, comment_url, error
        """
        if not self._auth_ready:
            return {
                "success": False,
                "platform": "youtube",
                "post_url": post_url,
                "comment_url": None,
                "error": (
                    "YouTube posting requires OAuth 2.0. "
                    "Set YOUTUBE_OAUTH_TOKEN in .env."
                ),
            }

        video_id, parent_comment_id = self._extract_ids(post_url)

        if not video_id:
            return {
                "success": False,
                "platform": "youtube",
                "post_url": post_url,
                "comment_url": None,
                "error": f"Could not extract video ID from URL: {post_url}",
            }

        # Respect rate limit
        self._wait_for_rate_limit()

        try:
            loop = asyncio.get_event_loop()

            if parent_comment_id:
                # Reply to an existing comment
                result = await loop.run_in_executor(
                    None,
                    self._post_reply_sync,
                    video_id,
                    parent_comment_id,
                    comment_text,
                )
            else:
                # New top-level comment on video
                result = await loop.run_in_executor(
                    None,
                    self._post_top_level_sync,
                    video_id,
                    comment_text,
                )
            return result

        except Exception as e:
            logger.error(
                "youtube_post_failed",
                video_id=video_id,
                error=str(e),
            )
            return {
                "success": False,
                "platform": "youtube",
                "post_url": post_url,
                "comment_url": None,
                "error": str(e),
            }

    def _post_top_level_sync(
        self, video_id: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Post a new top-level comment on a YouTube video.
        Uses commentThreads.insert (50 quota units).
        """
        payload = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text,
                    }
                },
            }
        }

        try:
            response = requests.post(
                f"{YT_COMMENT_THREADS_URL}?part=snippet",
                headers=self._get_auth_headers(),
                json=payload,
                timeout=15,
            )

            return self._handle_response(response, video_id, "top_level")

        except requests.exceptions.Timeout:
            return self._error_result(video_id, "Request timed out after 15 seconds")
        except Exception as e:
            return self._error_result(video_id, str(e))

    def _post_reply_sync(
        self, video_id: str, parent_comment_id: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Post a reply to an existing YouTube comment.
        Uses comments.insert (50 quota units).
        """
        payload = {
            "snippet": {
                "parentId": parent_comment_id,
                "textOriginal": comment_text,
            }
        }

        try:
            response = requests.post(
                f"{YT_COMMENTS_URL}?part=snippet",
                headers=self._get_auth_headers(),
                json=payload,
                timeout=15,
            )

            return self._handle_response(response, video_id, "reply")

        except requests.exceptions.Timeout:
            return self._error_result(video_id, "Request timed out after 15 seconds")
        except Exception as e:
            return self._error_result(video_id, str(e))

    # ── Response parsing ─────────────────────────────────────────

    def _handle_response(
        self, response: requests.Response, video_id: str, mode: str
    ) -> Dict[str, Any]:
        """Parse the YouTube API response and return a standardized result."""

        if response.status_code in (200, 201):
            data = response.json()

            # Extract new comment ID from response
            if mode == "top_level":
                new_comment_id = (
                    data.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("id", "")
                )
            else:
                new_comment_id = data.get("id", "")

            comment_url = (
                f"https://www.youtube.com/watch?v={video_id}"
                f"&lc={new_comment_id}"
            )

            logger.info(
                "comment_posted",
                video_id=video_id,
                comment_id=new_comment_id,
                mode=mode,
                comment_url=comment_url,
            )

            return {
                "success": True,
                "platform": "youtube",
                "post_url": f"https://www.youtube.com/watch?v={video_id}",
                "comment_url": comment_url,
                "comment_id": new_comment_id,
                "error": None,
            }

        else:
            # Parse error from response
            try:
                error_json = response.json()
                error_detail = error_json.get("error", {}).get("message", "")
                error_reason = ""
                errors = error_json.get("error", {}).get("errors", [])
                if errors:
                    error_reason = errors[0].get("reason", "")
            except Exception:
                error_detail = response.text[:200]
                error_reason = ""

            error_msg = f"YouTube API {response.status_code}: {error_detail}"
            if error_reason:
                error_msg += f" (reason: {error_reason})"

            logger.error(
                "youtube_api_error",
                video_id=video_id,
                status_code=response.status_code,
                error=error_msg,
            )

            return self._error_result(video_id, error_msg)

    def _error_result(self, video_id: str, error: str) -> Dict[str, Any]:
        """Build a standardized error result dict."""
        return {
            "success": False,
            "platform": "youtube",
            "post_url": f"https://www.youtube.com/watch?v={video_id}",
            "comment_url": None,
            "error": error,
        }

    # ── Queue Processor: Drain all queued YouTube drafts ─────────

    async def process_queue(self, db) -> Dict[str, Any]:
        """
        Process all 'queued' YouTube drafts sequentially with rate limiting.

        Fetches all drafts with status='queued' for YouTube, posts them
        one by one with YT_COMMENT_DELAY_SEC gap between each,
        and updates the DB status after each post.

        Args:
            db: SQLAlchemy Session.

        Returns:
            Summary dict with counts: total, posted, failed, skipped.
        """
        from api.database import DraftComment, IngestedPost

        drafts = (
            db.query(DraftComment)
            .join(IngestedPost)
            .filter(
                IngestedPost.platform == "youtube",
                DraftComment.status == "queued",
            )
            .order_by(DraftComment.created_at.asc())
            .all()
        )

        total = len(drafts)
        posted = 0
        failed = 0
        skipped = 0

        logger.info("queue_processing_started", platform="youtube", total=total)

        for i, draft in enumerate(drafts):
            post = draft.post

            if not post or not post.url:
                logger.warning("queue_skip_no_url", draft_id=draft.id)
                draft.status = "failed"
                db.commit()
                skipped += 1
                continue

            logger.info(
                "queue_posting",
                draft_id=draft.id,
                post_url=post.url,
                progress=f"{i + 1}/{total}",
            )

            result = await self.post_comment(post.url, draft.draft_text)

            if result["success"]:
                draft.status = "posted"
                draft.posted_at = datetime.now(timezone.utc)
                draft.posted_url = result.get("comment_url", "")
                db.commit()
                posted += 1

                logger.info(
                    "queue_post_success",
                    draft_id=draft.id,
                    comment_url=result.get("comment_url"),
                )
            else:
                draft.status = "failed"
                db.commit()
                failed += 1

                logger.error(
                    "queue_post_failed",
                    draft_id=draft.id,
                    error=result.get("error"),
                )

            # Rate limit: wait between posts (skip delay after last)
            if i < total - 1:
                logger.info(
                    "queue_rate_limit_wait",
                    seconds=YT_COMMENT_DELAY_SEC,
                )
                await asyncio.sleep(YT_COMMENT_DELAY_SEC)

        summary = {
            "platform": "youtube",
            "total": total,
            "posted": posted,
            "failed": failed,
            "skipped": skipped,
        }

        logger.info("queue_processing_complete", **summary)
        return summary
