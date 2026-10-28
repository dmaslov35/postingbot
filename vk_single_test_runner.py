"""Isolated dry-run for VK test queue 101. No VK actions."""

import sqlite3
from pathlib import Path

from vk_single_test_guard import validate_test_context

ROOT = Path("/opt/vkbot")
DB = ROOT / "vk_multi_account.sqlite3"
STOP = ROOT / "runtime/production.stop"


def prepare_dry_run():
    context = validate_test_context()

    if context["send_authorized"] is not False:
        raise RuntimeError("UNEXPECTED_SEND_AUTHORIZATION")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    try:
        account = con.execute(
            "SELECT id, code, profile_dir "
            "FROM accounts WHERE id=?",
            (context["account_id"],),
        ).fetchone()

        if account is None:
            raise RuntimeError("TEST_ACCOUNT_MISSING")

        if not Path(account["profile_dir"]).is_dir():
            raise RuntimeError("TEST_PROFILE_MISSING")

        job = con.execute(
            "SELECT id, account_id, group_url, requested_flow "
            "FROM queue WHERE id=?",
            (context["queue_id"],),
        ).fetchone()

        if job is None:
            raise RuntimeError("TEST_JOB_MISSING")

        if job["account_id"] != account["id"]:
            raise RuntimeError("TEST_ACCOUNT_MISMATCH")

        if job["group_url"] != context["group_url"]:
            raise RuntimeError("TEST_GROUP_MISMATCH")

        if job["requested_flow"] != context["flow"]:
            raise RuntimeError("TEST_FLOW_MISMATCH")

        if not STOP.is_file():
            raise RuntimeError("PRODUCTION_STOP_MISSING")

        return {
            "queue_id": job["id"],
            "account_id": account["id"],
            "group_url": job["group_url"],
            "flow": job["requested_flow"],
            "profile_exists": True,
            "message_verified": context["message_verified"],
            "dry_run": True,
            "send_authorized": False,
        }
    finally:
        con.close()


if __name__ == "__main__":
    result = prepare_dry_run()

    print("=== SINGLE VK TEST: DRY-RUN ===")
    for key, value in result.items():
        print(f"{key.upper()}: {value}")

    print("VK_REQUESTS: NONE")
    print("PUBLICATIONS: NONE")
    print("DELETIONS: NONE")


def prepare_isolated_test():
    """Prepare a non-sending TEST configuration."""
    context = prepare_dry_run()

    if not STOP.is_file():
        raise RuntimeError("PRODUCTION_STOP_MISSING")

    if context["queue_id"] != 101:
        raise RuntimeError("UNEXPECTED_TEST_QUEUE")

    if context["account_id"] != 4:
        raise RuntimeError("UNEXPECTED_TEST_ACCOUNT")

    if context["flow"] != "SUGGEST":
        raise RuntimeError("UNEXPECTED_TEST_FLOW")

    return {
        "queue_id": 101,
        "account_id": 4,
        "group_url": context["group_url"],
        "mode": "TEST",
        "state_file": str(ROOT / "runtime/vk_single_test_101_state.json"),
        "test_submit_enabled": False,
        "production_enabled": False,
        "subscriptions_enabled": False,
        "join_requests_enabled": False,
        "browser_launch_enabled": False,
        "send_authorized": False,
    }
