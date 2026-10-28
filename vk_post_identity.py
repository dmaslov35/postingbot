import re
from urllib.parse import urlparse, parse_qs

POST_PATTERN = re.compile(r"^wall(-?\d+)_(\d+)$")

def extract_post_identity(url):
    if not isinstance(url, str):
        return None

    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        return None

    if parsed.hostname not in ("vk.com", "www.vk.com", "m.vk.com", "vk.ru", "www.vk.ru", "m.vk.ru"):
        return None

    candidates = [parsed.path.strip("/").split("/")[-1]]

    query = parse_qs(parsed.query)
    candidates.extend(query.get("w", []))

    for candidate in candidates:
        match = POST_PATTERN.fullmatch(candidate)

        if match:
            owner_id = int(match.group(1))
            post_id = int(match.group(2))

            if owner_id == 0 or post_id <= 0:
                continue

            identity = f"{owner_id}_{post_id}"

            return {
                "owner_id": owner_id,
                "post_id": post_id,
                "vk_post_id": identity,
                "post_url": f"https://vk.com/wall{identity}"
            }

    return None

def matches_community(identity, expected_owner_id):
    if not identity:
        return False

    try:
        return identity["owner_id"] == int(expected_owner_id)
    except (TypeError, ValueError, KeyError):
        return False
