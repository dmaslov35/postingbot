"""Чтение стены VK для поиска объявлений после модерации.

Не публикует и не удаляет записи.
"""
from pathlib import Path

STOP = Path("/opt/vkbot/runtime/production.stop")


def read_wall_posts(vk, owner_id, count=100):
    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REQUIRED")

    if type(owner_id) is not int or owner_id >= 0:
        raise ValueError("INVALID_COMMUNITY_OWNER")

    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("INVALID_COUNT")

    response = vk.wall.get(
        owner_id=owner_id,
        count=count,
        offset=0,
    )

    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REMOVED")

    if not isinstance(response, dict):
        raise RuntimeError("INVALID_WALL_RESPONSE")

    items = response.get("items")

    if not isinstance(items, list):
        raise RuntimeError("INVALID_WALL_ITEMS")

    result = []

    for item in items:
        if not isinstance(item, dict):
            continue

        if type(item.get("owner_id")) is not int:
            continue

        if item["owner_id"] != owner_id:
            continue

        post_id = item.get("id")

        if type(post_id) is not int or post_id <= 0:
            continue

        result.append({
            "post_url": f"https://vk.ru/wall{owner_id}_{post_id}",
            "text": item.get("text") or "",
        })

    return result
