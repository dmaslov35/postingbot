import hashlib
import re
from datetime import datetime, timezone

from vk_post_identity import (
    extract_post_identity,
    matches_community,
)

def normalize_text(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()

def text_fingerprint(value):
    normalized = normalize_text(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def verify_publication(
    post_url,
    expected_owner_id,
    expected_text,
    actual_text,
    published_at,
    attempt_started_at,
    author_verified=False,
):
    """Проверяет предоставленные доказательства публикации.

    Не обращается к VK и не подтверждает происхождение данных.
    """
    identity = extract_post_identity(post_url)

    if not identity:
        return {"verified": False, "reason": "INVALID_POST_URL"}

    if not matches_community(identity, expected_owner_id):
        return {"verified": False, "reason": "WRONG_COMMUNITY"}

    expected_hash = text_fingerprint(expected_text)
    actual_hash = text_fingerprint(actual_text)

    if not expected_hash or expected_hash != actual_hash:
        return {"verified": False, "reason": "TEXT_MISMATCH"}

    if not author_verified:
        return {"verified": False, "reason": "AUTHOR_NOT_VERIFIED"}

    try:
        published = datetime.fromisoformat(
            published_at.replace("Z", "+00:00")
        )
        attempted = datetime.fromisoformat(
            attempt_started_at.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError, TypeError):
        return {"verified": False, "reason": "INVALID_TIME"}

    if published.tzinfo is None or attempted.tzinfo is None:
        return {"verified": False, "reason": "TIMEZONE_REQUIRED"}

    published = published.astimezone(timezone.utc)
    attempted = attempted.astimezone(timezone.utc)

    delta = (published - attempted).total_seconds()

    if delta < -120 or delta > 900:
        return {"verified": False, "reason": "TIME_MISMATCH"}

    return {
        "verified": True,
        "reason": "VERIFIED",
        "vk_post_id": identity["vk_post_id"],
        "post_url": identity["post_url"],
        "published_at": published.isoformat(),
        "text_hash": expected_hash,
    }
