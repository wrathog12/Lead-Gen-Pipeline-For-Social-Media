"""
Tier-1 Filter — Fast keyword/regex-based noise elimination.

Drops ~80% of irrelevant posts with zero LLM compute cost.
Uses a curated set of financial trigger keywords and regex patterns.
If a post contains none of these, it is immediately discarded.
"""

import re
from typing import List, Set


# Financial intent trigger keywords (case-insensitive)
FINANCIAL_KEYWORDS: Set[str] = {
    # Products
    "mutual fund", "mf", "sip", "loan", "credit card", "deposit",
    "fixed deposit", "fd", "rd", "recurring deposit", "insurance",
    "term plan", "lic", "nps", "ppf", "elss",
    # Actions
    "invest", "investing", "investment", "save", "saving", "tax",
    "tax saving", "returns", "interest rate", "emi", "premium",
    # Advice seeking
    "recommend", "suggestion", "which is best", "should i",
    "compare", "better option", "good fund", "best fund",
    # Brand (censored for PoC)
    "bci", "prudential", "bluechip", "value fund",
}

# Regex patterns for financial queries
FINANCIAL_PATTERNS = [
    r"\b\d+\s*(?:lakh|lac|cr|crore|k)\b",           # Amount mentions
    r"\b\d+\s*%\s*(?:return|interest|rate)\b",        # Percentage + financial term
    r"\bwhere\s+(?:to|should)\s+(?:i\s+)?invest\b",  # "Where to invest"
    r"\bbest\s+(?:mutual\s+)?fund\b",                 # "Best fund"
]


class Tier1Filter:
    """Fast keyword-based filter to eliminate noise before LLM processing."""

    def __init__(self, extra_keywords: List[str] = None):
        self.keywords = FINANCIAL_KEYWORDS.copy()
        if extra_keywords:
            self.keywords.update(kw.lower() for kw in extra_keywords)

        self.patterns = [re.compile(p, re.IGNORECASE) for p in FINANCIAL_PATTERNS]

    def passes_filter(self, text: str) -> bool:
        """
        Returns True if the post contains financial intent signals.
        Returns False if the post should be discarded (noise).
        """
        text_lower = text.lower()

        # Check keyword presence
        for keyword in self.keywords:
            if keyword in text_lower:
                return True

        # Check regex patterns
        for pattern in self.patterns:
            if pattern.search(text):
                return True

        return False

    def get_matched_keywords(self, text: str) -> List[str]:
        """Returns list of matched keywords for logging/debugging."""
        text_lower = text.lower()
        return [kw for kw in self.keywords if kw in text_lower]
