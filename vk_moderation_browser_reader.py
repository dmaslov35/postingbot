from pathlib import Path
from urllib.parse import urlparse
import re
import sqlite3

BASE = Path("/opt/vkbot")
STOP = BASE / "runtime/production.stop"
ACCOUNTS_DB = BASE / "vk_multi_account.sqlite3"

WALL_PATTERN = re.compile(r"^/wall(-\d+)_(\d+)/?$")


def require_safe_mode():
    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REQUIRED")


def parse_post_url(url):
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("HTTPS_REQUIRED")

    if parsed.hostname not in ("vk.com", "vk.ru", "m.vk.com", "m.vk.ru"):
        raise ValueError("INVALID_VK_DOMAIN")

    if parsed.username or parsed.password or parsed.port:
        raise ValueError("INVALID_URL_AUTHORITY")

    match = WALL_PATTERN.fullmatch(parsed.path)

    if not match:
        raise ValueError("INVALID_POST_URL")

    return {
        "owner_id": int(match.group(1)),
        "post_id": int(match.group(2)),
        "vk_post_id": f"{match.group(1)}_{match.group(2)}",
        "post_url": f"https://vk.com/wall{match.group(1)}_{match.group(2)}",
    }


def get_original_profile_paths():
    require_safe_mode()

    connection = sqlite3.connect(
        f"file:{ACCOUNTS_DB}?mode=ro",
        uri=True,
    )

    try:
        rows = connection.execute(
            "SELECT profile_dir FROM accounts WHERE profile_dir IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()

    return [
        Path(row[0]).resolve()
        for row in rows
        if row[0]
    ]


def validate_isolated_profile(profile_dir):
    require_safe_mode()

    profile = Path(profile_dir).resolve()

    if not profile.is_dir():
        raise ValueError("ISOLATED_PROFILE_NOT_FOUND")

    for original in get_original_profile_paths():
        if (
            profile == original
            or original in profile.parents
            or profile in original.parents
        ):
            raise ValueError("PRODUCTION_PROFILE_FORBIDDEN")

    return profile


def read_post(post_url, isolated_profile_dir):
    require_safe_mode()

    identity = parse_post_url(post_url)
    profile = validate_isolated_profile(isolated_profile_dir)

    return {
        "status": "BROWSER_READER_NOT_ACTIVATED",
        "vk_post_id": identity["vk_post_id"],
        "post_url": identity["post_url"],
        "isolated_profile_validated": True,
        "authorship_verified": False,
        "deletion_allowed": False,
    }


if __name__ == "__main__":
    require_safe_mode()

    test = parse_post_url(
        "https://vk.ru/wall-240781173_9"
    )

    assert test["vk_post_id"] == "-240781173_9"

    for invalid in (
        "https://example.com/wall-240781173_9",
        "http://vk.com/wall-240781173_9",
        "https://vk.com/wall-240781173_9/extra",
    ):
        try:
            parse_post_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("INVALID_URL_ACCEPTED")

    print("=== VK MODERATION BROWSER READER ===")
    print("MODULE_CREATED: YES")
    print("URL_VALIDATION: PASS")
    print("PROFILE_PROTECTION: ENABLED")
    print("BROWSER_LAUNCH: DISABLED")
    print("VK_REQUESTS: 0")
    print("PUBLICATIONS: 0")
    print("DELETIONS: 0")
    print("PASS: PRODUCTION_STOP_PRESERVED")
