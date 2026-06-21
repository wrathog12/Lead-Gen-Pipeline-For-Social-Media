"""
Post Routes — Execute approved comments (throttled, human-triggered).
"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/{draft_id}")
async def post_comment(draft_id: int):
    """Post a single approved comment to its target platform (throttled)."""
    # TODO: Look up the draft, verify it's APPROVED, call the right poster
    # Respect per-platform rate limits
    return {"message": f"Posting draft {draft_id}", "status": "pending"}


@router.post("/batch")
async def post_batch():
    """Post all approved comments one-by-one with rate limiting."""
    # TODO: Iterate through approved drafts, post with delays
    return {"message": "Batch posting initiated", "status": "pending"}
