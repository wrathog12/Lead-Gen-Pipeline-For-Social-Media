"""
Reddit Poster — Posts comments via Reddit OAuth2 API (PRAW).

Human-triggered from the dashboard. When the user clicks "Post Comment"
or "Queue All Posts", this module handles the actual Reddit API calls.

Features:
  - OAuth2 authentication via PRAW (script-type app)
  - Built-in rate limiting (1 comment per 10 seconds — Reddit's limit)
  - Queue processor: drains all 'queued' drafts sequentially with delays
  - Error isolation: one failed post doesn't block the rest of the queue

Requires: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME,
          REDDIT_PASSWORD, REDDIT_USER_AGENT in .env
"""

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import praw
from praw.exceptions import RedditAPIException

from src.execution.base_poster import BasePoster
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("reddit_poster")

# ── Rate limit: Reddit allows ~1 comment per 10 seconds for new accounts
# Established accounts can go faster, but we stay safe for PoC.
REDDIT_COMMENT_DELAY_SEC = 10


class RedditPoster(BasePoster):
    """
    Posts comments to Reddit via OAuth2 API (PRAW).

    Usage:
        poster = RedditPoster()

        # Single post
        result = await poster.post_comment(post_url, comment_text)

        # Queue drain (batch)
        results = await poster.process_queue(db_session)
    """

    def __init__(self):
        super().__init__(platform_name="reddit", requests_per_minute=6)

        self.reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            username=settings.reddit_username,
            password=settings.reddit_password,
            user_agent=settings.reddit_user_agent,
        )

        # Verify we have working credentials at init
        try:
            me = self.reddit.user.me()
            self._authenticated_as = me.name if me else "unknown"
            logger.info(
                "reddit_poster_authenticated",
                user=self._authenticated_as,
            )
        except Exception as e:
            self._authenticated_as = None
            logger.error("reddit_poster_auth_failed", error=str(e))

    # ── Extract Reddit submission ID from a URL ──────────────────

    @staticmethod
    def _extract_submission_id(post_url: str) -> Optional[str]:
        """
        Extract the Reddit submission ID from various URL formats.

        Handles:
          - https://www.reddit.com/r/sub/comments/ABC123/title/
          - https://reddit.com/r/sub/comments/ABC123/
          - https://old.reddit.com/r/sub/comments/ABC123/title
          - Short IDs like 'ABC123' (already an ID)
        """
        # Full Reddit URL pattern
        match = re.search(r"/comments/([a-zA-Z0-9]+)", post_url)
        if match:
            return match.group(1)

        # Already a bare submission ID (no slashes, alphanumeric)
        if re.match(r"^[a-zA-Z0-9]+$", post_url):
            return post_url

        return None

    # ── Core: Post a single comment ──────────────────────────────

    async def post_comment(
        self, post_url: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Post a comment to a Reddit submission.

        This runs the synchronous PRAW call in a thread executor
        so it doesn't block the async event loop.

        Args:
            post_url: Full Reddit post URL or submission ID.
            comment_text: The draft comment text to post.

        Returns:
            Dict with keys: success, platform, post_url, comment_url, error
        """
        submission_id = self._extract_submission_id(post_url)
        if not submission_id:
            return {
                "success": False,
                "platform": "reddit",
                "post_url": post_url,
                "comment_url": None,
                "error": f"Could not extract submission ID from URL: {post_url}",
            }

        # Respect rate limit
        self._wait_for_rate_limit()

        try:
            # Run PRAW's synchronous API in a thread
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._post_comment_sync,
                submission_id,
                comment_text,
            )
            return result

        except Exception as e:
            logger.error(
                "reddit_post_failed",
                submission_id=submission_id,
                error=str(e),
            )
            return {
                "success": False,
                "platform": "reddit",
                "post_url": post_url,
                "comment_url": None,
                "error": str(e),
            }

    def _post_comment_sync(
        self, submission_id: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Synchronous PRAW call to post a comment. Runs in a thread executor.
        """
        try:
            submission = self.reddit.submission(id=submission_id)

            # Post the comment
            comment = submission.reply(comment_text)

            comment_url = f"https://www.reddit.com{comment.permalink}"

            logger.info(
                "comment_posted",
                submission_id=submission_id,
                comment_id=comment.id,
                comment_url=comment_url,
            )

            return {
                "success": True,
                "platform": "reddit",
                "post_url": f"https://www.reddit.com/comments/{submission_id}",
                "comment_url": comment_url,
                "comment_id": comment.id,
                "error": None,
            }

        except RedditAPIException as e:
            # Reddit-specific errors (rate limit, banned, etc.)
            error_msg = "; ".join(
                f"{err.error_type}: {err.message}" for err in e.items
            )
            logger.error(
                "reddit_api_error",
                submission_id=submission_id,
                error=error_msg,
            )
            return {
                "success": False,
                "platform": "reddit",
                "post_url": f"https://www.reddit.com/comments/{submission_id}",
                "comment_url": None,
                "error": f"Reddit API Error: {error_msg}",
            }

        except Exception as e:
            return {
                "success": False,
                "platform": "reddit",
                "post_url": f"https://www.reddit.com/comments/{submission_id}",
                "comment_url": None,
                "error": str(e),
            }

    # ── Queue Processor: Drain all queued Reddit drafts ──────────

    async def process_queue(self, db) -> Dict[str, Any]:
        """
        Process all 'queued' Reddit drafts sequentially with rate limiting.

        This is the batch posting method called by the 'Queue All' button.
        It fetches all drafts with status='queued' for Reddit, posts them
        one by one with a REDDIT_COMMENT_DELAY_SEC gap between each,
        and updates the DB status after each post.

        Args:
            db: SQLAlchemy Session (must be from SessionLocal, not a
                FastAPI dependency — since this runs in a background task).

        Returns:
            Summary dict with counts: total, posted, failed, skipped.
        """
        from api.database import DraftComment, IngestedPost

        # Fetch all queued Reddit drafts
        drafts = (
            db.query(DraftComment)
            .join(IngestedPost)
            .filter(
                IngestedPost.platform == "reddit",
                DraftComment.status == "queued",
            )
            .order_by(DraftComment.created_at.asc())
            .all()
        )

        total = len(drafts)
        posted = 0
        failed = 0
        skipped = 0

        logger.info("queue_processing_started", platform="reddit", total=total)

        for i, draft in enumerate(drafts):
            # Get the associated post for URL
            post = draft.post

            if not post or not post.url:
                logger.warning(
                    "queue_skip_no_url",
                    draft_id=draft.id,
                )
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

            # Post the comment
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

            # Rate limit: wait between posts (skip delay after last one)
            if i < total - 1:
                logger.info(
                    "queue_rate_limit_wait",
                    seconds=REDDIT_COMMENT_DELAY_SEC,
                )
                await asyncio.sleep(REDDIT_COMMENT_DELAY_SEC)

        summary = {
            "platform": "reddit",
            "total": total,
            "posted": posted,
            "failed": failed,
            "skipped": skipped,
        }

        logger.info("queue_processing_complete", **summary)
        return summary
