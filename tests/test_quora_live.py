"""
Minimal test — Verify Quora ingester works.
Checks: browser launch → seed page load → extract related questions → normalize.

Uses only 1 seed URL to keep it fast and minimal.

Usage:
    python tests/test_quora_live.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.ingestion.quora_ingester import QuoraIngester


if __name__ == "__main__":
    print("\n🚀 Quora Ingester — Minimal Verification\n")

    # Use a single seed URL to keep it fast
    try:
        ingester = QuoraIngester(
            seed_urls=["https://www.quora.com/What-are-the-best-mutual-funds-to-invest-in-India"],
            headless=True,
        )
        print("✅ Ingester initialized")
    except Exception as e:
        print(f"❌ Init failed: {e}")
        sys.exit(1)

    # Fetch questions (sync wrapper) — limit to 15
    try:
        posts = ingester.fetch_posts_sync(limit=15)
        print(f"✅ Scraped {len(posts)} questions")
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Show results
    for i, p in enumerate(posts[:5], 1):
        print(f"\n── Question {i} ──")
        print(f"  Title: {p['title'][:100]}")
        print(f"  URL:   {p['url']}")

    # Schema check
    required = ["platform", "post_id", "author", "source", "url", "timestamp", "title", "text"]
    ok = len(posts) > 0 and all(all(f in p for f in required) for p in posts)
    print(f"\n{'✅' if ok else '❌'} Schema validation: {'PASS' if ok else 'FAIL'}")

    # URL format check
    urls_ok = all("quora.com/" in p["url"] for p in posts) if posts else False
    print(f"{'✅' if urls_ok else '❌'} URL format check: {'PASS' if urls_ok else 'FAIL'}")

    print(f"\n✅ Done. {len(posts)} Quora questions collected (from 1 seed page).")
