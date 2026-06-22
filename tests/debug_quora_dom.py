"""
Debug — Test extracting related questions + answers from a direct Quora URL.
Since Quora search requires login, we pivot to:
1. Seed with known question URLs
2. Extract "Related Questions" from each page to discover more
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        url = "https://www.quora.com/What-are-the-best-mutual-funds-to-invest-in-India"
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)

        # Dismiss modal if present
        try:
            close_btn = page.locator('button[aria-label="Close"]').first
            if await close_btn.is_visible(timeout=2000):
                await close_btn.click()
                await asyncio.sleep(1)
                print("Dismissed modal")
        except:
            pass

        # Scroll a couple times to load more content
        for _ in range(2):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        print(f"\nCurrent URL: {page.url}")

        # Find ALL links and categorize them
        links = await page.query_selector_all('a[href]')
        print(f"Total links: {len(links)}")

        question_links = []
        seen = set()
        for link in links:
            href = await link.get_attribute("href") or ""
            text = ""
            try:
                text = (await link.inner_text()).strip()
            except:
                continue
            
            # Normalize
            if href.startswith("/"):
                full = f"https://www.quora.com{href}"
            elif href.startswith("https://www.quora.com/"):
                full = href
            else:
                continue
            
            path = full.replace("https://www.quora.com/", "").split("?")[0].split("#")[0]
            
            # Skip non-question paths
            skip = ("profile/", "topic/", "search", "about", "contact",
                    "settings", "notifications", "messages", "spaces/",
                    "answer/", "unanswered/", "login", "signup", "careers",
                    "about/", "press", "privacy")
            if any(path.lower().startswith(s) for s in skip):
                continue
            
            # Must have hyphen (question slug) and reasonable length
            if "-" not in path or len(path) < 10:
                continue
            
            if full in seen:
                continue
            seen.add(full)
            
            if len(text) > 10:
                question_links.append({"url": full, "text": text[:120]})

        print(f"\nDiscovered question-like links: {len(question_links)}")
        for i, ql in enumerate(question_links[:20]):
            print(f"  [{i+1}] {ql['text']}")
            print(f"      {ql['url']}")

        await browser.close()

asyncio.run(main())
