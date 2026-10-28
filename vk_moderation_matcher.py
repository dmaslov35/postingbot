#!/usr/bin/env python3
"""Сопоставление кандидатов после модерации без подтверждения авторства."""

from vk_post_identity import extract_post_identity
from vk_post_verifier import text_fingerprint


def match_moderated_post(
    post_url,
    expected_owner_id,
    expected_text,
    actual_text,
):
    result = {
        "matched": False,
        "authorship_verified": False,
        "deletion_allowed": False,
        "reason": "UNKNOWN",
    }

    identity = extract_post_identity(post_url)

    if identity is None:
        result["reason"] = "INVALID_POST_URL"
        return result

    try:
        owner_id = int(expected_owner_id)
    except (TypeError, ValueError):
        result["reason"] = "INVALID_OWNER_ID"
        return result

    if identity["owner_id"] != owner_id:
        result["reason"] = "WRONG_COMMUNITY"
        return result

    expected_hash = text_fingerprint(expected_text)
    actual_hash = text_fingerprint(actual_text)

    if not expected_hash or not actual_hash:
        result["reason"] = "MISSING_TEXT"
        return result

    if expected_hash != actual_hash:
        result["reason"] = "TEXT_MISMATCH"
        return result

    result.update({
        "matched": True,
        "reason": "MATCH_CANDIDATE",
        "vk_post_id": identity["vk_post_id"],
        "post_url": identity["post_url"],
    })

    return result
