"""Доставка уведомлений через существующего Telegram-бота."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from vk_notifications import pending_notifications, mark_notification_sent

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
logger = logging.getLogger(__name__)


def load_telegram_settings(config_path=CONFIG):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    telegram = config.get("telegram", {})

    token = telegram.get("bot_token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Токен Telegram не настроен")

    raw_ids = telegram.get("admin_ids") or []
    if not isinstance(raw_ids, (list, tuple)):
        raw_ids = [raw_ids]

    single = telegram.get("admin_id")
    if single:
        raw_ids.append(single)

    recipients = []

    for value in raw_ids:
        try:
            chat_id = int(value)
            if chat_id and chat_id not in recipients:
                recipients.append(chat_id)
        except (TypeError, ValueError):
            continue

    if not recipients:
        raise ValueError("Не настроены получатели Telegram")

    return token.strip(), recipients


def send_telegram_message(token, chat_id, message, timeout=15):
    """Отправляет сообщение через Telegram Bot API."""

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Не выводим тело ответа и URL: в URL находится токен.
        raise RuntimeError(
            f"Telegram вернул HTTP {exc.code}"
        ) from None
    except urllib.error.URLError:
        raise RuntimeError("Telegram временно недоступен") from None

    if not result.get("ok"):
        raise RuntimeError("Telegram не подтвердил отправку")

    return True



def _delivery_connection(db_path=None):
    import sqlite3
    from vk_notifications import DEFAULT_QUEUE_DB

    path = Path(db_path) if db_path is not None else DEFAULT_QUEUE_DB
    path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(path), timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("""
        CREATE TABLE IF NOT EXISTS notification_recipients (
            notification_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(notification_id, chat_id)
        )
    """)
    return db


def deliver_pending(limit=20, db_path=None, sender=None,
                    config_path=CONFIG):
    """Доставляет сообщения с учётом каждого получателя."""

    token, recipients = load_telegram_settings(config_path)
    send = sender or send_telegram_message

    sent = 0
    failed = 0

    for notification in pending_notifications(
        limit=limit, db_path=db_path
    ):
        notification_id = notification["id"]
        all_delivered = True

        for chat_id in recipients:
            with _delivery_connection(db_path) as db:
                already_sent = db.execute(
                    """
                    SELECT 1 FROM notification_recipients
                    WHERE notification_id=? AND chat_id=?
                    """,
                    (notification_id, chat_id)
                ).fetchone() is not None

            if already_sent:
                continue

            try:
                result = send(
                    token, chat_id, notification["message"]
                )

                if result is not True:
                    raise RuntimeError(
                        "Telegram не подтвердил доставку"
                    )

                with _delivery_connection(db_path) as db:
                    db.execute(
                        """
                        INSERT OR IGNORE INTO notification_recipients
                        (notification_id, chat_id)
                        VALUES (?, ?)
                        """,
                        (notification_id, chat_id)
                    )
                    db.commit()

            except Exception:
                all_delivered = False
                failed += 1
                logger.error(
                    "Не удалось доставить уведомление #%s "
                    "одному из получателей",
                    notification_id
                )

        if all_delivered:
            with _delivery_connection(db_path) as db:
                delivered_count = db.execute(
                    """
                    SELECT COUNT(*) FROM notification_recipients
                    WHERE notification_id=?
                      AND chat_id IN (%s)
                    """ % ",".join("?" for _ in recipients),
                    [notification_id, *recipients]
                ).fetchone()[0]

            if delivered_count == len(recipients):
                if mark_notification_sent(
                    notification_id, db_path=db_path
                ):
                    sent += 1

    return {"sent": sent, "failed": failed}



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = deliver_pending()
    print(
        "Уведомления: доставлено =",
        result["sent"],
        ", ошибок =",
        result["failed"],
    )
