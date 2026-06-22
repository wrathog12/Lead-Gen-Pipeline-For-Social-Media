"""
Tier-2 Validator — LLM-based semantic intent scoring.

Uses Gemini Flash to score whether a social media post is genuinely
seeking financial advice (score 0-100). Posts scoring >= threshold
pass to the RAG + generation stage.

Design decisions:
  - ONE post per LLM call (not batched) for scoring accuracy
  - asyncio.gather with semaphore for concurrent throughput
  - Platform-aware prompt (X gets lenient threshold due to brevity)
  - Structured JSON response for reliable parsing
  - Graceful fallback: if LLM call fails, post is DROPPED (safe default)

Score >= 85: User is seeking help → Pass to RAG + Generation
Score <  85: Complaint, news, joke, rant → Drop to protect brand
"""

import json
import asyncio
from typing import Dict, Any, List, Optional

from google import genai
from google.genai import types

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("tier2_validator")

# ── Concurrency control ─────────────────────────────────────────
# Max simultaneous Gemini calls to stay within rate limits.
# Free tier: ~60 RPM, Paid: ~1000 RPM. 5 concurrent is safe for both.
DEFAULT_CONCURRENCY = 5

# ── Platform-specific threshold overrides ────────────────────────
# X/Twitter posts are inherently terse (≤280 chars), so a strict 85
# threshold drops too many valid leads. We lower it for X only.
PLATFORM_THRESHOLDS = {
    "reddit": 85,
    "youtube": 85,
    "quora": 85,
    "x": 75,
}

# ── System instruction ───────────────────────────────────────────
SYSTEM_INSTRUCTION = """You are a financial intent classifier working for an Indian bank's social media monitoring system.

Your SOLE job is to determine if a social media post is written by someone who is **genuinely seeking financial advice, product recommendations, or guidance** — the kind of person who would benefit from a helpful, relevant suggestion about a banking or investment product.

You are NOT a content moderator. You are a LEAD QUALIFIER. You are looking for purchase intent or advice-seeking behavior.

CRITICAL RULES:
1. You MUST respond with ONLY a valid JSON object. No markdown, no explanation outside the JSON.
2. The JSON must have exactly two keys: "score" (integer 0-100) and "reasoning" (string, 1-2 sentences).
3. Be STRICT. Most social media posts are noise. Only high-intent posts should score above 85.
4. Consider the PLATFORM context — a Reddit post has full paragraphs, a tweet has ≤280 characters."""

# ── Scoring rubric (embedded in user prompt) ─────────────────────
SCORING_RUBRIC = """
SCORING RUBRIC (follow strictly):

90-100: STRONG LEAD — User is explicitly asking for product recommendations or comparisons.
        Examples: "Which mutual fund should I start SIP in?", "Best credit card for travel in India?",
                  "Should I go for ELSS or PPF for tax saving?"

85-89:  MODERATE LEAD — User is seeking general financial guidance where a product suggestion fits naturally.
        Examples: "How should I plan my investments for retirement?", "What's a good way to save tax?",
                  "I have 10 lakh to invest, what should I do?"

70-84:  WEAK / AMBIGUOUS — Discussing finance but NOT seeking advice. Sharing experience, stating facts,
        or asking a question that doesn't invite product suggestions.
        Examples: "My SIP gave 15% returns last year", "RBI increased repo rate today",
                  "How does compound interest work?"

40-69:  NOISE — Tangentially financial but clearly not seeking product advice.
        Examples: "Bank app is down again", "Got scammed by a fake loan call",
                  "Why do banks charge so many fees?"

0-39:   IRRELEVANT — Not financial, a joke, meme, complaint about service, or spam.
        Examples: "lol", "This meme about taxes is hilarious", "ICICI customer service sucks"

IMPORTANT EDGE CASES:
- Complaints about a specific bank's SERVICE (app down, bad support) → score 20-40. They are NOT leads.
- News articles or market commentary shared without a question → score 50-70. NOT leads.
- "Is X worth it?" or "Should I get X?" → score 90+. These ARE leads.
- Posts comparing two products → score 90+. These ARE leads.
- Posts asking "how does X work?" about a financial concept → score 75-84. Educational, not a lead.
"""


def _build_user_prompt(text: str, platform: str) -> str:
    """
    Build the scoring prompt for a single post.

    Includes platform context so the LLM understands the format
    constraints (e.g., tweets are short, Reddit posts are long).
    """
    platform_context = {
        "reddit": (
            "This is a Reddit post. It may include a title and body text. "
            "Reddit posts tend to be detailed and often explicitly ask for recommendations."
        ),
        "youtube": (
            "This is a YouTube comment, shown with its parent video's title and description for context. "
            "The comment itself may be short, but judge intent using BOTH the comment text AND the video topic."
        ),
        "x": (
            "This is a tweet from X (Twitter). Tweets are limited to 280 characters, so intent signals "
            "may be compressed or implicit. Be slightly more lenient — a short question about finance "
            "in a tweet carries the same weight as a full Reddit paragraph."
        ),
        "quora": (
            "This is a Quora question title. Quora questions are almost always advice-seeking by nature, "
            "but verify the question is about financial products/services, not just general knowledge."
        ),
    }

    context = platform_context.get(platform, "This is a social media post.")

    return f"""{SCORING_RUBRIC}

PLATFORM: {platform.upper()}
CONTEXT: {context}

--- POST TEXT START ---
{text.strip()[:2000]}
--- POST TEXT END ---

Score this post. Respond with ONLY a JSON object: {{"score": <int 0-100>, "reasoning": "<1-2 sentences>"}}"""


class Tier2Validator:
    """LLM-powered intent validation using Gemini Flash."""

    def __init__(
        self,
        threshold: int = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        model_name: str = "gemini-2.5-flash",
    ):
        # Default threshold from settings, can be overridden
        self.default_threshold = threshold or settings.tier2_threshold
        self.concurrency = concurrency
        self.model_name = model_name
        self._semaphore = asyncio.Semaphore(concurrency)

        # Initialize Gemini client
        api_key = settings.gemini_api_key
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY not configured. "
                "Set it in .env or pass a valid key."
            )
        self.client = genai.Client(api_key=api_key)

        logger.info(
            "tier2_initialized",
            model=self.model_name,
            default_threshold=self.default_threshold,
            concurrency=self.concurrency,
        )

    def _get_threshold(self, platform: str) -> int:
        """Get the intent score threshold for a given platform."""
        return PLATFORM_THRESHOLDS.get(platform, self.default_threshold)

    def _parse_response(self, raw_text: str) -> Dict[str, Any]:
        """
        Parse the LLM's JSON response, handling common edge cases:
        - Markdown code fences wrapping the JSON
        - Extra whitespace or newlines
        - Malformed responses (returns a safe default)
        """
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
            # Remove closing fence
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            parsed = json.loads(text)
            score = int(parsed.get("score", 0))
            reasoning = str(parsed.get("reasoning", "No reasoning provided"))

            # Clamp score to valid range
            score = max(0, min(100, score))

            return {"score": score, "reasoning": reasoning}

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(
                "response_parse_failed",
                raw_text=raw_text[:200],
                error=str(e),
            )
            # Safe default: treat unparseable responses as noise (drop the post)
            return {
                "score": 0,
                "reasoning": f"Failed to parse LLM response: {str(e)[:100]}",
            }

    async def validate_intent(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score a single post's intent using Gemini Flash.

        Args:
            post: Dict with at minimum 'text', 'platform', and 'post_id' keys.

        Returns:
            {
                "passes": bool,
                "score": int (0-100),
                "reasoning": str,
                "post_id": str,
                "platform": str,
                "threshold_used": int
            }
        """
        post_id = post.get("post_id", "unknown")
        platform = post.get("platform", "unknown")
        text = post.get("text", "")
        threshold = self._get_threshold(platform)

        if not text.strip():
            logger.warning("empty_post_text", post_id=post_id)
            return {
                "passes": False,
                "score": 0,
                "reasoning": "Post text is empty",
                "post_id": post_id,
                "platform": platform,
                "threshold_used": threshold,
            }

        # Rate-limit via semaphore
        async with self._semaphore:
            try:
                user_prompt = _build_user_prompt(text, platform)

                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1,           # Low temperature for consistent scoring
                        max_output_tokens=200,      # JSON response is small
                    ),
                )

                raw_text = response.text or ""
                parsed = self._parse_response(raw_text)

                score = parsed["score"]
                reasoning = parsed["reasoning"]
                passes = score >= threshold

                logger.info(
                    "post_scored",
                    post_id=post_id,
                    platform=platform,
                    score=score,
                    threshold=threshold,
                    passes=passes,
                    reasoning=reasoning[:80],
                )

                return {
                    "passes": passes,
                    "score": score,
                    "reasoning": reasoning,
                    "post_id": post_id,
                    "platform": platform,
                    "threshold_used": threshold,
                }

            except Exception as e:
                logger.error(
                    "tier2_call_failed",
                    post_id=post_id,
                    platform=platform,
                    error=str(e),
                )
                # Safe default: drop the post on failure
                return {
                    "passes": False,
                    "score": 0,
                    "reasoning": f"LLM call failed: {str(e)[:150]}",
                    "post_id": post_id,
                    "platform": platform,
                    "threshold_used": threshold,
                }

    async def validate_batch(
        self, posts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Score multiple posts concurrently using asyncio.gather.

        Respects the semaphore concurrency limit (default 5 in-flight).
        Returns results in the SAME ORDER as the input posts.

        Args:
            posts: List of post dicts, each with 'text', 'platform', 'post_id'.

        Returns:
            List of result dicts (same length as input), each with
            'passes', 'score', 'reasoning', 'post_id', 'platform', 'threshold_used'.
        """
        if not posts:
            return []

        logger.info("batch_validation_started", total_posts=len(posts))

        # Fire all calls concurrently (semaphore controls actual parallelism)
        tasks = [self.validate_intent(post) for post in posts]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Tally results
        passed = sum(1 for r in results if r["passes"])
        failed = len(results) - passed

        logger.info(
            "batch_validation_complete",
            total=len(results),
            passed=passed,
            dropped=failed,
        )

        return results
