"""Поиск опубликованного объявления после модерации.

Только чтение. Совпадение не доказывает авторство.
"""
from vk_moderation_wall_reader import read_wall_posts
from vk_moderation_discovery import discover_moderated_post


def find_moderated_post(vk, owner_id, expected_text, count=100):
    posts = read_wall_posts(vk, owner_id, count=count)

    result = discover_moderated_post(
        posts=posts,
        expected_owner_id=owner_id,
        expected_text=expected_text,
    )

    result["scanned_posts"] = len(posts)
    result["authorship_verified"] = False
    result["deletion_allowed"] = False

    return result
