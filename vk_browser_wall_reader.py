"""Безопасное чтение видимых записей стены VK через Playwright.

Не публикует, не удаляет, не подтверждает авторство.
"""

import re

from vk_post_identity import extract_post_identity


class BrowserWallBlocked(RuntimeError):
    pass


def read_visible_wall_posts(page, expected_owner_id):
    if type(expected_owner_id) is not int or expected_owner_id >= 0:
        raise ValueError("INVALID_COMMUNITY_OWNER")

    from vk_worker_production import detect_block

    if detect_block(page):
        raise BrowserWallBlocked("VK_VERIFICATION")

    raw = page.locator('a[href*="wall"]').evaluate_all(
        """nodes => nodes.slice(0, 200).map(a => {
            const container = a.closest(
                '[data-post-id], [id^="post-"], article'
            );
            return {
                href: a.href,
                text: container ? container.innerText : null
            };
        })"""
    )

    if detect_block(page):
        raise BrowserWallBlocked("VK_VERIFICATION")

    posts = {}

    for item in raw:
        if not isinstance(item, dict):
            continue

        identity = extract_post_identity(item.get("href"))

        if not identity:
            continue

        post_id = identity["vk_post_id"]
        match = re.fullmatch(r"(-\d+)_(\d+)", str(post_id))

        if not match or int(match.group(1)) != expected_owner_id:
            continue

        text = item.get("text")

        if not isinstance(text, str) or not text.strip():
            continue

        posts[post_id] = {
            "post_url": identity["post_url"],
            "text": text.strip()[:10000],
        }

    return list(posts.values())
