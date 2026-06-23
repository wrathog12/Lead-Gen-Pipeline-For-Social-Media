"""
Ingest Routes — Orchestrates the full ingestion + processing pipeline.

When triggered (via API or dashboard button), this module:
1. Instantiates the platform ingester(s)
2. Fetches raw posts with rate limiting
3. Runs each post through: Dedup → Tier-1 → Tier-2 → RAG → Generator
4. Saves passing posts and generated drafts to the database
5. Tracks the pipeline run via PipelineRun metrics

The pipeline runs as a background task so the HTTP response returns
immediately. The dashboard can poll /api/ingest/status for progress.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from api.database import get_db, SessionLocal, IngestedPost, DraftComment, PipelineRun

from src.pipeline.deduplicator import Deduplicator
from src.pipeline.tier1_filter import Tier1Filter
from src.pipeline.tier2_validator import Tier2Validator
from src.pipeline.generator import ResponseGenerator
from src.rag.hybrid_search import HybridSearch

from src.utils.logger import get_logger

logger = get_logger("ingest_orchestrator")

router = APIRouter()


# ── Singleton pipeline components (initialized on first use) ─────
# These are heavy objects (LLM clients, FAISS indices, ML models)
# so we create them once and reuse across all pipeline runs.
_deduplicator: Optional[Deduplicator] = None
_tier1: Optional[Tier1Filter] = None
_tier2: Optional[Tier2Validator] = None
_generator: Optional[ResponseGenerator] = None
_rag: Optional[HybridSearch] = None
_init_lock = asyncio.Lock()
_initialized = False

# ── Rate limit delays (seconds between ingester calls) ───────────
RATE_LIMITS = {
    "reddit": 2.0,     # PRAW has built-in limits, but add buffer between queries
    "youtube": 1.0,    # YouTube API is quota-based, delay between comment fetches
    "x": 0.5,          # Single call usually, minimal delay
    "quora": 5.0,      # Playwright scraping — be very respectful
}

# ── Per-platform fetch limits ────────────────────────────────────
PLATFORM_LIMITS = {
    "reddit": 50,
    "youtube": 50,
    "x": 60,       # More tweets to maximize paid credits
    "quora": 30,
}

# ── Track running pipelines ──────────────────────────────────────
_running_pipelines: Dict[str, bool] = {}


async def _ensure_initialized():
    """Lazily initialize all pipeline components on first use."""
    global _deduplicator, _tier1, _tier2, _generator, _rag, _initialized

    async with _init_lock:
        if _initialized:
            return

        logger.info("initializing_pipeline_components")

        _deduplicator = Deduplicator()
        _tier1 = Tier1Filter()
        _tier2 = Tier2Validator()
        _generator = ResponseGenerator()
        _rag = HybridSearch()
        _rag.initialize()

        _initialized = True
        logger.info("pipeline_components_ready")


def _get_ingester(platform: str):
    """
    Instantiate the appropriate ingester for a platform.

    Returns the ingester instance or None if the platform
    can't be initialized (missing API keys, etc.).
    """
    try:
        if platform == "reddit":
            from src.ingestion.reddit_ingester import RedditIngester
            return RedditIngester()
        elif platform == "youtube":
            from src.ingestion.youtube_ingester import YouTubeIngester
            return YouTubeIngester()
        elif platform == "x":
            from src.ingestion.x_ingester import XIngester
            return XIngester()
        elif platform == "quora":
            from src.ingestion.quora_ingester import QuoraIngester
            return QuoraIngester()
        else:
            logger.error("unknown_platform", platform=platform)
            return None
    except Exception as e:
        logger.error(
            "ingester_init_failed",
            platform=platform,
            error=str(e),
        )
        return None


async def _run_pipeline_for_platform(platform: str):
    """
    Full pipeline run for a single platform.

    Steps:
    1. Fetch posts via the platform ingester
    2. For each post: Dedup → Tier-1 → Tier-2 → RAG → Generate → Save
    3. Track metrics in PipelineRun
    """
    if _running_pipelines.get(platform):
        logger.warning("pipeline_already_running", platform=platform)
        return

    _running_pipelines[platform] = True

    # Create a fresh DB session for this background task
    db = SessionLocal()

    # Create pipeline run record
    run = PipelineRun(
        platform=platform,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    posts_fetched = 0
    posts_filtered = 0
    drafts_generated = 0

    try:
        await _ensure_initialized()

        # ── Step 1: Fetch posts ──────────────────────────────────
        logger.info("ingestion_started", platform=platform)

        ingester = _get_ingester(platform)
        if ingester is None:
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Rate limit: add delay before fetching
        rate_delay = RATE_LIMITS.get(platform, 1.0)

        try:
            raw_posts = await ingester.fetch_posts(limit=PLATFORM_LIMITS.get(platform, 25))
        except Exception as e:
            logger.error("fetch_failed", platform=platform, error=str(e))
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        posts_fetched = len(raw_posts)
        logger.info("posts_fetched", platform=platform, count=posts_fetched)

        if not raw_posts:
            run.posts_fetched = 0
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # ── Step 2: Process each post through the pipeline ───────
        tier2_batch = []  # Posts that pass Tier-1, need Tier-2 scoring

        for post_data in raw_posts:
            post_id_str = post_data.get("post_id", "")

            # Rate limit between processing each post
            await asyncio.sleep(rate_delay * 0.1)  # Small delay per post

            # ── Dedup ────────────────────────────────────────────
            if _deduplicator.is_duplicate(post_id_str):
                logger.debug("duplicate_skipped", post_id=post_id_str)
                continue

            # Check if already in DB
            existing = db.query(IngestedPost).filter(
                IngestedPost.post_id == post_id_str
            ).first()
            if existing:
                continue

            # ── Tier-1 Filter ────────────────────────────────────
            text = post_data.get("text", "")

            # X/Twitter bypasses Tier-1 (posts are too short for keyword matching)
            if platform == "x":
                tier1_passed = True
            else:
                tier1_passed = _tier1.passes_filter(text)

            # Save ingested post to DB (even if it doesn't pass filters)
            db_post = IngestedPost(
                platform=platform,
                post_id=post_id_str,
                author=post_data.get("author", "unknown"),
                source=post_data.get("source", ""),
                url=post_data.get("url", ""),
                title=post_data.get("title", ""),
                text=text,
                timestamp=_parse_timestamp(post_data.get("timestamp")),
                tier1_passed=tier1_passed,
            )
            db.add(db_post)
            db.commit()
            db.refresh(db_post)

            if not tier1_passed:
                logger.debug("tier1_dropped", post_id=post_id_str)
                continue

            # Collect for batch Tier-2 scoring
            tier2_batch.append((db_post, post_data))

        # ── Step 3: Tier-2 batch validation ──────────────────────
        if tier2_batch:
            logger.info("tier2_batch_start", count=len(tier2_batch))

            tier2_posts = [
                {
                    "post_id": p_data.get("post_id", ""),
                    "platform": platform,
                    "text": p_data.get("text", ""),
                }
                for _, p_data in tier2_batch
            ]

            tier2_results = await _tier2.validate_batch(tier2_posts)

            # ── Step 4: RAG + Generation for passing posts ───────

            # 4a. Update all Tier-2 scores in DB and collect passing posts
            generation_inputs = []  # list of (db_post, post_data, score)

            for (db_post, post_data), result in zip(tier2_batch, tier2_results):
                score = result.get("score", 0)
                passes = result.get("passes", False)

                # Update DB with Tier-2 results
                db_post.tier2_score = score
                db_post.tier2_passed = passes
                db.commit()

                if not passes:
                    logger.info(
                        "tier2_dropped",
                        post_id=db_post.post_id,
                        score=score,
                    )
                    continue

                posts_filtered += 1
                generation_inputs.append((db_post, post_data, score))

            # 4b. Run RAG search + LLM generation concurrently
            #     Semaphore limits parallel Gemini API calls to avoid
            #     transient rate-limit errors on pay-as-you-go.
            if generation_inputs:
                logger.info(
                    "generation_batch_start",
                    count=len(generation_inputs),
                )
                gen_semaphore = asyncio.Semaphore(5)

                async def _rag_and_generate(db_post, post_data, score):
                    """Single RAG + generation task (runs under semaphore)."""
                    async with gen_semaphore:
                        # RAG: Find best matching scheme
                        try:
                            schemes = _rag.search(post_data.get("text", ""), top_k=1)
                            if not schemes:
                                logger.warning("no_scheme_match", post_id=db_post.post_id)
                                return None
                            best_scheme = schemes[0]
                        except Exception as e:
                            logger.error(
                                "rag_search_failed",
                                post_id=db_post.post_id,
                                error=str(e),
                            )
                            return None

                        # Generate comment via Gemini
                        try:
                            draft_text = await _generator.generate_response(
                                post=post_data,
                                scheme=best_scheme,
                                platform=platform,
                            )
                        except Exception as e:
                            logger.error(
                                "generation_failed",
                                post_id=db_post.post_id,
                                error=str(e),
                            )
                            return None

                        if not draft_text:
                            logger.info("generation_skipped", post_id=db_post.post_id)
                            return None

                        return (db_post, best_scheme, score, draft_text)

                # Fire all generation tasks concurrently
                tasks = [
                    _rag_and_generate(db_post, post_data, score)
                    for db_post, post_data, score in generation_inputs
                ]
                gen_results = await asyncio.gather(*tasks)

                # 4c. Save generated drafts to DB (sequential — safe for SQLite)
                for result in gen_results:
                    if result is None:
                        continue

                    db_post, best_scheme, score, draft_text = result

                    draft = DraftComment(
                        post_id=db_post.id,
                        matched_scheme=best_scheme.get("scheme_name", ""),
                        intent_score=score,
                        scheme_relevance=best_scheme.get("relevance_score", 0.0),
                        draft_text=draft_text,
                        status="pending",
                    )
                    db.add(draft)
                    db.commit()

                    drafts_generated += 1
                    logger.info(
                        "draft_saved",
                        post_id=db_post.post_id,
                        scheme=best_scheme.get("scheme_name", ""),
                        draft_preview=draft_text[:60],
                    )

        # ── Update pipeline run metrics ──────────────────────────
        run.posts_fetched = posts_fetched
        run.posts_filtered = posts_filtered
        run.drafts_generated = drafts_generated
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "pipeline_complete",
            platform=platform,
            fetched=posts_fetched,
            filtered=posts_filtered,
            drafts=drafts_generated,
        )

    except Exception as e:
        logger.error("pipeline_error", platform=platform, error=str(e))
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        _running_pipelines[platform] = False
        db.close()


def _parse_timestamp(ts) -> Optional[datetime]:
    """Parse a timestamp string into a datetime, or return None."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # Handle ISO format strings
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    return None


# ═══════════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════════


@router.post("/run/{platform}")
async def trigger_ingestion(platform: str, background_tasks: BackgroundTasks):
    """
    Trigger an ingestion run for a specific platform.

    The pipeline runs as a background task — this endpoint returns
    immediately with a status message.
    """
    valid_platforms = {"reddit", "youtube", "x", "quora"}

    if platform == "all":
        # Trigger all platforms
        for p in valid_platforms:
            if _running_pipelines.get(p):
                continue
            background_tasks.add_task(_run_pipeline_for_platform, p)
        return {
            "message": "Ingestion triggered for all platforms",
            "platforms": list(valid_platforms),
            "status": "started",
        }

    if platform not in valid_platforms:
        return {"message": f"Unknown platform: {platform}", "status": "error"}

    if _running_pipelines.get(platform):
        return {
            "message": f"Pipeline already running for {platform}",
            "status": "already_running",
        }

    background_tasks.add_task(_run_pipeline_for_platform, platform)

    return {
        "message": f"Ingestion triggered for {platform}",
        "platform": platform,
        "status": "started",
    }


@router.get("/status")
async def ingestion_status():
    """Get the status of all ingestion pipelines."""
    return {
        "running": {
            platform: is_running
            for platform, is_running in _running_pipelines.items()
        },
        "initialized": _initialized,
    }
