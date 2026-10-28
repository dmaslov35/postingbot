"""Strict guard for one explicitly approved VK test job.

This module validates context only. It does not authorize sending.
"""
import sqlite3
from pathlib import Path

ROOT = Path("/opt/vkbot")
DB = ROOT / "vk_multi_account.sqlite3"
STOP = ROOT / "runtime/production.stop"

EXPECTED_QUEUE_ID = 101
EXPECTED_ACCOUNT_ID = 4
EXPECTED_GROUP = "https://vk.ru/club240781173"
EXPECTED_FLOW = "SUGGEST"
EXPECTED_MESSAGE = (
    "🧪 ТЕСТОВОЕ УВЕДОМЛЕНИЕ\n\n"
    "Проверка автоматической публикации через бота "
    "«Вера ВК Постинг».\n\n"
    "Это техническая проверка. "
    "Объявление не является действующим предложением."
)


def validate_test_context():
    if not STOP.is_file():
        raise RuntimeError("TEST_REQUIRES_PRODUCTION_STOP")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        job = con.execute(
            "SELECT id, account_id, group_url, status, "
            "requested_flow, message_text "
            "FROM queue WHERE id=?",
            (EXPECTED_QUEUE_ID,),
        ).fetchone()

        if job is None:
            raise RuntimeError("TEST_JOB_MISSING")

        expected = {
            "id": EXPECTED_QUEUE_ID,
            "account_id": EXPECTED_ACCOUNT_ID,
            "group_url": EXPECTED_GROUP,
            "status": "WAITING",
            "requested_flow": EXPECTED_FLOW,
            "message_text": EXPECTED_MESSAGE,
        }

        for key, value in expected.items():
            if job[key] != value:
                raise RuntimeError("TEST_CONTEXT_MISMATCH:" + key)

        account = con.execute(
            "SELECT enabled, status, auth_status "
            "FROM accounts WHERE id=?",
            (EXPECTED_ACCOUNT_ID,),
        ).fetchone()

        if (
            account is None
            or account["enabled"] != 1
            or account["status"] != "READY"
            or account["auth_status"] != "AUTHORIZED"
        ):
            raise RuntimeError("TEST_ACCOUNT_NOT_READY")

        verified = con.execute(
            "SELECT EXISTS("
            "SELECT 1 FROM account_verified_identity "
            "WHERE account_id=? AND vk_user_id>0)",
            (EXPECTED_ACCOUNT_ID,),
        ).fetchone()[0]

        if verified != 1:
            raise RuntimeError("TEST_ACCOUNT_IDENTITY_NOT_VERIFIED")

        if not STOP.is_file():
            raise RuntimeError("PRODUCTION_STOP_REMOVED")

        return {
            "queue_id": EXPECTED_QUEUE_ID,
            "account_id": EXPECTED_ACCOUNT_ID,
            "group_url": EXPECTED_GROUP,
            "flow": EXPECTED_FLOW,
            "message_verified": True,
            "send_authorized": False,
        }
    finally:
        con.close()
