"""
Post Routes — Execute approved comments (throttled, human-triggered).

Provides two posting modes:
  1. Single post:   POST /api/post/{draft_id}  — posts one comment immediately
  2. Batch queue:   POST /api/post/batch/{platform} — queues all pending drafts
                    then drains the queue in a background task with rate limiting

For Reddit, actual API calls are made via RedditPoster.
For other platforms, we simulate posting (PoC mode) until their posters are built.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from api.database import get_db, SessionLocal, DraftComment, IngestedPost
from src.utils.logger import get_logger

logger = get_logger("post_routes")

router = APIRouter()


# ── Lazy singleton posters ───────────────────────────────────────
# Heavy objects (PRAW client, API clients) initialized on first use.

_reddit_poster = None
_x_poster = None
_youtube_poster = None
_poster_lock = asyncio.Lock()


async def _get_reddit_poster():
    """Lazily initialize the Reddit poster singleton."""
    global _reddit_poster
    async with _poster_lock:
        if _reddit_poster is None:
            from src.execution.reddit_poster import RedditPoster
            _reddit_poster = RedditPoster()
    return _reddit_poster


async def _get_x_poster():
    """Lazily initialize the X poster singleton."""
    global _x_poster
    async with _poster_lock:
        if _x_poster is None:
            from src.execution.x_poster import XPoster
            _x_poster = XPoster()
    return _x_poster


async def _get_youtube_poster():
    """Lazily initialize the YouTube poster singleton."""
    global _youtube_poster
    async with _poster_lock:
        if _youtube_poster is None:
            from src.execution.youtube_poster import YouTubePoster
            _youtube_poster = YouTubePoster()
    return _youtube_poster


# ── Track running queue processors ───────────────────────────────
_queue_running: dict = {}


# ═══════════════════════════════════════════════════════════════════
# Single Comment Posting
# ═══════════════════════════════════════════════════════════════════


@router.post("/{draft_id}")
async def post_comment(draft_id: int, db: Session = Depends(get_db)):
    """
    Post a single comment. Uses the real poster for Reddit,
    simulates posting for other platforms (PoC mode).
    """
    draft = db.query(DraftComment).filter(DraftComment.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status == "posted":
        return {"message": "Already posted", "status": "posted", "draft_id": draft_id}

    # Get the associated post for platform info and URL
    post = db.query(IngestedPost).filter(IngestedPost.id == draft.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Associated post not found")

    platform = post.platform

    # ── Reddit / X / YouTube: Real API posting ─────────────────────
    if platform in ("reddit", "x", "youtube"):
        if platform == "reddit":
            poster = await _get_reddit_poster()
        elif platform == "x":
            poster = await _get_x_poster()
        else:
            poster = await _get_youtube_poster()

        result = await poster.post_comment(post.url, draft.draft_text)

        if result["success"]:
            draft.status = "posted"
            draft.posted_at = datetime.now(timezone.utc)
            draft.posted_url = result.get("comment_url", "")
            db.commit()

            return {
                "message": f"Comment posted to {platform.capitalize()}!",
                "status": "posted",
                "draft_id": draft_id,
                "comment_url": result.get("comment_url"),
            }
        else:
            return {
                "message": f"Failed to post: {result.get('error')}",
                "status": "failed",
                "draft_id": draft_id,
            }

    # ── Other platforms: Simulate posting (PoC) ──────────────────
    else:
        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "message": f"Draft {draft_id} posted successfully (simulated)",
            "status": "posted",
            "draft_id": draft_id,
        }


# ═══════════════════════════════════════════════════════════════════
# Batch Queue Processing
# ═══════════════════════════════════════════════════════════════════


async def _process_platform_queue(platform: str):
    """
    Background task: drain all 'queued' drafts for a platform
    using its real poster with rate limiting.
    """
    db = SessionLocal()
    try:
        if platform == "reddit":
            poster = await _get_reddit_poster()
        elif platform == "x":
            poster = await _get_x_poster()
        elif platform == "youtube":
            poster = await _get_youtube_poster()
        else:
            logger.error("no_poster_for_platform", platform=platform)
            return

        result = await poster.process_queue(db)
        logger.info("queue_complete", **result)
    except Exception as e:
        logger.error("queue_error", platform=platform, error=str(e))
    finally:
        _queue_running[platform] = False
        db.close()


async def _process_simulated_queue(platform: str):
    """
    Background task: mark all 'queued' drafts as 'posted' for
    platforms that don't have real posters yet. Adds a 2-second
    delay between each to simulate rate limiting.
    """
    db = SessionLocal()
    try:
        drafts = (
            db.query(DraftComment)
            .join(IngestedPost)
            .filter(
                IngestedPost.platform == platform,
                DraftComment.status == "queued",
            )
            .order_by(DraftComment.created_at.asc())
            .all()
        )

        posted = 0
        for i, draft in enumerate(drafts):
            draft.status = "posted"
            draft.posted_at = datetime.now(timezone.utc)
            db.commit()
            posted += 1

            # Simulate rate limiting
            if i < len(drafts) - 1:
                await asyncio.sleep(2)

        logger.info(
            "simulated_queue_complete",
            platform=platform,
            posted=posted,
        )
    except Exception as e:
        logger.error("simulated_queue_error", platform=platform, error=str(e))
    finally:
        _queue_running[platform] = False
        db.close()


@router.post("/batch/{platform}")
async def post_batch(
    platform: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Queue all pending/queued comments for a platform and process
    them in a background task with rate limiting.

    Step 1: Mark all 'pending' drafts as 'queued' in the DB.
    Step 2: Kick off a background task that drains the queue
            sequentially, respecting the platform's rate limits.
    """
    if _queue_running.get(platform):
        return {
            "message": f"Queue already processing for {platform}",
            "status": "already_running",
        }

    # Step 1: Move all pending → queued
    pending_drafts = (
        db.query(DraftComment)
        .join(IngestedPost)
        .filter(
            IngestedPost.platform == platform,
            DraftComment.status.in_(["pending"]),
        )
        .all()
    )

    for draft in pending_drafts:
        draft.status = "queued"
    db.commit()

    # Count total queued (including any already queued before this call)
    total_queued = (
        db.query(DraftComment)
        .join(IngestedPost)
        .filter(
            IngestedPost.platform == platform,
            DraftComment.status == "queued",
        )
        .count()
    )

    if total_queued == 0:
        return {
            "message": f"No comments to post for {platform}",
            "count": 0,
            "status": "empty",
        }

    # Step 2: Start background queue processor
    _queue_running[platform] = True

    if platform in ("reddit", "x", "youtube"):
        background_tasks.add_task(_process_platform_queue, platform)
    else:
        background_tasks.add_task(_process_simulated_queue, platform)

    return {
        "message": f"{total_queued} comments queued for {platform} — posting in background",
        "count": total_queued,
        "platform": platform,
        "status": "queue_started",
    }


# ═══════════════════════════════════════════════════════════════════
# Queue Status
# ═══════════════════════════════════════════════════════════════════


@router.get("/queue-status")
async def queue_status():
    """Check which platform queues are currently being processed."""
    return {
        "running": {
            platform: is_running
            for platform, is_running in _queue_running.items()
        }
    }
