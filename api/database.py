"""
Database — SQLAlchemy models and session management.

Uses SQLite for PoC (zero setup). Models track:
- Ingested posts and their pipeline status
- Draft comments in the review queue
- Posted comments for the audit log
- Pipeline metrics per run
"""

# TODO: Implement SQLAlchemy models
# - IngestedPostModel (tracks all fetched posts and filter outcomes)
# - DraftCommentModel (review queue entries)
# - PostedCommentModel (audit log)
# - PipelineRunModel (metrics per ingestion run)
