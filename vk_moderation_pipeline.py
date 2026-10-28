#!/usr/bin/env python3
"""Мониторинг публикаций VK: проверка, события, защита от повторов.

Не выполняет сетевых запросов самостоятельно.
Не отправляет сообщения и не изменяет базы данных.
"""

import hashlib
from pathlib import Path

from vk_moderation_api_reader import read_vk_post
from vk_moderation_monitor import evaluate_candidate
from vk_post_identity import extract_post_identity


STOP = Path("/opt/vkbot/runtime/production.stop")


def require_safe_mode():
    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REQUIRED")


def make_event_key(registry_id, vk_post_id, event_type):
    raw = f"{registry_id}|{vk_post_id}|{event_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_notification(record, candidate):
    require_safe_mode()

    if not isinstance(record, dict):
        raise ValueError("INVALID_RECORD")

    if not isinstance(candidate, dict):
        raise ValueError("INVALID_CANDIDATE")

    required = (
        "id",
        "post_url",
        "expected_owner_id",
        "expected_text",
    )

    if any(key not in record for key in required):
        raise ValueError("MISSING_RECORD_FIELDS")

    if not candidate.get("found"):
        return None

    result = evaluate_candidate(
        post_url=candidate["post_url"],
        expected_owner_id=record["expected_owner_id"],
        expected_text=record["expected_text"],
        actual_text=candidate["actual_text"],
    )

    if not result["matched"]:
        return None

    assert result["authorship_verified"] is False
    assert result["deletion_allowed"] is False

    from vk_moderation_api_reader import assess_vk_authorship

    identity = extract_post_identity(candidate["post_url"])

    authorship_reason = "ACCOUNT_ID_UNAVAILABLE"

    if identity is not None:
        expected_user_id = record.get("verified_vk_user_id")

        if expected_user_id is None:
            account_id = record.get("account_id")

            if type(account_id) is int and account_id > 0:
                from vk_multi_account import get_verified_vk_user_id
                expected_user_id = get_verified_vk_user_id(account_id)

        if type(expected_user_id) is int and expected_user_id > 0:
            assessment = assess_vk_authorship(
                {
                    "owner_id": identity["owner_id"],
                    "id": identity["post_id"],
                    "from_id": candidate.get("from_id"),
                    "signer_id": candidate.get("signer_id"),
                    "created_by": candidate.get("created_by"),
                },
                expected_user_id,
                record["expected_owner_id"],
                identity["post_id"],
            )
            authorship_reason = assessment["reason"]

    event_key = make_event_key(
        record["id"],
        candidate["vk_post_id"],
        "MODERATION_CANDIDATE",
    )

    message = (
        "🔎 Найдена публикация для проверки\n\n"
        f"Запись реестра: {record['id']}\n"
        f"Ссылка: {candidate['post_url']}\n\n"
        "Текст объявления совпадает.\n"
        f"Проверка авторства: {authorship_reason}\n"
        "Авторство бота НЕ подтверждено.\n"
        "Автоматическое удаление ЗАПРЕЩЕНО."
    )

    return {
        "event_key": event_key,
        "event_type": "MODERATION_CANDIDATE",
        "registry_id": record["id"],
        "post_url": candidate["post_url"],
        "message": message,
        "authorship_verified": False,
        "deletion_allowed": False,
    }


def collect_notifications(records, candidates, delivered_keys=None):
    require_safe_mode()

    if delivered_keys is None:
        delivered_keys = set()

    events = []
    seen = set(delivered_keys)

    for record in records:
        for candidate in candidates:
            event = prepare_notification(record, candidate)

            if event is None:
                continue

            if event["event_key"] in seen:
                continue

            seen.add(event["event_key"])
            events.append(event)

    return events


def fetch_candidate(vk_client, post_url):
    """Только явный вызов wall.getById через существующий reader.

    Не вызывается автоматически при импорте или тестировании.
    """
    require_safe_mode()
    return read_vk_post(vk_client, post_url)


def enqueue_moderation_notifications(events, db_path=None):
    """Сохраняет события модерации в очереди без повторов."""
    from vk_notifications import enqueue_notification

    notification_ids = []

    for event in events:
        if not isinstance(event, dict):
            raise ValueError("INVALID_MODERATION_EVENT")

        if event.get("event_type") != "MODERATION_CANDIDATE":
            raise ValueError("UNEXPECTED_MODERATION_EVENT_TYPE")

        if event.get("authorship_verified") is not False:
            raise ValueError("UNSAFE_AUTHORSHIP_STATUS")

        if event.get("deletion_allowed") is not False:
            raise ValueError("UNSAFE_DELETION_STATUS")

        event_key = event.get("event_key")
        message = event.get("message")

        if not isinstance(event_key, str) or not event_key.strip():
            raise ValueError("INVALID_EVENT_KEY")

        if not isinstance(message, str) or not message.strip():
            raise ValueError("INVALID_NOTIFICATION_MESSAGE")

        notification_id = enqueue_notification(
            "PUBLICATION_REVIEW",
            details=message,
            db_path=db_path,
            event_key=event_key,
        )

        notification_ids.append(notification_id)

    return notification_ids
