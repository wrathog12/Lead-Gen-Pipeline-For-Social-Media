"""
Generator — LLM-powered grounded response generation.

Generates platform-appropriate comments using retrieved scheme data.
Strictly grounded: ONLY uses data from the RAG-retrieved scheme,
never the LLM's parametric knowledge, to avoid hallucination.

Design decisions:
  - SEPARATE prompt template per platform (Reddit, YouTube, X, Quora)
  - Each prompt enforces platform-specific tone, length, and formatting
  - Single Gemini Flash call per comment (not batched)
  - Strict grounding: scheme's vector_description and metadata ONLY
  - Regulatory compliance: no return promises, no guarantees
  - Human-sounding: helpful, not corporate or salesy
"""

import json
from typing import Dict, Any, Optional

from google import genai
from google.genai import types

from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger("generator")


# ── Shared grounding rules (injected into ALL platform prompts) ──
GROUNDING_RULES = """
ABSOLUTE RULES (violating ANY of these is a critical failure):

1. ONLY USE THE PROVIDED SCHEME DATA. Do NOT invent features, returns, interest rates,
   or any details not explicitly stated in the scheme description below. If the scheme
   description doesn't mention a number, you don't mention a number.

2. NEVER promise returns, guarantees, or specific performance. No phrases like
   "guaranteed returns", "you will get X%", "assured growth", etc.

3. NEVER mention competitor banks or products by name (HDFC, SBI, Axis, etc.).

4. NEVER sound like an advertisement. You are a helpful community member who happens
   to know about this product. You are NOT a bank employee posting an ad.

5. Include a soft call-to-action like "check out details on icicibank.com" or
   "you can explore more at icicibank.com" — never pushy, never salesy.

6. NEVER use phrases like "I recommend", "You should definitely", or anything that
   constitutes financial advice. Use softer language: "you might want to look at",
   "worth exploring", "could be a good fit".

7. Sound HUMAN. Use natural, conversational language. No corporate jargon.
   No bullet points. No numbered lists. Just flowing, genuine text.

8. Do NOT start with "Great question!" or any generic opener. Jump straight
   into the helpful content.
"""


def _format_scheme_context(scheme: Dict[str, Any]) -> str:
    """
    Format scheme data into a clean context block for the prompt.
    This is the ONLY source of truth the LLM should use.
    """
    meta = scheme.get("metadata", {})

    return f"""--- SCHEME DATA (your ONLY source of truth) ---
Scheme Name: {scheme.get('scheme_name', 'Unknown')}
Category: {meta.get('category', 'Unknown')}
Sub-Category: {meta.get('sub_category', '')}
Risk Level: {meta.get('risk_level', '')}
Target Audience: {meta.get('target_demographic', '')}
Description: {scheme.get('vector_description', '')}
--- END SCHEME DATA ---"""


# ═══════════════════════════════════════════════════════════════════
# Platform-specific prompt builders
# ═══════════════════════════════════════════════════════════════════


def _build_reddit_prompt(post_text: str, scheme: Dict[str, Any]) -> tuple[str, str]:
    """
    Build system instruction + user prompt for a Reddit comment.

    Reddit style: Conversational, 2-3 sentences, slightly detailed.
    Reddit users value substance and authenticity. They instantly
    detect and downvote corporate-sounding responses.
    """
    system = f"""You are a knowledgeable member of Indian personal finance communities on Reddit.
You genuinely enjoy helping people with financial questions. You write like a real Redditor —
casual, direct, and helpful. You are NOT a bank representative.

Your task: Write a Reddit comment replying to the post below, naturally weaving in
the provided financial product where it genuinely fits the user's question.

LENGTH: 2-3 sentences. No more. Redditors skim — keep it tight.
TONE: Conversational, like you're chatting with a friend about money.
FORMAT: Plain text. No markdown headers, no bullet points, no bold.

{GROUNDING_RULES}"""

    user = f"""{_format_scheme_context(scheme)}

--- USER'S REDDIT POST ---
{post_text.strip()[:1500]}
--- END POST ---

Write your Reddit comment reply (2-3 sentences, conversational, grounded in scheme data only):"""

    return system, user


def _build_youtube_prompt(post_text: str, scheme: Dict[str, Any]) -> tuple[str, str]:
    """
    Build system instruction + user prompt for a YouTube comment.

    YouTube style: Casual, brief, friendly. ~500 chars max.
    YouTube comments are informal — people use emojis sparingly
    and keep things short. Context includes the video topic.
    """
    system = f"""You are a helpful viewer replying to a comment on a YouTube finance video.
You write like a regular YouTube commenter — casual, brief, and friendly.
You are NOT a bank representative or a financial advisor.

Your task: Write a YouTube comment reply that naturally mentions the provided
financial product where it genuinely fits what the commenter is asking about.

LENGTH: 1-2 sentences. Keep it under 500 characters total.
TONE: Casual and friendly, like replying to another viewer.
FORMAT: Plain text. You may use ONE emoji at the end if it feels natural (👍 or 📈).
        No hashtags, no links in the text (just mention "icicibank.com" as text).

{GROUNDING_RULES}"""

    user = f"""{_format_scheme_context(scheme)}

--- YOUTUBE COMMENT (includes video context) ---
{post_text.strip()[:1500]}
--- END COMMENT ---

Write your YouTube comment reply (1-2 sentences, casual, under 500 characters):"""

    return system, user


def _build_x_prompt(post_text: str, scheme: Dict[str, Any]) -> tuple[str, str]:
    """
    Build system instruction + user prompt for an X (Twitter) reply.

    X style: Ultra-concise. HARD LIMIT of 250 characters (leaving room
    for the @mention). Every word must earn its place.
    """
    system = f"""You are replying to a tweet about personal finance in India.
You write like a real X/Twitter user — extremely concise, no fluff whatsoever.
You are NOT a bank representative.

Your task: Write a tweet-length reply that mentions the provided financial product
in a natural, helpful way.

LENGTH: MAXIMUM 250 CHARACTERS. This is a HARD LIMIT. Count carefully.
        If you cannot make a meaningful reply under 250 characters, respond with
        exactly the word "SKIP" and nothing else.
TONE: Direct and punchy. Every word must earn its place.
FORMAT: Plain text only. No hashtags. No emojis. No links. Just mention
        "icicibank.com" as plain text if there's room.

{GROUNDING_RULES}

CRITICAL: Your response MUST be under 250 characters. Count them."""

    user = f"""{_format_scheme_context(scheme)}

--- TWEET ---
{post_text.strip()[:300]}
--- END TWEET ---

Write your X reply (UNDER 250 characters, punchy, grounded in scheme data only):"""

    return system, user


def _build_quora_prompt(post_text: str, scheme: Dict[str, Any]) -> tuple[str, str]:
    """
    Build system instruction + user prompt for a Quora answer snippet.

    Quora style: Slightly more authoritative and educational, 3-4 sentences.
    Quora users expect well-reasoned answers, not quick quips.
    The comment serves as a helpful snippet, not a full answer.
    """
    system = f"""You are a knowledgeable person answering a question on Quora about personal finance in India.
You write in a clear, educational tone — like someone who has genuine experience with
financial products. You are NOT a bank representative or financial advisor.

Your task: Write a short, helpful answer snippet that naturally mentions the provided
financial product where it genuinely addresses the question.

LENGTH: 3-4 sentences. Enough to be genuinely helpful, not so long that people scroll past.
TONE: Informative and composed. Slightly more formal than Reddit, but still warm.
FORMAT: Plain text. No bullet points, no numbered lists. Flowing prose.

{GROUNDING_RULES}"""

    user = f"""{_format_scheme_context(scheme)}

--- QUORA QUESTION ---
{post_text.strip()[:1500]}
--- END QUESTION ---

Write your Quora answer snippet (3-4 sentences, educational, grounded in scheme data only):"""

    return system, user


# ═══════════════════════════════════════════════════════════════════
# Generator class
# ═══════════════════════════════════════════════════════════════════

# Map platform names to their prompt builders
_PROMPT_BUILDERS = {
    "reddit": _build_reddit_prompt,
    "youtube": _build_youtube_prompt,
    "x": _build_x_prompt,
    "quora": _build_quora_prompt,
}


class ResponseGenerator:
    """Generates grounded, platform-appropriate draft comments."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name

        # Initialize Gemini client
        api_key = settings.gemini_api_key
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY not configured. "
                "Set it in .env or pass a valid key."
            )
        self.client = genai.Client(api_key=api_key)

        logger.info("generator_initialized", model=self.model_name)

    async def generate_response(
        self,
        post: Dict[str, Any],
        scheme: Dict[str, Any],
        platform: str,
    ) -> Optional[str]:
        """
        Generate a draft comment grounded in the retrieved scheme data.

        Uses a platform-specific prompt to produce a comment that matches
        the tone, length, and style of the target platform.

        Args:
            post: The original user post dict (must have 'text' key).
            scheme: The matched BCI scheme from RAG (full scheme dict).
            platform: Target platform — "reddit", "youtube", "x", or "quora".

        Returns:
            Draft comment string ready for human review.
            Returns None if:
              - The LLM returns "SKIP" (X post too constrained)
              - The LLM call fails
              - The platform is unknown
        """
        post_text = post.get("text", "")
        post_id = post.get("post_id", "unknown")

        if not post_text.strip():
            logger.warning("empty_post_text", post_id=post_id)
            return None

        # Get the right prompt builder
        builder = _PROMPT_BUILDERS.get(platform)
        if builder is None:
            logger.error("unknown_platform", platform=platform, post_id=post_id)
            return None

        # Build platform-specific prompts
        system_instruction, user_prompt = builder(post_text, scheme)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,         # Slightly creative for natural-sounding comments
                    max_output_tokens=300,    # Generous ceiling, prompt constrains actual length
                ),
            )

            draft = (response.text or "").strip()

            # Handle SKIP response (X posts that can't fit under 250 chars)
            if draft.upper() == "SKIP":
                logger.info(
                    "generation_skipped",
                    post_id=post_id,
                    platform=platform,
                    reason="LLM returned SKIP — post too constrained for X reply",
                )
                return None

            # Validate X character limit (belt and suspenders)
            if platform == "x" and len(draft) > 280:
                logger.warning(
                    "x_over_limit",
                    post_id=post_id,
                    length=len(draft),
                    draft=draft[:100],
                )
                # Truncate at last complete sentence under 280
                draft = self._truncate_for_x(draft)
                if draft is None:
                    return None

            # Strip any quotes the LLM may have wrapped the response in
            if draft.startswith('"') and draft.endswith('"'):
                draft = draft[1:-1]

            logger.info(
                "comment_generated",
                post_id=post_id,
                platform=platform,
                scheme=scheme.get("scheme_name", "unknown"),
                length=len(draft),
                preview=draft[:80],
            )

            return draft

        except Exception as e:
            logger.error(
                "generation_failed",
                post_id=post_id,
                platform=platform,
                error=str(e),
            )
            return None

    def _truncate_for_x(self, text: str, limit: int = 275) -> Optional[str]:
        """
        Truncate a too-long X comment to fit under the character limit.

        Tries to cut at the last sentence boundary under the limit.
        If no sentence boundary exists, truncates at the last word
        boundary and adds "…".

        Returns None if the text can't be meaningfully truncated.
        """
        if len(text) <= limit:
            return text

        # Try to find last sentence end (. ! ?) within the limit
        truncated = text[:limit]

        for end_char in [".", "!", "?"]:
            last_pos = truncated.rfind(end_char)
            if last_pos > 50:  # Must keep at least 50 chars to be meaningful
                return truncated[:last_pos + 1]

        # Fallback: cut at last space and add ellipsis
        last_space = truncated.rfind(" ")
        if last_space > 50:
            return truncated[:last_space] + "…"

        # Can't meaningfully truncate
        return None
