
"""Проверка происхождения публикации.

Модуль не обращается к VK и не выполняет публикаций.
Самостоятельно не подтверждает авторство записи.
"""

from vk_post_identity import extract_post_identity


def assess_publication_proof(
    queue_id,
    account_id,
    group_owner_id,
    expected_text,
    candidate_url,
    evidence=None,
):
    """Оценивает доказательства, не выдавая ложное подтверждение."""

    identity = extract_post_identity(candidate_url)

    if identity is None:
        return {
            "verified": False,
            "reason": "INVALID_POST_URL",
        }

    try:
        expected_owner = int(group_owner_id)
    except (TypeError, ValueError):
        return {
            "verified": False,
            "reason": "INVALID_GROUP_OWNER",
        }

    if identity["owner_id"] != expected_owner:
        return {
            "verified": False,
            "reason": "WRONG_COMMUNITY",
        }

    if not queue_id or not account_id or not expected_text:
        return {
            "verified": False,
            "reason": "INCOMPLETE_JOB",
        }

    # Кандидат, найденный на странице, не является доказательством
    # успешного выполнения операции публикации.
    #
    # Даже если внешний вызывающий код передаст
    # {"verified": True}, мы не доверяем этому полю.
    #
    # Подтверждение станет возможным только после внедрения
    # проверяемого источника происхождения записи.
    return {
        "verified": False,
        "reason": "TRUSTED_ORIGIN_NOT_AVAILABLE",
        "vk_post_id": identity["vk_post_id"],
        "post_url": identity["post_url"],
        "queue_id": queue_id,
        "account_id": account_id,
    }
