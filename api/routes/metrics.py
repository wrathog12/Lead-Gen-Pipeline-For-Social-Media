"""
Metrics Routes — Dashboard statistics endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from api.database import get_db, IngestedPost, DraftComment, PipelineRun

router = APIRouter()


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)):
    """Get overview metrics for the dashboard."""

    by_platform = {}
    for platform in ["reddit", "youtube", "x", "quora"]:
        fetched = db.query(func.count(IngestedPost.id)).filter(
            IngestedPost.platform == platform
        ).scalar() or 0

        filtered = db.query(func.count(IngestedPost.id)).filter(
            IngestedPost.platform == platform,
            IngestedPost.tier2_passed == True,
        ).scalar() or 0

        drafted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
            IngestedPost.platform == platform,
        ).scalar() or 0

        posted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
            IngestedPost.platform == platform,
            DraftComment.status == "posted",
        ).scalar() or 0

        by_platform[platform] = {
            "fetched": fetched,
            "filtered": filtered,
            "drafted": drafted,
            "posted": posted,
        }

    total_fetched = sum(p["fetched"] for p in by_platform.values())
    total_filtered = sum(p["filtered"] for p in by_platform.values())
    total_drafted = sum(p["drafted"] for p in by_platform.values())
    total_posted = sum(p["posted"] for p in by_platform.values())
    queue_pending = db.query(func.count(DraftComment.id)).filter(
        DraftComment.status == "pending"
    ).scalar() or 0

    return {
        "total_fetched": total_fetched,
        "total_filtered": total_filtered,
        "total_drafted": total_drafted,
        "total_posted": total_posted,
        "queue_pending": queue_pending,
        "by_platform": by_platform,
    }


@router.get("/platform/{platform}")
async def get_platform_metrics(platform: str, db: Session = Depends(get_db)):
    """Get detailed metrics for a specific platform."""

    fetched = db.query(func.count(IngestedPost.id)).filter(
        IngestedPost.platform == platform
    ).scalar() or 0

    filtered = db.query(func.count(IngestedPost.id)).filter(
        IngestedPost.platform == platform,
        IngestedPost.tier2_passed == True,
    ).scalar() or 0

    drafted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
        IngestedPost.platform == platform,
    ).scalar() or 0

    posted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
        IngestedPost.platform == platform,
        DraftComment.status == "posted",
    ).scalar() or 0

    pending = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
        IngestedPost.platform == platform,
        DraftComment.status == "pending",
    ).scalar() or 0

    last_run = db.query(PipelineRun).filter(
        PipelineRun.platform == platform,
    ).order_by(PipelineRun.started_at.desc()).first()

    return {
        "platform": platform,
        "fetched": fetched,
        "filtered": filtered,
        "drafted": drafted,
        "posted": posted,
        "pending": pending,
        "last_run": last_run.started_at.isoformat() if last_run else None,
    }
