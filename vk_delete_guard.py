"""Защита автоматического удаления публикаций VK.

Не обращается к VK и не выполняет удаление.
"""

from vk_post_identity import extract_post_identity


def assess_delete_permission(publication, proof=None):
    """Проверяет возможность удаления. По умолчанию запрещает."""

    result = {
        "allowed": False,
        "reason": "DELETE_NOT_AUTHORIZED",
    }

    if not isinstance(publication, dict):
        result["reason"] = "INVALID_PUBLICATION"
        return result

    if publication.get("state") not in ("PUBLISHED", "DELETE_DUE"):
        result["reason"] = "INVALID_STATE"
        return result

    identity = extract_post_identity(publication.get("post_url"))

    if identity is None:
        result["reason"] = "INVALID_POST_URL"
        return result

    if identity["vk_post_id"] != publication.get("vk_post_id"):
        result["reason"] = "POST_ID_MISMATCH"
        return result

    # Проверяем принадлежность записи сообществу.
    # Короткие адреса без подтвержденного ID не принимаем.
    import re
    from urllib.parse import urlparse

    group_url = publication.get("group_url")
    if not isinstance(group_url, str):
        result["reason"] = "INVALID_GROUP_URL"
        return result

    parsed_group = urlparse(group_url.strip())
    if (
        parsed_group.scheme != "https"
        or parsed_group.hostname not in ("vk.com", "www.vk.com", "m.vk.com", "vk.ru", "www.vk.ru", "m.vk.ru")
    ):
        result["reason"] = "INVALID_GROUP_URL"
        return result

    match = re.fullmatch(
        r"(?:club|public)([0-9]+)",
        parsed_group.path.strip("/")
    )

    if match is None:
        result["reason"] = "UNRESOLVED_GROUP_ID"
        return result

    if identity["owner_id"] != -int(match.group(1)):
        result["reason"] = "COMMUNITY_MISMATCH"
        return result

    if not publication.get("account_id"):
        result["reason"] = "MISSING_ACCOUNT"
        return result

    if not publication.get("delete_after"):
        result["reason"] = "MISSING_DELETE_TIME"
        return result

    # Внешние флаги proof={"verified": True} не считаются
    # достоверным доказательством авторства.
    # Разрешение будет реализовано только после появления
    # независимой проверки через доверенный источник VK.
    result["reason"] = "TRUSTED_AUTHORSHIP_PROOF_REQUIRED"
    return result
