"""
Quora Ingester — Scrapes Quora questions via Playwright headless browser.

Strategy: Seed URL + Related Questions Discovery
- Quora search requires login, so we can't use it
- Instead, we start with a few seed question URLs about Indian finance
- From each seed page, Quora shows 20+ "Related Questions" in the sidebar/feed
- We extract those related question titles + URLs
- This gives us 20-30 diverse, real Quora questions from just 3-5 page loads

Design decisions:
- No proxy needed — we make < 10 page loads total
- No login needed — individual question pages are publicly accessible
- Rate-limited — 3-5 second delays between navigations
- Posting is FULLY MANUAL — dashboard shows draft + question URL,
  human copy-pastes the answer on Quora

Requires: playwright (pip install playwright && playwright install chromium)
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.ingestion.base_ingester import BaseIngester
from src.utils.logger import get_logger

logger = get_logger("quora_ingester")

# ── Seed question URLs (Indian finance topics) ──────────────────
# These are real Quora question pages that generate lots of
# related questions in the sidebar/feed. 3-5 seeds is enough.
DEFAULT_SEED_URLS = [
    "https://www.quora.com/What-are-the-best-mutual-funds-to-invest-in-India",
    "https://www.quora.com/What-is-the-best-home-loan-in-India",
    "https://www.quora.com/Which-is-the-best-credit-card-in-India",
    "https://www.quora.com/Is-SIP-a-good-way-to-invest-in-mutual-funds",
    "https://www.quora.com/What-is-the-best-health-insurance-plan-in-India",
]

# ── Delays (seconds) — respectful scraping ──────────────────────
PAGE_LOAD_WAIT = 5       # Wait for JS to render after navigation
SCROLL_WAIT = 2          # Wait after each scroll for lazy content
BETWEEN_PAGES_WAIT = 4   # Delay between different seed pages


class QuoraIngester(BaseIngester):
    """
    Scrapes Quora questions using Playwright headless browser.

    Flow:
    1. Launch headless Chromium
    2. Navigate to each seed question URL
    3. Scroll to load related questions
    4. Extract related question titles + URLs from the page
    5. Normalize to standard schema
    6. Deduplicate across seeds
    """

    def __init__(
        self,
        seed_urls: Optional[List[str]] = None,
        headless: bool = True,
    ):
        super().__init__(platform_name="quora")
        self.seed_urls = seed_urls or DEFAULT_SEED_URLS
        self.headless = headless
        self._seen_urls: set = set()

    # ── Core: Extract related questions from a question page ─────

    async def _scrape_question_page(
        self, page, seed_url: str, max_questions: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Navigate to a Quora question page, scroll to load related
        questions, and extract their titles + URLs.
        """
        logger.info("navigating_to_seed", url=seed_url)

        try:
            await page.goto(seed_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            logger.warning("page_load_failed", url=seed_url, error=str(e))
            return []

        # Wait for React SPA to render
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # Dismiss login modal if it appears
        await self._dismiss_login_modal(page)

        # Scroll twice to load more related questions
        for _ in range(2):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(SCROLL_WAIT)

        # Also add the seed question itself
        seed_title = await page.title()
        seed_title = seed_title.replace(" - Quora", "").strip()

        questions = []

        # Add the seed question
        current_url = page.url
        if current_url not in self._seen_urls and seed_title and len(seed_title) > 10:
            self._seen_urls.add(current_url)
            questions.append({
                "url": current_url,
                "title": seed_title,
                "is_seed": True,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })

        # Extract all links from the page
        links = await page.query_selector_all("a[href]")

        for link in links:
            if len(questions) >= max_questions:
                break

            try:
                href = await link.get_attribute("href")
                if not href:
                    continue

                # Build full URL
                if href.startswith("/"):
                    full_url = f"https://www.quora.com{href}"
                elif href.startswith("https://www.quora.com/"):
                    full_url = href
                else:
                    continue

                # Clean URL (remove query params)
                full_url = full_url.split("?")[0].split("#")[0]

                # Must be a question URL
                if not self._is_question_url(full_url):
                    continue

                # Skip duplicates
                if full_url in self._seen_urls:
                    continue

                # Get title text
                title = (await link.inner_text()).strip()

                # Filter out noise: "Updated May 2", "Updated 10mo", etc.
                if not title or len(title) < 15:
                    continue
                if title.lower().startswith("updated"):
                    continue
                if title.lower() in ("related", "related questions", "more", "see more"):
                    continue

                self._seen_urls.add(full_url)

                questions.append({
                    "url": full_url,
                    "title": title,
                    "is_seed": False,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })

            except Exception:
                continue

        logger.info(
            "seed_page_scraped",
            seed_url=seed_url[:60],
            questions_found=len(questions),
        )

        return questions

    async def _dismiss_login_modal(self, page) -> None:
        """Try to close Quora's login/signup modal if it pops up."""
        try:
            close_selectors = [
                'button[aria-label="Close"]',
                '.modal_close_button',
            ]
            for selector in close_selectors:
                close_btn = page.locator(selector).first
                if await close_btn.is_visible(timeout=1500):
                    await close_btn.click()
                    await asyncio.sleep(0.5)
                    logger.info("login_modal_dismissed")
                    return
        except Exception:
            pass

    def _is_question_url(self, url: str) -> bool:
        """
        Check if a URL looks like a Quora question page.

        Quora questions: /What-are-the-best-mutual-funds (hyphenated slug)
        Not questions: /profile/..., /topic/..., /answer/..., etc.
        """
        path = url.replace("https://www.quora.com/", "")

        # Exclude known non-question paths
        excluded_prefixes = (
            "profile/", "topic/", "search", "about", "contact",
            "settings", "notifications", "messages", "spaces/",
            "answer/", "unanswered/", "login", "signup", "careers",
            "about/", "press", "privacy", "languages",
        )
        if any(path.lower().startswith(p) for p in excluded_prefixes):
            return False

        # Must have hyphens (question titles are hyphenated) and be long enough
        if "-" not in path or len(path) < 15:
            return False

        # Skip answer links (contain /answer/ in them)
        if "/answer/" in path:
            return False

        return True

    # ── Normalize to standard schema ─────────────────────────────

    def normalize_post(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a scraped Quora question dict into our standard schema."""

        url = raw_data["url"]
        title = raw_data["title"]

        # Generate a deterministic post_id from the URL
        post_id = hashlib.md5(url.encode()).hexdigest()[:12]

        return {
            "platform": "quora",
            "post_id": post_id,
            "author": "quora_user",  # We don't scrape author info
            "source": "Quora",
            "url": url,
            "timestamp": raw_data.get("scraped_at", datetime.now(timezone.utc).isoformat()),
            "title": title,
            "text": title,  # For questions, title IS the content
        }

    # ── Main fetch (async) ───────────────────────────────────────

    async def fetch_posts(
        self,
        query: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Quora questions by visiting seed URLs and discovering
        related questions from each page.

        Launches a Playwright browser, visits each seed, extracts
        related questions, normalizes, and returns.
        """
        from playwright.async_api import async_playwright

        all_questions: List[Dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            for i, seed_url in enumerate(self.seed_urls):
                if len(all_questions) >= limit:
                    break

                remaining = limit - len(all_questions)
                questions = await self._scrape_question_page(
                    page, seed_url, max_questions=remaining
                )
                all_questions.extend(questions)

                # Respectful delay between pages (skip after last)
                if i < len(self.seed_urls) - 1 and len(all_questions) < limit:
                    await asyncio.sleep(BETWEEN_PAGES_WAIT)

            await browser.close()

        # Normalize all questions
        results = [self.normalize_post(q) for q in all_questions]

        logger.info(
            "ingestion_complete",
            platform="quora",
            seeds_visited=min(len(self.seed_urls), len(results)),
            total_questions=len(results),
        )

        return results

    # ── Sync wrapper ─────────────────────────────────────────────

    def fetch_posts_sync(
        self,
        query: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """Synchronous wrapper for fetch_posts."""
        return asyncio.run(self.fetch_posts(query=query, limit=limit))
