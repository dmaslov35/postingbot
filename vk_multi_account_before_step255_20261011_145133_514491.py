from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import json
import os
import random
import sqlite3
import sys
import uuid

BASE = Path("/opt/vkbot")

DB_FILE = BASE / "vk_multi_account.sqlite3"
ACCOUNTS_DIR = BASE / "accounts"
GROUPS_FILE = BASE / "groups.txt"

# ============================================================
# GLOBAL HARD SAFETY
# ============================================================

PRODUCTION_MASTER_UNLOCKED = True

# No mutation is permitted while this is False.
REAL_VK_ACTIONS_ENABLED = True

# Individual mutation gates.
SUGGEST_ENABLED = True
CREATE_ENABLED = False
SUBSCRIBE_ENABLED = False
JOIN_ENABLED = False

# One browser / one account at a time.
MAX_PARALLEL_ACCOUNTS = 1

# Queue policy.
DEFAULT_MIN_DELAY_SEC = 15 * 60
DEFAULT_MAX_DELAY_SEC = 35 * 60

# Prevent repeated successful publication to same group.
DEFAULT_GROUP_COOLDOWN_HOURS = 72


def now():
    return datetime.now().isoformat(timespec="seconds")


def normalize_vk_url(raw):
    raw = str(raw or "").strip()

    if not raw:
        return None

    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)

    host = parsed.netloc.lower().split(":")[0]

    if host in {
        "vk.com",
        "www.vk.com",
        "vk.ru",
        "www.vk.ru",
    }:
        host = "vk.ru"

    path = "/" + parsed.path.strip("/")

    if path == "/":
        return None

    return f"https://{host}{path}"


def connect():
    con = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    con.execute(
        "PRAGMA journal_mode=WAL"
    )

    con.execute(
        "PRAGMA foreign_keys=ON"
    )

    return con


def init_db():
    ACCOUNTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    con = connect()

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            profile_dir TEXT NOT NULL UNIQUE,

            enabled INTEGER NOT NULL DEFAULT 1,

            auth_status TEXT NOT NULL
                DEFAULT 'UNKNOWN',

            status TEXT NOT NULL
                DEFAULT 'READY',

            last_error TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            last_started_at TEXT,
            last_finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS account_group_state (
            account_id INTEGER NOT NULL,
            group_url TEXT NOT NULL,

            capability TEXT,
            subscription TEXT,

            last_status TEXT,
            last_error TEXT,

            updated_at TEXT NOT NULL,

            PRIMARY KEY (
                account_id,
                group_url
            ),

            FOREIGN KEY(account_id)
                REFERENCES accounts(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_url TEXT NOT NULL,

            account_id INTEGER,

            requested_flow TEXT NOT NULL
                DEFAULT 'AUTO',

            selected_flow TEXT,

            status TEXT NOT NULL
                DEFAULT 'WAITING',

            priority INTEGER NOT NULL
                DEFAULT 100,

            attempts INTEGER NOT NULL
                DEFAULT 0,

            message_text TEXT,

            result TEXT,
            error TEXT,

            created_at TEXT NOT NULL,
            not_before TEXT,

            started_at TEXT,
            finished_at TEXT,

            FOREIGN KEY(account_id)
                REFERENCES accounts(id)
                ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS post_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            queue_id INTEGER,
            account_id INTEGER NOT NULL,
            group_url TEXT NOT NULL,

            flow TEXT NOT NULL,

            message_text TEXT,

            status TEXT NOT NULL,

            created_at TEXT NOT NULL,

            FOREIGN KEY(queue_id)
                REFERENCES queue(id)
                ON DELETE SET NULL,

            FOREIGN KEY(account_id)
                REFERENCES accounts(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_queue_status
        ON queue(status, priority, id);

        CREATE INDEX IF NOT EXISTS idx_history_group
        ON post_history(group_url, created_at);

        CREATE INDEX IF NOT EXISTS idx_account_group
        ON account_group_state(
            account_id,
            group_url
        );
        """
    )

    defaults = {
        "production_master_unlocked": "0",
        "real_vk_actions_enabled": "0",
        "suggest_enabled": "0",
        "create_enabled": "0",
        "subscribe_enabled": "0",
        "join_enabled": "0",

        "min_delay_sec":
            str(DEFAULT_MIN_DELAY_SEC),

        "max_delay_sec":
            str(DEFAULT_MAX_DELAY_SEC),

        "group_cooldown_hours":
            str(DEFAULT_GROUP_COOLDOWN_HOURS),
    }

    for key, value in defaults.items():
        con.execute(
            """
            INSERT OR IGNORE INTO settings(
                key,
                value
            )
            VALUES (?, ?)
            """,
            (key, value),
        )

    con.commit()
    con.close()


def get_setting(key, default=None):
    con = connect()

    row = con.execute(
        """
        SELECT value
        FROM settings
        WHERE key=?
        """,
        (key,),
    ).fetchone()

    con.close()

    if row is None:
        return default

    return row["value"]


def setting_bool(key):
    return get_setting(
        key,
        "0",
    ) == "1"


def set_setting(key, value):
    con = connect()

    con.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )

    con.commit()
    con.close()


def assert_global_safety():
    # File-level lock.
    if not PRODUCTION_MASTER_UNLOCKED:
        raise RuntimeError(
            "MULTI_ACCOUNT_MASTER_LOCKED"
        )

    # DB-level lock.
    if not setting_bool(
        "production_master_unlocked"
    ):
        raise RuntimeError(
            "DATABASE_MASTER_LOCKED"
        )

    if not REAL_VK_ACTIONS_ENABLED:
        raise RuntimeError(
            "REAL_VK_ACTIONS_DISABLED"
        )

    if not setting_bool(
        "real_vk_actions_enabled"
    ):
        raise RuntimeError(
            "DATABASE_REAL_ACTIONS_DISABLED"
        )


def safe_code(value):
    value = str(value).strip().lower()

    out = []

    for ch in value:
        if ch.isalnum() or ch in "_-":
            out.append(ch)

    code = "".join(out).strip("_-")

    if not code:
        raise ValueError(
            "ACCOUNT_CODE_EMPTY"
        )

    return code


def add_account(code, name):
    code = safe_code(code)
    name = str(name).strip()

    if not name:
        raise ValueError(
            "ACCOUNT_NAME_EMPTY"
        )

    profile = (
        ACCOUNTS_DIR
        / code
        / "profile"
    )

    profile.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.chmod(
        ACCOUNTS_DIR / code,
        0o700,
    )

    con = connect()

    ts = now()

    try:
        con.execute(
            """
            INSERT INTO accounts(
                code,
                name,
                profile_dir,
                enabled,
                auth_status,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 1, 'UNKNOWN',
                    'READY', ?, ?)
            """,
            (
                code,
                name,
                str(profile),
                ts,
                ts,
            ),
        )

        con.commit()

    finally:
        con.close()

    return profile


def list_accounts():
    con = connect()

    rows = con.execute(
        """
        SELECT *
        FROM accounts
        ORDER BY id
        """
    ).fetchall()

    con.close()

    return rows


def get_account(account_id):
    con = connect()

    row = con.execute(
        """
        SELECT *
        FROM accounts
        WHERE id=?
        """,
        (account_id,),
    ).fetchone()

    con.close()

    return row


def set_account_enabled(
    account_id,
    enabled,
):
    con = connect()

    con.execute(
        """
        UPDATE accounts
        SET enabled=?,
            status=?,
            updated_at=?
        WHERE id=?
        """,
        (
            1 if enabled else 0,
            "READY" if enabled else "PAUSED",
            now(),
            account_id,
        ),
    )

    con.commit()
    con.close()


def set_account_auth(
    account_id,
    auth_status,
    error=None,
):
    con = connect()

    con.execute(
        """
        UPDATE accounts
        SET auth_status=?,
            last_error=?,
            updated_at=?
        WHERE id=?
        """,
        (
            auth_status,
            error,
            now(),
            account_id,
        ),
    )

    con.commit()
    con.close()


def set_account_status(
    account_id,
    status,
    error=None,
):
    con = connect()

    con.execute(
        """
        UPDATE accounts
        SET status=?,
            last_error=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            error,
            now(),
            account_id,
        ),
    )

    con.commit()
    con.close()


def queue_group(
    group_url,
    account_id=None,
    requested_flow="AUTO",
    priority=100,
):
    url = normalize_vk_url(
        group_url
    )

    if not url:
        raise ValueError(
            "INVALID_GROUP_URL"
        )

    flow = str(
        requested_flow
    ).upper()

    if flow not in {
        "AUTO",
        "SUGGEST",
        "CREATE",
    }:
        raise ValueError(
            "INVALID_FLOW"
        )

    con = connect()

    # Do not create duplicate waiting jobs.
    row = con.execute(
        """
        SELECT id
        FROM queue
        WHERE group_url=?
          AND status IN (
              'WAITING',
              'RUNNING'
          )
        LIMIT 1
        """,
        (url,),
    ).fetchone()

    if row:
        con.close()
        return row["id"], False

    cur = con.execute(
        """
        INSERT INTO queue(
            group_url,
            account_id,
            requested_flow,
            status,
            priority,
            created_at
        )
        VALUES (?, ?, ?, 'WAITING', ?, ?)
        """,
        (
            url,
            account_id,
            flow,
            priority,
            now(),
        ),
    )

    queue_id = cur.lastrowid

    con.commit()
    con.close()

    return queue_id, True


def queue_groups_file():
    if not GROUPS_FILE.exists():
        raise RuntimeError(
            f"GROUPS_FILE_NOT_FOUND:"
            f"{GROUPS_FILE}"
        )

    added = 0
    existing = 0

    seen = set()

    for raw in GROUPS_FILE.read_text(
        encoding="utf-8-sig"
    ).splitlines():

        url = normalize_vk_url(raw)

        if not url:
            continue

        if url.lower() in seen:
            continue

        seen.add(url.lower())

        _, created = queue_group(url)

        if created:
            added += 1
        else:
            existing += 1

    return added, existing


def reset_interrupted_jobs():
    """
    Прерванные публикации нельзя повторять автоматически:
    VK мог принять объявление до сбоя процесса.
    """
    con = connect()
    try:
        con.execute(
            """
            UPDATE queue
            SET status='REVIEW_REQUIRED',
                error='INTERRUPTED_PUBLICATION_CHECK_REQUIRED',
                finished_at=?
            WHERE status='RUNNING'
            """,
            (now(),),
        )

        con.execute(
            """
            UPDATE accounts
            SET status=CASE
                    WHEN enabled=1 THEN 'READY'
                    ELSE 'PAUSED'
                END,
                updated_at=?
            WHERE status='BUSY'
            """,
            (now(),),
        )

        con.commit()
    finally:
        con.close()


def next_job():
    con = connect()

    row = con.execute(
        """
        SELECT *
        FROM queue
        WHERE status='WAITING'
          AND (
              not_before IS NULL
              OR not_before <= ?
          )
        ORDER BY
            priority ASC,
            id ASC
        LIMIT 1
        """,
        (now(),),
    ).fetchone()

    con.close()

    return row


def enabled_accounts():
    con = connect()

    rows = con.execute(
        """
        SELECT *
        FROM accounts
        WHERE enabled=1
          AND status='READY'
          AND auth_status='AUTHORIZED'
        ORDER BY
            COALESCE(
                last_finished_at,
                '1970-01-01'
            ) ASC,
            id ASC
        """
    ).fetchall()

    con.close()

    return rows


def account_capability(
    account_id,
    group_url,
):
    con = connect()

    row = con.execute(
        """
        SELECT *
        FROM account_group_state
        WHERE account_id=?
          AND group_url=?
        """,
        (
            account_id,
            group_url,
        ),
    ).fetchone()

    con.close()

    return row


def save_capability(
    account_id,
    group_url,
    capability,
    subscription=None,
    status=None,
    error=None,
):
    con = connect()

    con.execute(
        """
        INSERT INTO account_group_state(
            account_id,
            group_url,
            capability,
            subscription,
            last_status,
            last_error,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(
            account_id,
            group_url
        )
        DO UPDATE SET
            capability=
                excluded.capability,
            subscription=
                excluded.subscription,
            last_status=
                excluded.last_status,
            last_error=
                excluded.last_error,
            updated_at=
                excluded.updated_at
        """,
        (
            account_id,
            group_url,
            capability,
            subscription,
            status,
            error,
            now(),
        ),
    )

    con.commit()
    con.close()


def choose_account(job):
    if job["account_id"]:
        account = get_account(
            job["account_id"]
        )

        if (
            account
            and account["enabled"]
            and account["status"] == "READY"
            and account["auth_status"] == "AUTHORIZED" 
        ):
            return account

        return None

    accounts = enabled_accounts()

    if not accounts:
        return None

    # Prefer known compatible account.
    for account in accounts:
        cap = account_capability(
            account["id"],
            job["group_url"],
        )

        if not cap:
            continue

        capability = cap[
            "capability"
        ]

        requested = job[
            "requested_flow"
        ]

        if (
            requested == "AUTO"
            and capability
                in {"SUGGEST", "CREATE"}
        ):
            return account

        if capability == requested:
            return account

    # Unknown capability:
    # oldest-used enabled account gets
    # the read/inspect attempt.
    return accounts[0]


def mark_running(
    queue_id,
    account_id,
):
    con = connect()

    con.execute(
        """
        UPDATE queue
        SET status='RUNNING',
            account_id=?,
            attempts=attempts+1,
            started_at=?,
            error=NULL
        WHERE id=?
        """,
        (
            account_id,
            now(),
            queue_id,
        ),
    )

    con.execute(
        """
        UPDATE accounts
        SET status='BUSY',
            last_started_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            now(),
            now(),
            account_id,
        ),
    )

    con.commit()
    con.close()


def finish_account(account_id):
    con = connect()

    con.execute(
        """
        UPDATE accounts
        SET status=
            CASE
                WHEN enabled=1
                THEN 'READY'
                ELSE 'PAUSED'
            END,
            last_finished_at=?,
            updated_at=?
        WHERE id=?
          AND status='BUSY'
        """,
        (
            now(),
            now(),
            account_id,
        ),
    )

    con.commit()
    con.close()


def finish_job(
    queue_id,
    status,
    result=None,
    error=None,
    selected_flow=None,
    message_text=None,
):
    con = connect()

    con.execute(
        """
        UPDATE queue
        SET status=?,
            result=?,
            error=?,
            selected_flow=
                COALESCE(?, selected_flow),
            message_text=
                COALESCE(?, message_text),
            finished_at=?
        WHERE id=?
        """,
        (
            status,
            result,
            error,
            selected_flow,
            message_text,
            now(),
            queue_id,
        ),
    )

    con.commit()
    con.close()


def add_history(
    queue_id,
    account_id,
    group_url,
    flow,
    message_text,
    status,
):
    con = connect()

    con.execute(
        """
        INSERT INTO post_history(
            queue_id,
            account_id,
            group_url,
            flow,
            message_text,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            queue_id,
            account_id,
            group_url,
            flow,
            message_text,
            status,
            now(),
        ),
    )

    con.commit()
    con.close()


def successful_group_before(
    group_url,
):
    con = connect()

    row = con.execute(
        """
        SELECT *
        FROM post_history
        WHERE group_url=?
          AND status IN (
              'CONFIRMED',
              'PROBABLE',
              'REMOTE_ATTEMPTED',
              'UNCERTAIN'
          )
        ORDER BY id DESC
        LIMIT 1
        """,
        (group_url,),
    ).fetchone()

    con.close()

    return row


def queue_stats():
    con = connect()

    rows = con.execute(
        """
        SELECT status, COUNT(*) AS n
        FROM queue
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()

    con.close()

    return {
        row["status"]: row["n"]
        for row in rows
    }


def account_stats():
    con = connect()

    rows = con.execute(
        """
        SELECT
            a.*,
            (
                SELECT COUNT(*)
                FROM post_history h
                WHERE h.account_id=a.id
            ) AS history_count
        FROM accounts a
        ORDER BY a.id
        """
    ).fetchall()

    con.close()

    return rows


def print_status():
    print()
    print("=" * 70)
    print("VK MULTI ACCOUNT")
    print("=" * 70)

    print(
        "MASTER LOCK:",
        "UNLOCKED"
        if PRODUCTION_MASTER_UNLOCKED
        else "LOCKED",
    )

    print(
        "REAL VK ACTIONS:",
        "ENABLED"
        if REAL_VK_ACTIONS_ENABLED
        else "DISABLED",
    )

    print()
    print("ACCOUNTS")

    accounts = account_stats()

    if not accounts:
        print("  no accounts")

    for a in accounts:
        print(
            f"  #{a['id']} "
            f"{a['code']} "
            f"name={a['name']} "
            f"enabled={bool(a['enabled'])} "
            f"auth={a['auth_status']} "
            f"status={a['status']} "
            f"history={a['history_count']}"
        )

    print()
    print("QUEUE")

    stats = queue_stats()

    if not stats:
        print("  empty")

    for status, count in stats.items():
        print(
            f"  {status}: {count}"
        )

    print("=" * 70)


def usage():
    print(
        """
Usage:

  python vk_multi_account.py init

  python vk_multi_account.py status

  python vk_multi_account.py add-account CODE NAME

  python vk_multi_account.py enable ID

  python vk_multi_account.py disable ID

  python vk_multi_account.py auth-ok ID

  python vk_multi_account.py auth-required ID

  python vk_multi_account.py queue URL

  python vk_multi_account.py queue-file

  python vk_multi_account.py reset-running
"""
    )


def main():
    init_db()

    if len(sys.argv) < 2:
        print_status()
        return

    cmd = sys.argv[1]

    if cmd == "init":
        print(
            "DATABASE INITIALIZED:",
            DB_FILE,
        )
        print_status()
        return

    if cmd == "status":
        print_status()
        return

    if cmd == "add-account":
        if len(sys.argv) < 4:
            raise SystemExit(
                "add-account CODE NAME"
            )

        profile = add_account(
            sys.argv[2],
            " ".join(sys.argv[3:]),
        )

        print(
            "ACCOUNT CREATED"
        )

        print(
            "PROFILE:",
            profile,
        )

        return

    if cmd in {
        "enable",
        "disable",
        "auth-ok",
        "auth-required",
    }:
        if len(sys.argv) != 3:
            raise SystemExit(
                f"{cmd} ID"
            )

        account_id = int(
            sys.argv[2]
        )

        if cmd == "enable":
            set_account_enabled(
                account_id,
                True,
            )

        elif cmd == "disable":
            set_account_enabled(
                account_id,
                False,
            )

        elif cmd == "auth-ok":
            set_account_auth(
                account_id,
                "AUTHORIZED",
            )

        elif cmd == "auth-required":
            set_account_auth(
                account_id,
                "AUTH_REQUIRED",
            )

            set_account_status(
                account_id,
                "AUTH_REQUIRED",
            )

        print_status()
        return

    if cmd == "queue":
        if len(sys.argv) != 3:
            raise SystemExit(
                "queue URL"
            )

        queue_id, created = (
            queue_group(
                sys.argv[2]
            )
        )

        print(
            "QUEUE:",
            queue_id,
            "CREATED:"
            if created
            else "ALREADY EXISTS",
        )

        return

    if cmd == "queue-file":
        added, existing = (
            queue_groups_file()
        )

        print(
            "ADDED:",
            added,
        )

        print(
            "EXISTING:",
            existing,
        )

        return

    if cmd == "reset-running":
        reset_interrupted_jobs()

        print(
            "INTERRUPTED JOBS RESET"
        )

        return

    usage()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
