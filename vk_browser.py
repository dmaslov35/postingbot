#!/usr/bin/env python3

from pathlib import Path
from playwright.sync_api import sync_playwright

VK_URL = "https://vk.com/"
SCREENSHOT = Path("/opt/vkbot/vk_probe.png")


def main():
    print("VK BROWSER PROBE")
    print("MODE: READ-ONLY")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="ru-RU",
        )

        page = context.new_page()

        print("Opening VK...")

        response = page.goto(
            VK_URL,
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_timeout(3000)

        print("HTTP STATUS:", response.status if response else "NO RESPONSE")
        print("FINAL URL:", page.url)
        print("TITLE:", page.title())

        body = page.locator("body").inner_text(timeout=10000)
        body_compact = " ".join(body.split())

        print()
        print("BODY PREVIEW:")
        print(body_compact[:1000])

        page.screenshot(
            path=str(SCREENSHOT),
            full_page=False,
        )

        print()
        print("SCREENSHOT:", SCREENSHOT)
        print("SCREENSHOT SAVED: YES")

        context.close()
        browser.close()

    print()
    print("VK OPENED: YES")
    print("LOGIN DATA ENTERED: NO")
    print("BUTTONS CLICKED: NO")
    print("POSTS CREATED: NO")
    print("VK API USED: NO")


if __name__ == "__main__":
    main()
