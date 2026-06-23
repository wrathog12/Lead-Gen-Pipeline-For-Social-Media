"""
Database — SQLAlchemy models and session management.

Uses SQLite for PoC (zero setup). Models track:
- Ingested posts and their pipeline status
- Draft comments in the review queue
- Pipeline run metrics
"""

from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, Float, ForeignKey, event,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = "sqlite:///./data/leadgen.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=30,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Dependency — yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Models ────────────────────────────────────────────────────────


class IngestedPost(Base):
    """Tracks every post fetched by the ingestion spokes."""
    __tablename__ = "ingested_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False, index=True)       # reddit / youtube / x / quora
    post_id = Column(String(100), unique=True, nullable=False)      # Platform-specific ID
    author = Column(String(200), default="unknown")
    source = Column(String(200), default="")                        # subreddit, channel, etc.
    url = Column(String(500), nullable=False)
    title = Column(String(500), default="")
    text = Column(Text, default="")
    timestamp = Column(DateTime, nullable=True)                     # When the post was published
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tier1_passed = Column(Boolean, default=False)
    tier2_score = Column(Integer, nullable=True)
    tier2_passed = Column(Boolean, default=False)

    # Relationship to draft comments
    drafts = relationship("DraftComment", back_populates="post", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<IngestedPost(id={self.id}, platform='{self.platform}', post_id='{self.post_id}')>"


class DraftComment(Base):
    """AI-generated comment awaiting human review."""
    __tablename__ = "draft_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("ingested_posts.id"), nullable=False)
    matched_scheme = Column(String(200), default="")                # BCI scheme name
    intent_score = Column(Integer, default=0)                       # 0-100
    scheme_relevance = Column(Float, default=0.0)                   # 0.0-1.0
    draft_text = Column(Text, nullable=False)
    status = Column(String(20), default="pending", index=True)      # pending / queued / posted / rejected / failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    posted_at = Column(DateTime, nullable=True)
    posted_url = Column(String(500), nullable=True)

    # Relationship back to post
    post = relationship("IngestedPost", back_populates="drafts")

    def __repr__(self):
        return f"<DraftComment(id={self.id}, status='{self.status}', post_id={self.post_id})>"


class PipelineRun(Base):
    """Tracks each ingestion pipeline run for metrics."""
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False, index=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    posts_fetched = Column(Integer, default=0)
    posts_filtered = Column(Integer, default=0)
    drafts_generated = Column(Integer, default=0)
    status = Column(String(20), default="running")                  # running / completed / failed

    def __repr__(self):
        return f"<PipelineRun(id={self.id}, platform='{self.platform}', status='{self.status}')>"


# ── DB Initialization ─────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    import os
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)


# Enable WAL mode for better concurrent read performance with SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
