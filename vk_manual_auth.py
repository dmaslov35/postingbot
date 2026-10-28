import time
from playwright.sync_api import sync_playwright

PROFILE = "/opt/vkbot/VKBotChromeServer"
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        executable_path=CHROME,
        headless=False,
        viewport=None,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--start-maximized",
        ],
    )

    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    page.goto(
        "https://vk.ru/feed",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("URL:", page.url, flush=True)
    print("TITLE:", page.title(), flush=True)
    print("BROWSER READY - NO TIME LIMIT", flush=True)

    try:
        while True:
            time.sleep(60)
            print(
                "URL:", page.url,
                "TITLE:", page.title(),
                flush=True
            )
    except KeyboardInterrupt:
        print("Closing browser...", flush=True)

    ctx.close()
