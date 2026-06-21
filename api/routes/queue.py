"""
Queue Routes — CRUD operations for the review queue.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_pending():
    """List all pending draft comments for human review."""
    # TODO: Query database for pending drafts
    return {"drafts": [], "count": 0}


@router.put("/{draft_id}/approve")
async def approve_draft(draft_id: int):
    """Approve a draft comment for posting."""
    # TODO: Update draft status to APPROVED
    return {"message": f"Draft {draft_id} approved"}


@router.put("/{draft_id}/reject")
async def reject_draft(draft_id: int):
    """Reject a draft comment."""
    # TODO: Update draft status to REJECTED
    return {"message": f"Draft {draft_id} rejected"}


@router.put("/{draft_id}/edit")
async def edit_draft(draft_id: int, new_text: str):
    """Edit a draft comment's text before approval."""
    # TODO: Update draft text in database
    return {"message": f"Draft {draft_id} updated"}
