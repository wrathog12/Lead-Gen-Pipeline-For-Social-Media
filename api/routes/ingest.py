"""
Ingest Routes — Trigger ingestion runs per platform.
"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/run/{platform}")
async def trigger_ingestion(platform: str):
    """Trigger an ingestion run for a specific platform."""
    # TODO: Call the appropriate ingester and run the pipeline
    return {"message": f"Ingestion triggered for {platform}", "status": "pending"}


@router.get("/status")
async def ingestion_status():
    """Get the status of all ingestion spokes."""
    # TODO: Return last run time, post counts, errors per platform
    return {"status": "not_implemented"}
