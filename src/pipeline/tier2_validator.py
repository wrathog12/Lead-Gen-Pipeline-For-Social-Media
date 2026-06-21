"""
Tier-2 Validator — LLM-based semantic intent scoring.

Uses Gemini Flash to score whether a post is genuinely seeking
financial advice (score 0-100). Posts scoring >= threshold pass
to the RAG + generation stage.

Score >= 85: User is seeking help → Pass
Score <  85: Complaint, news, joke, rant → Drop
"""

from typing import Dict, Any, Optional


class Tier2Validator:
    """LLM-powered intent validation using Gemini Flash."""

    def __init__(self, threshold: int = 85):
        self.threshold = threshold
        # TODO: Initialize Gemini client

    async def validate_intent(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score the post's intent using LLM.

        Returns:
            {
                "passes": bool,
                "score": int (0-100),
                "reasoning": str,
                "post_id": str
            }
        """
        # TODO: Implement Gemini Flash call with structured prompt
        # Prompt should ask:
        # 1. Is the user genuinely seeking financial advice/recommendations?
        # 2. Is this an appropriate context to suggest a product?
        # 3. Score 0-100 on advice-seeking intent
        raise NotImplementedError("Tier-2 validation not yet implemented")

    def _build_prompt(self, text: str, platform: str) -> str:
        """Build the intent-scoring prompt for the LLM."""
        # TODO: Platform-aware prompt construction
        raise NotImplementedError
