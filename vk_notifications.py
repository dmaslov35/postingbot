"""Безопасная подготовка уведомлений Telegram.

Модуль не отправляет сообщения самостоятельно.
Для отправки необходим отдельный явный вызов.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_EVENTS = {'DELETE_COMPLETED', 'PUBLICATION_CONFIRMED', 'DELETE_FAILED', 'SERVICE_ERROR', 'PUBLICATION_FAILED', 'VK_AUTH_REQUIRED', 'DELETE_REVIEW_REQUIRED', 'PUBLICATION_REVIEW'}

EVENT_TITLES = {'PUBLICATION_REVIEW': 'Публикация требует проверки', 'PUBLICATION_CONFIRMED': 'Публикация подтверждена', 'PUBLICATION_FAILED': 'Ошибка публикации', 'VK_AUTH_REQUIRED': 'Требуется авторизация VK', 'DELETE_COMPLETED': 'Объявление удалено', 'DELETE_FAILED': 'Ошибка удаления', 'SERVICE_ERROR': 'Ошибка работы бота', 'DELETE_REVIEW_REQUIRED': 'Требуется проверка удаления'}


def build_notification(event, details=""):
    """Формирует русскоязычное уведомление."""

    if event not in ALLOWED_EVENTS:
        raise ValueError("Неизвестный тип уведомления")

    title = EVENT_TITLES[event]
    timestamp = datetime.now(
        timezone.utc
    ).strftime("%d.%m.%Y %H:%M UTC")

    message = f"🔔 {title}\n🕒 {timestamp}"

    if details:
        message += f"\n\n{str(details)[:1500]}"

    return message


def notification_record(event, details=""):
    """Создаёт запись для последующей доставки."""

    return {
        "event": event,
        "message": build_notification(event, details),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "delivered": False,
    }


# Очередь событий не отправляет сообщения самостоятельно.
# Доставка подключается отдельно.
DEFAULT_QUEUE_DB = Path(__file__).resolve().parent / "runtime" / "notifications.sqlite3"


def _connect_queue(db_path=None):
    """Подключение к очереди с безопасным обновлением схемы."""
    import sqlite3

    path = Path(db_path) if db_path is not None else DEFAULT_QUEUE_DB
    path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")

    try:
        # STEP590_EVENT_KEY_MIGRATION
        db.execute("""
            CREATE TABLE IF NOT EXISTS notification_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','SENT')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sent_at TEXT,
                event_key TEXT
            )
        """)

        columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(notification_queue)"
            )
        }

        if "event_key" not in columns:
            db.execute(
                "ALTER TABLE notification_queue "
                "ADD COLUMN event_key TEXT"
            )

        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_notification_queue_event_key
            ON notification_queue(event_key)
        """)

        db.commit()
        return db

    except Exception:
        db.rollback()
        db.close()
        raise


def enqueue_notification(event, details="", db_path=None, event_key=None):
    """Добавляет уведомление, не дублируя события с одинаковым ключом."""
    message = build_notification(event, details)

    if event_key is not None:
        if not isinstance(event_key, str) or not event_key.strip():
            raise ValueError("INVALID_EVENT_KEY")

    with _connect_queue(db_path) as db:
        if event_key is None:
            cursor = db.execute(
                "INSERT INTO notification_queue (event, message) VALUES (?, ?)",
                (event, message)
            )
            return cursor.lastrowid

        cursor = db.execute(
            """
            INSERT OR IGNORE INTO notification_queue
                (event, message, event_key)
            VALUES (?, ?, ?)
            """,
            (event, message, event_key)
        )

        if cursor.rowcount == 1:
            return cursor.lastrowid

        row = db.execute(
            "SELECT id FROM notification_queue WHERE event_key=?",
            (event_key,)
        ).fetchone()

        if row is None:
            raise RuntimeError("NOTIFICATION_INSERT_FAILED")

        return row[0]


def pending_notifications(limit=20, db_path=None):
    """Возвращает ожидающие уведомления."""
    limit = max(1, min(int(limit), 100))

    with _connect_queue(db_path) as db:
        rows = db.execute(
            """
            SELECT id, event, message, created_at
            FROM notification_queue
            WHERE status='PENDING'
            ORDER BY id
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def mark_notification_sent(notification_id, db_path=None):
    """Помечает уведомление доставленным только после подтверждения отправки."""
    with _connect_queue(db_path) as db:
        cursor = db.execute(
            """
            UPDATE notification_queue
            SET status='SENT', sent_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='PENDING'
            """,
            (notification_id,)
        )
        return cursor.rowcount == 1
