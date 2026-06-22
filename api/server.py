"""
API Server — Main FastAPI application.

Orchestrates the entire pipeline:
- Serves the admin dashboard (Jinja2 templates)
- Exposes REST endpoints for ingestion, queue management, and posting
- Manages database connections and background tasks
"""

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from api.database import get_db, init_db, IngestedPost, DraftComment, PipelineRun
from api.routes import ingest, queue, post, metrics

import os
from datetime import datetime, timezone, timedelta

app = FastAPI(
    title="Lead-Gen Pipeline",
    description="Social Media Lead Generation Pipeline with Human-in-the-Loop",
    version="0.1.0",
)

# Mount static files for the dashboard
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

# Jinja2 templates for dashboard pages
templates = Jinja2Templates(directory="dashboard/templates")


# ── Startup: Initialize DB ──────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


# ── Register API routes ─────────────────────────────────────────

app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])
app.include_router(queue.router, prefix="/api/queue", tags=["Review Queue"])
app.include_router(post.router, prefix="/api/post", tags=["Execution"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingestion"])


# ── Platform config (used by templates) ─────────────────────────

PLATFORM_CONFIG = {
    "reddit": {
        "name": "Reddit",
        "color": "#FF4500",
        "icon": "reddit",
        "post_label": "📝 Reddit Post",
        "response_label": "🤖 AI-Generated Comment",
        "post_truncate": 150,
        "response_truncate": 250,
        "post_button": "📤 Post Comment",
        "post_action": "api",
    },
    "youtube": {
        "name": "YouTube",
        "color": "#FF0000",
        "icon": "youtube",
        "post_label": "💬 YouTube Comment",
        "response_label": "🤖 AI-Generated Reply",
        "post_truncate": 150,
        "response_truncate": 250,
        "post_button": "📤 Post Comment",
        "post_action": "api",
    },
    "x": {
        "name": "X (Twitter)",
        "color": "#1DA1F2",
        "icon": "x",
        "post_label": "🐦 Tweet",
        "response_label": "🤖 AI-Generated Reply",
        "post_truncate": 280,
        "response_truncate": 280,
        "post_button": "📤 Post Reply",
        "post_action": "api",
    },
    "quora": {
        "name": "Quora",
        "color": "#B92B27",
        "icon": "quora",
        "post_label": "❓ Question",
        "response_label": "🤖 AI-Generated Answer",
        "post_truncate": 120,
        "response_truncate": 300,
        "post_button": "📋 Copy & Open",
        "post_action": "clipboard",
    },
}


# ── Helper: relative timestamp ──────────────────────────────────

def relative_time(dt):
    """Convert datetime to '2 hours ago' style string."""
    if not dt:
        return "unknown"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        m = seconds // 60
        return f"{m}m ago"
    elif seconds < 86400:
        h = seconds // 3600
        return f"{h}h ago"
    else:
        d = seconds // 86400
        return f"{d}d ago"


# ── Dashboard Page Routes ───────────────────────────────────────

@app.get("/")
async def root():
    """Redirect to dashboard."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    """Home page with flip cards and pipeline summary."""

    # Aggregate stats per platform
    platform_stats = {}
    for platform_key in ["reddit", "youtube", "x", "quora"]:
        fetched = db.query(func.count(IngestedPost.id)).filter(
            IngestedPost.platform == platform_key
        ).scalar() or 0

        filtered = db.query(func.count(IngestedPost.id)).filter(
            IngestedPost.platform == platform_key,
            IngestedPost.tier2_passed == True,
        ).scalar() or 0

        drafted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
            IngestedPost.platform == platform_key,
        ).scalar() or 0

        posted = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
            IngestedPost.platform == platform_key,
            DraftComment.status == "posted",
        ).scalar() or 0

        # Last run time
        last_run = db.query(PipelineRun).filter(
            PipelineRun.platform == platform_key,
        ).order_by(PipelineRun.started_at.desc()).first()

        platform_stats[platform_key] = {
            "fetched": fetched,
            "filtered": filtered,
            "drafted": drafted,
            "posted": posted,
            "last_run": relative_time(last_run.started_at) if last_run else "Never",
            "config": PLATFORM_CONFIG[platform_key],
        }

    # Totals
    total_fetched = sum(s["fetched"] for s in platform_stats.values())
    total_filtered = sum(s["filtered"] for s in platform_stats.values())
    total_drafted = sum(s["drafted"] for s in platform_stats.values())
    total_posted = sum(s["posted"] for s in platform_stats.values())
    queue_pending = db.query(func.count(DraftComment.id)).filter(
        DraftComment.status == "pending"
    ).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "active_page": "home",
            "platform_stats": platform_stats,
            "total_fetched": total_fetched,
            "total_filtered": total_filtered,
            "total_drafted": total_drafted,
            "total_posted": total_posted,
            "queue_pending": queue_pending,
        },
    )


@app.get("/dashboard/{platform}")
async def dashboard_platform(platform: str, request: Request, db: Session = Depends(get_db)):
    """Platform-specific page with lead cards."""

    if platform not in PLATFORM_CONFIG:
        return RedirectResponse(url="/dashboard")

    config = PLATFORM_CONFIG[platform]

    # Analytics for this platform
    fetched = db.query(func.count(IngestedPost.id)).filter(
        IngestedPost.platform == platform
    ).scalar() or 0

    filtered = db.query(func.count(IngestedPost.id)).filter(
        IngestedPost.platform == platform,
        IngestedPost.tier2_passed == True,
    ).scalar() or 0

    commented = db.query(func.count(DraftComment.id)).join(IngestedPost).filter(
        IngestedPost.platform == platform,
        DraftComment.status == "posted",
    ).scalar() or 0

    # Get all leads with drafts for this platform (pending first, then posted)
    leads_raw = (
        db.query(DraftComment, IngestedPost)
        .join(IngestedPost, DraftComment.post_id == IngestedPost.id)
        .filter(IngestedPost.platform == platform)
        .order_by(
            # pending first, then queued, then posted, then rejected
            func.case(
                (DraftComment.status == "pending", 0),
                (DraftComment.status == "queued", 1),
                (DraftComment.status == "posted", 2),
                (DraftComment.status == "rejected", 3),
                else_=4,
            ),
            DraftComment.created_at.desc(),
        )
        .all()
    )

    leads = []
    for draft, post in leads_raw:
        leads.append({
            "id": draft.id,
            "post_title": post.title,
            "post_text": post.text,
            "post_url": post.url,
            "author": post.author,
            "source": post.source,
            "timestamp": relative_time(post.timestamp),
            "intent_score": draft.intent_score,
            "matched_scheme": draft.matched_scheme,
            "draft_text": draft.draft_text,
            "status": draft.status,
        })

    return templates.TemplateResponse(
        request=request,
        name="platform.html",
        context={
            "active_page": platform,
            "platform": platform,
            "config": config,
            "analytics": {
                "fetched": fetched,
                "filtered": filtered,
                "commented": commented,
            },
            "leads": leads,
        },
    )


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
