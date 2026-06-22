"""
X (Twitter) Poster — Posts replies via X API v2 with OAuth 1.0a.

Human-triggered from the dashboard. When the user clicks "Post Reply"
or "Queue All Posts", this module handles the actual X API calls.

Features:
  - OAuth 1.0a HMAC-SHA1 signing (no extra dependencies — uses stdlib)
  - Built-in rate limiting (1 reply per 30 seconds — conservative for free tier)
  - Queue processor: drains all 'queued' drafts sequentially with delays
  - Error isolation: one failed post doesn't block the rest of the queue
  - Tweet ID extraction from various X/Twitter URL formats

X API v2 Free Tier Limits:
  - 50 tweets/day (creation)
  - 1,500 tweets/month (read)
  - We use 30s delay between posts to stay well within limits

Requires: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in .env
"""

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import requests

from src.execution.base_poster import BasePoster
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("x_poster")

# ── X API v2 endpoint ────────────────────────────────────────────
X_TWEET_URL = "https://api.twitter.com/2/tweets"

# ── Rate limit: Free tier allows 50 tweets/day.
# 30 seconds between posts keeps us safe at ~2880 max/day (well above 50).
X_REPLY_DELAY_SEC = 10


class XPoster(BasePoster):
    """
    Posts replies to X/Twitter via API v2 using OAuth 1.0a.

    Usage:
        poster = XPoster()

        # Single post
        result = await poster.post_comment(tweet_url, reply_text)

        # Queue drain (batch)
        results = await poster.process_queue(db_session)
    """

    def __init__(self):
        super().__init__(platform_name="x", requests_per_minute=2)

        self.api_key = settings.x_api_key
        self.api_secret = settings.x_api_secret
        self.access_token = settings.x_access_token
        self.access_secret = settings.x_access_secret

        # Quick validation
        if not self.api_key or not self.access_token:
            logger.error("x_poster_credentials_missing")
        else:
            logger.info("x_poster_initialized")

    # ── OAuth 1.0a HMAC-SHA1 Signing ─────────────────────────────
    # Implements RFC 5849 signature generation using only stdlib.
    # No external OAuth libraries needed.

    def _percent_encode(self, s: str) -> str:
        """RFC 5849 percent-encoding (slightly stricter than URL encoding)."""
        return urllib.parse.quote(str(s), safe="")

    def _generate_oauth_signature(
        self,
        method: str,
        url: str,
        params: Dict[str, str],
    ) -> str:
        """
        Generate an OAuth 1.0a HMAC-SHA1 signature.

        Steps (per RFC 5849):
          1. Sort all parameters alphabetically
          2. Concatenate into a parameter string
          3. Build the signature base string: METHOD&URL&PARAMS
          4. Sign with HMAC-SHA1 using consumer_secret&token_secret as key
        """
        # Sort parameters and build parameter string
        sorted_params = sorted(params.items())
        param_string = "&".join(
            f"{self._percent_encode(k)}={self._percent_encode(v)}"
            for k, v in sorted_params
        )

        # Build signature base string
        base_string = "&".join([
            method.upper(),
            self._percent_encode(url),
            self._percent_encode(param_string),
        ])

        # Build signing key
        signing_key = (
            f"{self._percent_encode(self.api_secret)}"
            f"&{self._percent_encode(self.access_secret)}"
        )

        # HMAC-SHA1
        hashed = hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha1,
        )

        return base64.b64encode(hashed.digest()).decode("utf-8")

    def _build_auth_header(
        self,
        method: str,
        url: str,
        body_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Build the full OAuth 1.0a Authorization header value.

        Returns a string like:
          OAuth oauth_consumer_key="...", oauth_nonce="...", ...
        """
        # OAuth parameters
        oauth_params = {
            "oauth_consumer_key": self.api_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.access_token,
            "oauth_version": "1.0",
        }

        # For signature, combine OAuth params with any body params
        # (for POST with application/x-www-form-urlencoded)
        # For JSON bodies, body params are NOT included in signature
        all_params = dict(oauth_params)
        if body_params:
            all_params.update(body_params)

        # Generate signature
        signature = self._generate_oauth_signature(method, url, all_params)
        oauth_params["oauth_signature"] = signature

        # Build header string
        header_parts = ", ".join(
            f'{self._percent_encode(k)}="{self._percent_encode(v)}"'
            for k, v in sorted(oauth_params.items())
        )

        return f"OAuth {header_parts}"

    # ── Extract tweet ID from URL ────────────────────────────────

    @staticmethod
    def _extract_tweet_id(tweet_url: str) -> Optional[str]:
        """
        Extract the tweet ID from various X/Twitter URL formats.

        Handles:
          - https://x.com/username/status/1234567890
          - https://twitter.com/username/status/1234567890
          - https://mobile.twitter.com/username/status/1234567890
          - Bare tweet IDs like '1234567890'
        """
        match = re.search(r"/status/(\d+)", tweet_url)
        if match:
            return match.group(1)

        # Already a bare numeric ID
        if re.match(r"^\d+$", tweet_url):
            return tweet_url

        return None

    # ── Core: Post a single reply ────────────────────────────────

    async def post_comment(
        self, post_url: str, comment_text: str
    ) -> Dict[str, Any]:
        """
        Post a reply to a tweet via X API v2.

        Runs the HTTP call in a thread executor so it doesn't
        block the async event loop.

        Args:
            post_url: Full tweet URL or tweet ID.
            comment_text: The reply text (should be ≤280 chars).

        Returns:
            Dict with keys: success, platform, post_url, comment_url, error
        """
        tweet_id = self._extract_tweet_id(post_url)
        if not tweet_id:
            return {
                "success": False,
                "platform": "x",
                "post_url": post_url,
                "comment_url": None,
                "error": f"Could not extract tweet ID from URL: {post_url}",
            }

        # Respect rate limit
        self._wait_for_rate_limit()

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._post_reply_sync,
                tweet_id,
                comment_text,
            )
            return result

        except Exception as e:
            logger.error(
                "x_post_failed",
                tweet_id=tweet_id,
                error=str(e),
            )
            return {
                "success": False,
                "platform": "x",
                "post_url": post_url,
                "comment_url": None,
                "error": str(e),
            }

    def _post_reply_sync(
        self, tweet_id: str, reply_text: str
    ) -> Dict[str, Any]:
        """
        Synchronous HTTP call to post a reply via X API v2.
        Uses OAuth 1.0a HMAC-SHA1 authentication.
        """
        # Truncate to 280 chars if somehow exceeding limit
        if len(reply_text) > 280:
            reply_text = reply_text[:277] + "..."

        # Build request body
        payload = {
            "text": reply_text,
            "reply": {
                "in_reply_to_tweet_id": tweet_id,
            },
        }

        # Build OAuth 1.0a Authorization header
        # For JSON body POST, body params are NOT included in OAuth signature
        auth_header = self._build_auth_header("POST", X_TWEET_URL)

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                X_TWEET_URL,
                headers=headers,
                json=payload,
                timeout=15,
            )

            if response.status_code == 201:
                data = response.json()
                new_tweet_id = data.get("data", {}).get("id", "")
                # We don't know the username from the response alone,
                # so we construct a partial URL
                comment_url = f"https://x.com/i/status/{new_tweet_id}"

                logger.info(
                    "reply_posted",
                    in_reply_to=tweet_id,
                    new_tweet_id=new_tweet_id,
                    comment_url=comment_url,
                )

                return {
                    "success": True,
                    "platform": "x",
                    "post_url": f"https://x.com/i/status/{tweet_id}",
                    "comment_url": comment_url,
                    "tweet_id": new_tweet_id,
                    "error": None,
                }

            else:
                error_body = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("detail", "")
                    errors = error_json.get("errors", [])
                    if errors:
                        error_detail = "; ".join(
                            e.get("message", str(e)) for e in errors
                        )
                except Exception:
                    error_detail = error_body[:200]

                error_msg = (
                    f"X API {response.status_code}: {error_detail}"
                )
                logger.error(
                    "x_api_error",
                    tweet_id=tweet_id,
                    status_code=response.status_code,
                    error=error_msg,
                )

                return {
                    "success": False,
                    "platform": "x",
                    "post_url": f"https://x.com/i/status/{tweet_id}",
                    "comment_url": None,
                    "error": error_msg,
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "platform": "x",
                "post_url": f"https://x.com/i/status/{tweet_id}",
                "comment_url": None,
                "error": "Request timed out after 15 seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "platform": "x",
                "post_url": f"https://x.com/i/status/{tweet_id}",
                "comment_url": None,
                "error": str(e),
            }

    # ── Queue Processor: Drain all queued X drafts ───────────────

    async def process_queue(self, db) -> Dict[str, Any]:
        """
        Process all 'queued' X drafts sequentially with rate limiting.

        Fetches all drafts with status='queued' for X, posts them
        one by one with X_REPLY_DELAY_SEC gap between each,
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
                IngestedPost.platform == "x",
                DraftComment.status == "queued",
            )
            .order_by(DraftComment.created_at.asc())
            .all()
        )

        total = len(drafts)
        posted = 0
        failed = 0
        skipped = 0

        logger.info("queue_processing_started", platform="x", total=total)

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
                    seconds=X_REPLY_DELAY_SEC,
                )
                await asyncio.sleep(X_REPLY_DELAY_SEC)

        summary = {
            "platform": "x",
            "total": total,
            "posted": posted,
            "failed": failed,
            "skipped": skipped,
        }

        logger.info("queue_processing_complete", **summary)
        return summary
