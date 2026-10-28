"""Проверка параметров wall.post без хранения секретов."""

from urllib.parse import parse_qs


def match_wall_post_request(request, expected_owner_id, expected_text):
    result = {
        "matched": False,
        "reason": "INVALID_REQUEST",
    }

    try:
        if request.method.upper() != "POST":
            return result

        url = request.url
        from urllib.parse import urlparse
        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.vk.com"
            or parsed.path.rstrip("/") != "/method/wall.post"
        ):
            return result

        body = request.post_data

        if not isinstance(body, str):
            result["reason"] = "NO_REQUEST_BODY"
            return result

        params = parse_qs(body, keep_blank_values=True)

        owners = params.get("owner_id", [])
        messages = params.get("message", [])

        if len(owners) != 1 or len(messages) != 1:
            result["reason"] = "MISSING_OR_DUPLICATE_FIELDS"
            return result

        if owners[0] != str(int(expected_owner_id)):
            result["reason"] = "WRONG_COMMUNITY"
            return result

        if messages[0] != expected_text:
            result["reason"] = "WRONG_TEXT"
            return result

        return {
            "matched": True,
            "reason": "REQUEST_FIELDS_MATCH",
        }

    except Exception:
        return result
