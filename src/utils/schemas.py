"""
Schemas — Pydantic models for data validation across the pipeline.

Defines the standard shapes for posts, schemes, draft comments,
and review queue entries. All pipeline components use these models.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class Platform(str, Enum):
    """Supported social media platforms."""
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    X = "x"
    QUORA = "quora"


class ReviewStatus(str, Enum):
    """Status of a draft comment in the review queue."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    FAILED = "failed"


class IngestedPost(BaseModel):
    """Standardized post schema from any platform."""
    platform: Platform
    post_id: str
    author: str
    source: str = ""            # subreddit, channel name, etc.
    url: str
    timestamp: datetime
    title: str = ""
    text: str


class SchemeMetadata(BaseModel):
    """Metadata for a BCI financial scheme."""
    category: str               # "Mutual Fund", "Loan", "Credit Card", "Deposit"
    risk_level: str = ""
    sub_category: str = ""


class BCIScheme(BaseModel):
    """A single BCI financial product/scheme."""
    scheme_id: str
    scheme_name: str
    metadata: SchemeMetadata
    bm25_keywords: List[str] = []
    vector_description: str


class DraftComment(BaseModel):
    """A generated comment awaiting human review."""
    id: Optional[int] = None
    post: IngestedPost
    matched_scheme: BCIScheme
    intent_score: int = Field(ge=0, le=100)
    scheme_relevance_score: float = Field(ge=0.0, le=1.0)
    draft_text: str
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    posted_url: Optional[str] = None
    error_message: Optional[str] = None
