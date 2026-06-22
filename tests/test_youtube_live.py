"""
Test Script — Verify YouTube ingestion works.

Run this to confirm:
1. API key is valid
2. We can search for finance videos
3. We can fetch comments from videos
4. Comments are normalized correctly
5. 7-day time filter works

Usage:
    python tests/test_youtube_live.py

Before running, make sure you have a .env file with:
    YOUTUBE_API_KEY=...
"""

import sys
import os
from datetime import datetime

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()  # Load .env from project root

from src.ingestion.youtube_ingester import YouTubeIngester


def test_auth():
    """Test 1: Can we initialize and validate the API key?"""
    print("=" * 60)
    print("TEST 1: YouTube API Key Validation")
    print("=" * 60)

    try:
        ingester = YouTubeIngester()
        # Force a minimal API call to verify the key works
        # Search for 1 video — costs 100 units but confirms everything
        videos = ingester._search_videos("mutual fund India", max_results=1)
        print(f"  ✅ API key is valid!")
        print(f"  ✅ Test search returned {len(videos)} video(s)")
        if videos:
            print(f"  ✅ Sample: \"{videos[0]['title'][:70]}\"")
        return ingester
    except ValueError as e:
        print(f"  ❌ Configuration error: {e}")
        return None
    except Exception as e:
        print(f"  ❌ API call FAILED: {e}")
        print()
        print("  Checklist:")
        print("  1. Is YOUTUBE_API_KEY set in .env?")
        print("  2. Is the YouTube Data API v3 enabled in Google Cloud Console?")
        print("  3. Is the API key unrestricted or allowed for youtube.googleapis.com?")
        return None


def test_video_search(ingester):
    """Test 2: Can we search for finance videos?"""
    print()
    print("=" * 60)
    print("TEST 2: Video Search (single query, 'mutual fund India')")
    print("=" * 60)

    videos = ingester._search_videos("mutual fund India", max_results=5)

    print(f"  📊 Videos found: {len(videos)}")
    print()

    for i, video in enumerate(videos, 1):
        print(f"  ── Video {i} ──")
        print(f"  Title:     {video['title'][:80]}")
        print(f"  Channel:   {video['channel_title']}")
        print(f"  Video ID:  {video['video_id']}")
        print(f"  Published: {video['published_at']}")
        print(f"  Desc:      {video['description'][:120]}...")
        print()

    return videos


def test_comment_fetch(ingester, videos):
    """Test 3: Can we fetch comments from a discovered video?"""
    print("=" * 60)
    print("TEST 3: Comment Fetch (from first discovered video)")
    print("=" * 60)

    if not videos:
        print("  ⚠️  No videos available (previous test returned empty)")
        return []

    target = videos[0]
    print(f"  🎬 Target video: \"{target['title'][:70]}\"")
    print(f"  📺 Channel: {target['channel_title']}")
    print()

    comments = ingester._fetch_comments(target["video_id"], max_results=10)

    print(f"  💬 Comments fetched: {len(comments)}")
    print()

    for i, comment in enumerate(comments[:5], 1):  # Show max 5
        print(f"  ── Comment {i} ──")
        print(f"  Author:    {comment['author']}")
        print(f"  Likes:     {comment['like_count']}")
        print(f"  Published: {comment['published_at']}")
        print(f"  Text:      {comment['text'][:150]}...")
        print()

    if len(comments) > 5:
        print(f"  ... and {len(comments) - 5} more comments")
        print()

    return comments


def test_full_run(ingester):
    """Test 4: Full multi-query run with a single query group."""
    print("=" * 60)
    print("TEST 4: Full Pipeline Run (single query group, limit 3 videos)")
    print("=" * 60)

    # Use just one query group to keep quota usage minimal
    ingester.search_groups = ["mutual fund India | SIP invest"]

    posts = ingester.fetch_posts_sync(
        limit=10,        # Max 10 comments per video
        max_videos=3,    # Only look at 3 videos
    )

    print(f"  📊 Total normalized comments: {len(posts)}")
    print()

    # Group by video for display
    by_video = {}
    for post in posts:
        vid = post.get("video_title", "Unknown")
        by_video.setdefault(vid, []).append(post)

    for vid_title, vid_posts in by_video.items():
        print(f"  📁 Video: \"{vid_title[:65]}\"")
        print(f"     Source: {vid_posts[0]['source']}")
        for post in vid_posts[:3]:  # Show max 3 per video
            text_preview = post["text"].split("Commenter Question: ")[-1][:80]
            print(f"     • [{post['score']:>3}👍] {post['author']}: {text_preview}")
        if len(vid_posts) > 3:
            print(f"     ... and {len(vid_posts) - 3} more")
        print()

    return posts


def test_time_filter(posts):
    """Test 5: Verify all comments are from the last 7 days."""
    print("=" * 60)
    print("TEST 5: Time Window Verification (last 7 days)")
    print("=" * 60)

    if not posts:
        print("  ⚠️  No posts to verify (previous test returned empty)")
        return

    now = datetime.utcnow()
    all_within_window = True

    for post in posts:
        ts = post["timestamp"]
        try:
            post_time = datetime.fromisoformat(ts.replace("+00:00", "").replace("Z", ""))
            age_days = (now - post_time).days

            if age_days > 7:
                print(f"  ❌ Comment {post['post_id'][:20]} is {age_days} days old!")
                all_within_window = False
        except Exception:
            print(f"  ⚠️  Could not parse timestamp: {ts}")

    if all_within_window:
        print(f"  ✅ All {len(posts)} comments are within the 7-day window")

    # Show age distribution
    ages = []
    for post in posts:
        ts = post["timestamp"]
        try:
            post_time = datetime.fromisoformat(ts.replace("+00:00", "").replace("Z", ""))
            age_hours = (now - post_time).total_seconds() / 3600
            ages.append(age_hours)
        except Exception:
            pass

    if ages:
        print(f"  📊 Oldest: {max(ages):.1f} hours ago")
        print(f"  📊 Newest: {min(ages):.1f} hours ago")
        print(f"  📊 Average: {sum(ages)/len(ages):.1f} hours ago")


def test_schema_validation(posts):
    """Test 6: Verify all posts match our expected schema."""
    print()
    print("=" * 60)
    print("TEST 6: Schema Validation")
    print("=" * 60)

    required_fields = ["platform", "post_id", "author", "source", "url", "timestamp", "title", "text"]

    if not posts:
        print("  ⚠️  No posts to validate")
        return

    all_valid = True
    for post in posts:
        for field in required_fields:
            if field not in post:
                print(f"  ❌ Post {post.get('post_id', '?')[:20]} missing field: {field}")
                all_valid = False

        if post["platform"] != "youtube":
            print(f"  ❌ Post {post['post_id'][:20]} has wrong platform: {post['platform']}")
            all_valid = False

    if all_valid:
        print(f"  ✅ All {len(posts)} posts have valid schema")
        print(f"  ✅ Fields verified: {', '.join(required_fields)}")


def estimate_quota():
    """Show estimated quota usage for this test run."""
    print()
    print("=" * 60)
    print("QUOTA ESTIMATE")
    print("=" * 60)
    print("  📊 Test 1 (auth check):      100 units (1 search)")
    print("  📊 Test 2 (video search):     100 units (1 search)")
    print("  📊 Test 3 (comment fetch):      1 unit  (1 commentThreads)")
    print("  📊 Test 4 (full run):         100 units (1 search) + ~3 units (comments)")
    print("  ─────────────────────────────────────────")
    print("  📊 Total estimated:          ~304 units out of 10,000 daily")
    print()


# ── Run all tests ─────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("🚀 Lead-Gen Pipeline — YouTube Ingester Test Suite")
    print("━" * 60)

    estimate_quota()

    # Test 1: API key validation
    ingester = test_auth()
    if not ingester:
        print("\n🛑 Cannot proceed without valid API key. Fix .env and retry.")
        sys.exit(1)

    # Test 2: Video search
    print()
    videos = test_video_search(ingester)

    # Test 3: Comment fetching
    print()
    comments = test_comment_fetch(ingester, videos)

    # Test 4: Full pipeline run
    print()
    posts = test_full_run(ingester)

    # Test 5: Time filter check
    print()
    test_time_filter(posts)

    # Test 6: Schema validation
    test_schema_validation(posts)

    print()
    print("━" * 60)
    print(f"✅ All tests complete. Total comments collected: {len(posts)}")
    print("━" * 60)
