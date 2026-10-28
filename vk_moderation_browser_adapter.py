
"""Безопасный адаптер чтения стены VK через существующую страницу Playwright."""

from urllib.parse import urlsplit

from vk_moderation_wall_reader import STOP


class BrowserWall:
    def __init__(self, page):
        self.page = page

    def get(self, owner_id, count=100, offset=0):
        if not STOP.is_file():
            raise RuntimeError("PRODUCTION_STOP_REQUIRED")

        if type(owner_id) is not int or owner_id >= 0:
            raise ValueError("INVALID_COMMUNITY_OWNER")

        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("INVALID_COUNT")

        if offset != 0:
            raise ValueError("UNSUPPORTED_OFFSET")

        url = f"https://vk.ru/wall{owner_id}"

        # VK may load wall cards long after DOMContentLoaded.
        # Retry only when the cards have not appeared.
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        for attempt in range(2):
            if not STOP.is_file():
                raise RuntimeError("PRODUCTION_STOP_REMOVED")

            self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            if not STOP.is_file():
                raise RuntimeError("PRODUCTION_STOP_REMOVED")

            current = urlsplit(self.page.url)
            if (
                current.netloc not in ("vk.ru", "vk.com")
                or current.path.rstrip("/") != f"/wall{owner_id}"
            ):
                raise RuntimeError(
                    "UNEXPECTED_VK_REDIRECT:"
                    + (
                        "AUTH"
                        if current.path.startswith(("/login", "/auth"))
                        else "CHALLENGE"
                        if any(x in current.path.lower() for x in (
                            "challenge", "captcha", "verify"
                        ))
                        else "OTHER"
                    )
                )

            try:
                self.page.locator(
                    'div[data-post-id]'
                ).first.wait_for(
                    state="attached",
                    timeout=30000,
                )
                break
            except PlaywrightTimeoutError as exc:
                if not STOP.is_file():
                    raise RuntimeError("PRODUCTION_STOP_REMOVED") from exc
                if attempt == 1:
                    raise RuntimeError("VK_WALL_NOT_LOADED") from exc

        if not STOP.is_file():
            raise RuntimeError("PRODUCTION_STOP_REMOVED")

        posts = self.page.locator(
            'div[data-post-id]'
        )

        items = []

        for index in range(min(posts.count(), count)):
            post = posts.nth(index)
            raw_id = post.get_attribute("data-post-id")

            if not isinstance(raw_id, str):
                continue

            expected_prefix = f"{owner_id}_"

            if not raw_id.startswith(expected_prefix):
                continue

            post_id_text = raw_id[len(expected_prefix):]

            if not post_id_text.isascii() or not post_id_text.isdecimal():
                continue

            post_id = int(post_id_text)

            if post_id <= 0:
                continue

            text = None

            for selector in (
                ".wall_post_text",
                ".post_text",
                "[data-testid='post_text']",
            ):
                elements = post.locator(selector)

                if elements.count() == 0:
                    continue

                candidate_text = elements.first.inner_text(
                    timeout=3000,
                )

                if candidate_text.strip():
                    text = candidate_text
                    break

            if text is None:
                # VK may render post text without legacy CSS classes.
                # Read only the text of the matching post card.
                candidate_text = post.inner_text(timeout=3000).strip()
                if candidate_text:
                    text = candidate_text

            if text is None:
                continue

            items.append({
                "owner_id": owner_id,
                "id": post_id,
                "text": text,
            })

        return {"items": items}


class BrowserVKClient:
    def __init__(self, page):
        self.wall = BrowserWall(page)
