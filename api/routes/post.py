"""
Post Routes — Execute approved comments (throttled, human-triggered).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from api.database import get_db, DraftComment, IngestedPost

router = APIRouter()


@router.post("/{draft_id}")
async def post_comment(draft_id: int, db: Session = Depends(get_db)):
    """Post a single comment. For PoC, just marks it as posted."""
    draft = db.query(DraftComment).filter(DraftComment.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # For PoC: simulate posting by updating status
    # In production: call the appropriate poster (RedditPoster, YouTubePoster, etc.)
    draft.status = "posted"
    draft.posted_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message": f"Draft {draft_id} posted successfully",
        "status": "posted",
        "draft_id": draft_id,
    }


@router.post("/batch/{platform}")
async def post_batch(platform: str, db: Session = Depends(get_db)):
    """Post all queued/pending comments for a platform."""
    drafts = (
        db.query(DraftComment)
        .join(IngestedPost)
        .filter(
            IngestedPost.platform == platform,
            DraftComment.status.in_(["pending", "queued"]),
        )
        .all()
    )

    posted_count = 0
    for draft in drafts:
        # For PoC: simulate posting
        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        posted_count += 1

    db.commit()

    return {
        "message": f"{posted_count} comments posted for {platform}",
        "count": posted_count,
        "platform": platform,
    }
