"""
Queue Routes — CRUD operations for the review queue.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from api.database import get_db, DraftComment, IngestedPost

router = APIRouter()


@router.get("/")
async def list_pending(db: Session = Depends(get_db)):
    """List all pending draft comments."""
    drafts = (
        db.query(DraftComment)
        .filter(DraftComment.status == "pending")
        .order_by(DraftComment.created_at.desc())
        .all()
    )
    return {
        "drafts": [{"id": d.id, "status": d.status, "post_id": d.post_id} for d in drafts],
        "count": len(drafts),
    }


@router.get("/{platform}")
async def list_platform_pending(platform: str, db: Session = Depends(get_db)):
    """List pending drafts for a specific platform."""
    drafts = (
        db.query(DraftComment)
        .join(IngestedPost)
        .filter(IngestedPost.platform == platform, DraftComment.status == "pending")
        .order_by(DraftComment.created_at.desc())
        .all()
    )
    return {
        "drafts": [{"id": d.id, "status": d.status, "post_id": d.post_id} for d in drafts],
        "count": len(drafts),
    }


@router.put("/{draft_id}/approve")
async def approve_draft(draft_id: int, db: Session = Depends(get_db)):
    """Approve a draft comment for posting (sets status to queued)."""
    draft = db.query(DraftComment).filter(DraftComment.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft.status = "queued"
    db.commit()
    return {"message": f"Draft {draft_id} queued for posting", "status": "queued"}


@router.put("/{draft_id}/reject")
async def reject_draft(draft_id: int, db: Session = Depends(get_db)):
    """Reject a draft comment."""
    draft = db.query(DraftComment).filter(DraftComment.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft.status = "rejected"
    db.commit()
    return {"message": f"Draft {draft_id} rejected", "status": "rejected"}


@router.post("/batch-approve/{platform}")
async def batch_approve(platform: str, db: Session = Depends(get_db)):
    """Approve all pending drafts for a platform."""
    drafts = (
        db.query(DraftComment)
        .join(IngestedPost)
        .filter(IngestedPost.platform == platform, DraftComment.status == "pending")
        .all()
    )

    for draft in drafts:
        draft.status = "queued"
    db.commit()

    return {"message": f"{len(drafts)} drafts queued for {platform}", "count": len(drafts)}

