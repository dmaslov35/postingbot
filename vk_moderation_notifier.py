#!/usr/bin/env python3
"""Telegram-уведомления мониторинга VK с защитой от повторов."""

import json
import sqlite3
from pathlib import Path

import requests


BASE = Path("/opt/vkbot")
STOP = BASE / "runtime/production.stop"
CONFIG = BASE / "config.json"
DB = BASE / "runtime/moderation_notifications.sqlite3"


def require_safe_mode():
    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_REQUIRED")


def load_telegram_config():
    require_safe_mode()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    telegram = config["telegram"]

    token = telegram["bot_token"]

    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("INVALID_TELEGRAM_TOKEN")

    recipients = telegram.get("admin_ids", [])

    if not isinstance(recipients, list):
        raise RuntimeError("INVALID_ADMIN_IDS")

    recipients = list(dict.fromkeys(
        str(x) for x in recipients
        if str(x).strip()
    ))

    if not recipients:
        admin_id = telegram.get("admin_id")
        if admin_id:
            recipients = [str(admin_id)]

    if not recipients:
        raise RuntimeError("NO_TELEGRAM_RECIPIENTS")

    return token, recipients


def connect_database():
    require_safe_mode()

    DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB, timeout=10)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            event_key TEXT NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT,
            PRIMARY KEY (event_key, recipient)
        )
    """)

    conn.commit()
    return conn


def already_delivered(conn, event_key, recipient):
    row = conn.execute(
        """
        SELECT status FROM notifications
        WHERE event_key = ? AND recipient = ?
        """,
        (event_key, str(recipient)),
    ).fetchone()

    return bool(row and row[0] == "DELIVERED")


def send_notification(event, dry_run=True):
    require_safe_mode()

    if not isinstance(event, dict):
        raise ValueError("INVALID_EVENT")

    if event.get("authorship_verified") is not False:
        raise RuntimeError("UNSAFE_AUTHORSHIP_STATE")

    if event.get("deletion_allowed") is not False:
        raise RuntimeError("UNSAFE_DELETION_STATE")

    key = event.get("event_key")
    message = event.get("message")

    if not isinstance(key, str) or not key:
        raise ValueError("INVALID_EVENT_KEY")

    if not isinstance(message, str) or not message:
        raise ValueError("INVALID_MESSAGE")

    token, recipients = load_telegram_config()

    if dry_run:
        return {
            "mode": "DRY_RUN",
            "recipient_count": len(recipients),
            "sent": 0,
        }

    require_safe_mode()
    conn = connect_database()
    sent = 0
    pending = 0

    try:
        for recipient in recipients:
            require_safe_mode()

            if already_delivered(conn, key, recipient):
                continue

            # Записываем попытку до сетевого запроса.
            # Неопределённые результаты не повторяются автоматически.
            with conn:
                inserted = conn.execute(
                    """
                    INSERT OR IGNORE INTO notifications
                    (event_key, recipient, status)
                    VALUES (?, ?, 'SENDING')
                    """,
                    (key, recipient),
                ).rowcount

            if not inserted:
                pending += 1
                continue

            try:
                response = requests.post(
                    "https://api.telegram.org/bot"
                    + token + "/sendMessage",
                    json={
                        "chat_id": recipient,
                        "text": message,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )

                payload = response.json()

                if response.status_code == 200 and payload.get("ok") is True:
                    with conn:
                        conn.execute(
                            """
                            UPDATE notifications
                            SET status = 'DELIVERED',
                                delivered_at = CURRENT_TIMESTAMP
                            WHERE event_key = ? AND recipient = ?
                            """,
                            (key, recipient),
                        )
                    sent += 1
                else:
                    with conn:
                        conn.execute(
                            """
                            UPDATE notifications
                            SET status = 'REVIEW_REQUIRED'
                            WHERE event_key = ? AND recipient = ?
                            """,
                            (key, recipient),
                        )
                    pending += 1

            except (requests.RequestException, ValueError):
                with conn:
                    conn.execute(
                        """
                        UPDATE notifications
                        SET status = 'REVIEW_REQUIRED'
                        WHERE event_key = ? AND recipient = ?
                        """,
                        (key, recipient),
                    )
                pending += 1

    finally:
        conn.close()

    return {
        "mode": "LIVE",
        "recipient_count": len(recipients),
        "sent": sent,
        "review_required": pending,
    }
