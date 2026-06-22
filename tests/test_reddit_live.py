"""
Test Script — Verify Reddit ingestion works.

Run this to confirm:
1. OAuth2 credentials are valid
2. We can search subreddits
3. Posts are normalized correctly
4. 7-day time filter works

Usage:
    python tests/test_reddit_live.py

Before running, make sure you have a .env file with:
    REDDIT_CLIENT_ID=...
    REDDIT_CLIENT_SECRET=...
    REDDIT_USERNAME=...
    REDDIT_PASSWORD=...
    REDDIT_USER_AGENT=LeadGenPoC/0.1 by <your_username>
"""

import sys
import os
from datetime import datetime

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()  # Load .env from project root

from src.ingestion.reddit_ingester import RedditIngester


def test_auth():
    """Test 1: Can we authenticate with Reddit?"""
    print("=" * 60)
    print("TEST 1: Reddit Authentication")
    print("=" * 60)

    try:
        ingester = RedditIngester()
        # PRAW lazily connects, so we force a simple API call
        user = ingester.reddit.user.me()
        print(f"  ✅ Authenticated as: u/{user.name}")
        print(f"  ✅ Account karma: {user.link_karma + user.comment_karma}")
        return ingester
    except Exception as e:
        print(f"  ❌ Authentication FAILED: {e}")
        print()
        print("  Checklist:")
        print("  1. Do you have a .env file in the project root?")
        print("  2. Is REDDIT_CLIENT_ID set correctly?")
        print("  3. Is your app type 'script' (not 'web app')?")
        print("  4. Is your password correct?")
        return None


def test_single_query(ingester):
    """Test 2: Can we search a single subreddit with one query?"""
    print()
    print("=" * 60)
    print("TEST 2: Single Query Search (r/IndiaInvestments, 'mutual fund')")
    print("=" * 60)

    # Override to search just one subreddit with one query
    ingester.subreddits = ["IndiaInvestments"]
    posts = ingester.fetch_posts_sync(query="mutual fund", limit=5)

    print(f"  📊 Posts found: {len(posts)}")
    print()

    for i, post in enumerate(posts, 1):
        print(f"  ── Post {i} ──")
        print(f"  Title:     {post['title'][:80]}")
        print(f"  Author:    u/{post['author']}")
        print(f"  Subreddit: r/{post['source']}")
        print(f"  URL:       {post['url']}")
        print(f"  Timestamp: {post['timestamp']}")
        print(f"  Score:     {post['score']} upvotes")
        print(f"  Comments:  {post['num_comments']}")
        print(f"  Text:      {post['text'][:150]}...")
        print()

    return posts


def test_multi_query(ingester):
    """Test 3: Full run across multiple subreddits and queries."""
    print("=" * 60)
    print("TEST 3: Full Multi-Query Run (all subreddits, top 3 queries)")
    print("=" * 60)

    # Reset subreddits and use a subset of queries for speed
    ingester.subreddits = [
        "IndiaInvestments",
        "personalfinanceindia",
    ]

    test_queries = ["mutual fund", "home loan", "credit card"]
    ingester.search_queries = test_queries

    posts = ingester.fetch_posts_sync(limit=5)

    print(f"  📊 Total unique posts: {len(posts)}")
    print()

    # Group by subreddit for display
    by_subreddit = {}
    for post in posts:
        sub = post["source"]
        by_subreddit.setdefault(sub, []).append(post)

    for sub, sub_posts in by_subreddit.items():
        print(f"  📁 r/{sub}: {len(sub_posts)} posts")
        for post in sub_posts[:3]:  # Show max 3 per sub
            print(f"     • [{post['score']:>3}⬆] {post['title'][:70]}")
        if len(sub_posts) > 3:
            print(f"     ... and {len(sub_posts) - 3} more")
        print()

    return posts


def test_time_filter(posts):
    """Test 4: Verify all posts are from the last 7 days."""
    print("=" * 60)
    print("TEST 4: Time Window Verification (last 7 days)")
    print("=" * 60)

    if not posts:
        print("  ⚠️  No posts to verify (previous test returned empty)")
        return

    now = datetime.utcnow()
    all_within_window = True

    for post in posts:
        post_time = datetime.fromisoformat(post["timestamp"].replace("+00:00", ""))
        age_days = (now - post_time).days

        if age_days > 7:
            print(f"  ❌ Post {post['post_id']} is {age_days} days old!")
            all_within_window = False

    if all_within_window:
        print(f"  ✅ All {len(posts)} posts are within the 7-day window")

    # Show age distribution
    ages = []
    for post in posts:
        post_time = datetime.fromisoformat(post["timestamp"].replace("+00:00", ""))
        age_hours = (now - post_time).total_seconds() / 3600
        ages.append(age_hours)

    if ages:
        print(f"  📊 Oldest: {max(ages):.1f} hours ago")
        print(f"  📊 Newest: {min(ages):.1f} hours ago")
        print(f"  📊 Average: {sum(ages)/len(ages):.1f} hours ago")


def test_schema_validation(posts):
    """Test 5: Verify all posts match our expected schema."""
    print()
    print("=" * 60)
    print("TEST 5: Schema Validation")
    print("=" * 60)

    required_fields = ["platform", "post_id", "author", "source", "url", "timestamp", "title", "text"]

    if not posts:
        print("  ⚠️  No posts to validate")
        return

    all_valid = True
    for post in posts:
        for field in required_fields:
            if field not in post:
                print(f"  ❌ Post {post.get('post_id', '?')} missing field: {field}")
                all_valid = False

        if post["platform"] != "reddit":
            print(f"  ❌ Post {post['post_id']} has wrong platform: {post['platform']}")
            all_valid = False

    if all_valid:
        print(f"  ✅ All {len(posts)} posts have valid schema")
        print(f"  ✅ Fields verified: {', '.join(required_fields)}")


# ── Run all tests ─────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("🚀 Lead-Gen Pipeline — Reddit Ingester Test Suite")
    print("━" * 60)
    print()

    # Test 1: Authentication
    ingester = test_auth()
    if not ingester:
        print("\n🛑 Cannot proceed without authentication. Fix .env and retry.")
        sys.exit(1)

    # Test 2: Single query
    print()
    posts = test_single_query(ingester)

    # Test 3: Multi-query run
    print()
    all_posts = test_multi_query(ingester)

    # Test 4: Time filter check
    print()
    combined = posts + all_posts
    # Deduplicate by post_id for the check
    unique = {p["post_id"]: p for p in combined}
    test_time_filter(list(unique.values()))

    # Test 5: Schema validation
    test_schema_validation(list(unique.values()))

    print()
    print("━" * 60)
    print(f"✅ All tests complete. Total unique posts collected: {len(unique)}")
    print("━" * 60)
