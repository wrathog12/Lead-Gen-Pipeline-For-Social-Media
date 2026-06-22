"""
Minimal test — Verify X ingester works.
Just checks: auth → fetch → normalize. That's it.

Usage:
    python tests/test_x_live.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.ingestion.x_ingester import XIngester


if __name__ == "__main__":
    print("\n🚀 X Ingester — Minimal Verification\n")

    try:
        ingester = XIngester()
        print("✅ Bearer token loaded")
    except ValueError as e:
        print(f"❌ Config error: {e}")
        sys.exit(1)

    # Fetch a small batch (10 tweets to save cost on test run)
    try:
        posts = ingester.fetch_posts_sync(limit=10)
        print(f"✅ Fetched {len(posts)} tweets")
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        sys.exit(1)

    # Show a few results
    for i, p in enumerate(posts[:3], 1):
        print(f"\n── Tweet {i} ──")
        print(f"  Author:  {p['author']}")
        print(f"  URL:     {p['url']}")
        print(f"  Likes:   {p['score']}")
        print(f"  Text:    {p['text'][:120]}...")

    # Schema check
    required = ["platform", "post_id", "author", "source", "url", "timestamp", "title", "text"]
    ok = all(all(f in p for f in required) for p in posts)
    print(f"\n{'✅' if ok else '❌'} Schema validation: {'PASS' if ok else 'FAIL'}")
    print(f"\n✅ Done. Cost: ~${len(posts) * 0.005:.3f}")
