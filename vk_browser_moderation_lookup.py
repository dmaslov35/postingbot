"""Поиск объявления после модерации через уже открытую страницу VK.

Только чтение. Не подтверждает авторство и не разрешает удаление.
"""

from pathlib import Path

from vk_browser_wall_reader import read_visible_wall_posts
from vk_moderation_discovery import discover_moderated_post


STOP = Path("/opt/vkbot/runtime/production.stop")


def find_moderated_post_in_browser(page, owner_id, expected_text):
    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REQUIRED")

    if type(owner_id) is not int or owner_id >= 0:
        raise ValueError("INVALID_COMMUNITY_OWNER")

    if not isinstance(expected_text, str) or not expected_text.strip():
        raise ValueError("INVALID_EXPECTED_TEXT")

    posts = read_visible_wall_posts(page, owner_id)

    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REMOVED")

    result = discover_moderated_post(
        posts=posts,
        expected_owner_id=owner_id,
        expected_text=expected_text,
    )

    result["scanned_posts"] = len(posts)
    result["source"] = "BROWSER"
    result["authorship_verified"] = False
    result["deletion_allowed"] = False

    return result
