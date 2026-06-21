"""
Metrics Routes — Dashboard statistics endpoints.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/overview")
async def get_overview():
    """Get overview metrics for the dashboard."""
    # TODO: Return aggregated stats
    return {
        "total_fetched": 0,
        "by_platform": {
            "reddit": {"fetched": 0, "passed_t1": 0, "passed_t2": 0, "drafted": 0, "posted": 0},
            "youtube": {"fetched": 0, "passed_t1": 0, "passed_t2": 0, "drafted": 0, "posted": 0},
            "x": {"fetched": 0, "passed_t1": 0, "passed_t2": 0, "drafted": 0, "posted": 0},
            "quora": {"fetched": 0, "passed_t1": 0, "passed_t2": 0, "drafted": 0, "posted": 0},
        },
        "queue_pending": 0,
        "total_posted": 0,
    }


@router.get("/platform/{platform}")
async def get_platform_metrics(platform: str):
    """Get detailed metrics for a specific platform."""
    # TODO: Return platform-specific stats
    return {"platform": platform, "status": "not_implemented"}
