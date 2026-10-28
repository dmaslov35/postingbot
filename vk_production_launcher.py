#!/opt/vkbot/venv/bin/python

from pathlib import Path
from datetime import datetime
import ast
import sqlite3
import subprocess
import sys

BASE = Path("/opt/vkbot")

DISPATCHER = BASE / "vk_queue_dispatcher.py"
MULTI = BASE / "vk_multi_account.py"
ADAPTER = BASE / "vk_queue_worker_adapter.py"
DB = BASE / "vk_multi_account.sqlite3"

PYTHON = BASE / "venv" / "bin" / "python"

LOG = BASE / "vk_production_launcher.log"


def log(message):
    line = (
        f"[{datetime.now().isoformat(timespec='seconds')}] "
        f"{message}"
    )

    print(line, flush=True)

    with LOG.open(
        "a",
        encoding="utf-8",
    ) as f:
        f.write(line + "\n")


def read_assignment(path, name):
    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(path),
    )

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == name
                ):
                    try:
                        return ast.literal_eval(
                            node.value
                        )
                    except Exception:
                        return None

    return None


def db_setting(name):
    con = sqlite3.connect(DB)

    try:
        row = con.execute(
            """
            SELECT value
            FROM settings
            WHERE key=?
            """,
            (name,),
        ).fetchone()

        if row is None:
            return None

        return row[0]

    finally:
        con.close()


def deny(message, code=20):
    log(
        "DENIED: " + message
    )
    log(
        "NO VK ACTION WAS PERFORMED"
    )
    return code


def main():
    required = [
        DISPATCHER,
        MULTI,
        ADAPTER,
        DB,
    ]

    for path in required:
        if not path.exists():
            return deny(
                f"MISSING:{path}",
                10,
            )

    # --------------------------------------------------------
    # File-level locks.
    # --------------------------------------------------------

    if read_assignment(
        DISPATCHER,
        "PRODUCTION_MASTER_UNLOCKED",
    ) is not True:
        return deny(
            "DISPATCHER MASTER LOCKED"
        )

    if read_assignment(
        DISPATCHER,
        "REAL_VK_ACTIONS_ENABLED",
    ) is not True:
        return deny(
            "DISPATCHER REAL ACTIONS DISABLED"
        )

    if read_assignment(
        MULTI,
        "PRODUCTION_MASTER_UNLOCKED",
    ) is not True:
        return deny(
            "MULTI ACCOUNT MASTER LOCKED"
        )

    if read_assignment(
        MULTI,
        "REAL_VK_ACTIONS_ENABLED",
    ) is not True:
        return deny(
            "MULTI ACCOUNT REAL ACTIONS DISABLED"
        )

    if read_assignment(
        ADAPTER,
        "PRODUCTION_MASTER_UNLOCKED",
    ) is not True:
        return deny(
            "ADAPTER MASTER LOCKED"
        )

    if read_assignment(
        ADAPTER,
        "REAL_VK_ACTIONS_ENABLED",
    ) is not True:
        return deny(
            "ADAPTER REAL ACTIONS DISABLED"
        )

    if read_assignment(
        ADAPTER,
        "SUGGEST_ENABLED",
    ) is not True:
        return deny(
            "SUGGEST DISABLED"
        )

    # CREATE remains explicitly forbidden.
    if read_assignment(
        ADAPTER,
        "CREATE_ENABLED",
    ) is True:
        return deny(
            "CREATE PRODUCTION NOT APPROVED"
        )

    # --------------------------------------------------------
    # DB-level locks.
    # --------------------------------------------------------

    if db_setting(
        "production_master_unlocked"
    ) != "1":
        return deny(
            "DATABASE MASTER LOCKED"
        )

    if db_setting(
        "real_vk_actions_enabled"
    ) != "1":
        return deny(
            "DATABASE REAL ACTIONS DISABLED"
        )

    if db_setting(
        "suggest_enabled"
    ) != "1":
        return deny(
            "DATABASE SUGGEST DISABLED"
        )

    if db_setting(
        "create_enabled"
    ) == "1":
        return deny(
            "DATABASE CREATE MUST REMAIN DISABLED"
        )

    log(
        "ALL PRODUCTION SAFETY GATES PASSED"
    )

    log(
        "STARTING SEQUENTIAL MULTI-ACCOUNT DISPATCHER"
    )

    result = subprocess.run(
        [
            str(PYTHON),
            str(DISPATCHER),
        ],
        cwd=str(BASE),
    )

    log(
        f"Dispatcher exit code: "
        f"{result.returncode}"
    )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
