
"""Разбор ответа VK API wall.post без сетевых запросов."""

from urllib.parse import urlparse


def parse_wall_post_response(url, method, status, payload):
    """Извлекает post_id только из успешного ответа wall.post."""

    result = {
        "recognized": False,
        "post_id": None,
        "verified": False,
        "reason": "NOT_WALL_POST",
    }

    parsed = urlparse(str(url))
    host = (parsed.hostname or "").lower()

    if (
        parsed.scheme != "https"
        or host != "api.vk.com"
        or parsed.path.rstrip("/") != "/method/wall.post"
        or str(method).upper() != "POST"
    ):
        return result

    result["recognized"] = True
    result["reason"] = "INVALID_RESPONSE"

    if int(status) != 200 or not isinstance(payload, dict):
        return result

    if payload.get("error"):
        result["reason"] = "VK_API_ERROR"
        return result

    response = payload.get("response")

    if not isinstance(response, dict):
        return result

    post_id = response.get("post_id")

    if (
        isinstance(post_id, bool)
        or not isinstance(post_id, int)
        or post_id <= 0
    ):
        return result

    result["post_id"] = post_id
    result["reason"] = "POST_ID_EXTRACTED"

    # Сам post_id ещё не доказывает, что ответ принадлежит
    # конкретному заданию и авторизованному аккаунту.
    result["verified"] = False

    return result
