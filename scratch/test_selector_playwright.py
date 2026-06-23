import asyncio
import sys
from playwright.async_api import async_playwright

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            print("SUCCESS: Browser launched on", asyncio.get_event_loop())
            await browser.close()
    except Exception as e:
        print("FAILED: Browser launch failed on", asyncio.get_event_loop(), "Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
