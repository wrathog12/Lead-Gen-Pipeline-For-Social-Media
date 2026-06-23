import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from src.ingestion.quora_ingester import QuoraIngester

async def main():
    print("Event loop:", asyncio.get_event_loop())
    ingester = QuoraIngester(
        seed_urls=["https://www.quora.com/What-are-the-best-mutual-funds-to-invest-in-India"],
        headless=True,
    )
    posts = await ingester.fetch_posts(limit=5)
    print(f"Fetch completed: found {len(posts)} posts.")

if __name__ == "__main__":
    if sys.platform == "win32":
        # Force ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
