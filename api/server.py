"""
API Server — Main FastAPI application.

Orchestrates the entire pipeline:
- Serves the admin dashboard (Jinja2 templates)
- Exposes REST endpoints for ingestion, queue management, and posting
- Manages database connections and background tasks
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Lead-Gen Pipeline",
    description="Social Media Lead Generation Pipeline with Human-in-the-Loop",
    version="0.1.0",
)

# Mount static files for the dashboard
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

# Jinja2 templates for dashboard pages
templates = Jinja2Templates(directory="dashboard/templates")


# TODO: Register API routes
# from api.routes import ingest, queue, post, metrics
# app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingestion"])
# app.include_router(queue.router, prefix="/api/queue", tags=["Review Queue"])
# app.include_router(post.router, prefix="/api/post", tags=["Execution"])
# app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])


@app.get("/")
async def dashboard_home():
    """Redirect to the dashboard overview page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
