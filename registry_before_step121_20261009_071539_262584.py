import sqlite3
from pathlib import Path

DEFAULT_DB = Path("/opt/vkbot/runtime/publications.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id INTEGER,
    account_id INTEGER,
    group_url TEXT NOT NULL,
    flow TEXT NOT NULL CHECK(flow IN ('CREATE', 'SUGGEST')),
    vk_post_id TEXT,
    post_url TEXT,
    state TEXT NOT NULL CHECK(state IN (
        'SUBMITTED',
        'PENDING_MODERATION',
        'PUBLISHED',
        'REVIEW_REQUIRED',
        'DELETE_DUE',
        'DELETED',
        'DELETE_FAILED'
    )),
    published_at TEXT,
    delete_after TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(state != 'PUBLISHED' OR (
        vk_post_id IS NOT NULL
        AND post_url IS NOT NULL
        AND published_at IS NOT NULL
    ))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_queue
ON publications(queue_id)
WHERE queue_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_vk_id
ON publications(vk_post_id)
WHERE vk_post_id IS NOT NULL;
"""

def connect(db_path=DEFAULT_DB):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(SCHEMA)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS post_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER NOT NULL,
            vk_post_id TEXT NOT NULL,
            post_url TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0
                CHECK(verified = 0),
            discovered_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(queue_id, vk_post_id)
        )
    """)
    return connection

def register_attempt(
    queue_id, account_id, group_url, flow,
    state="REVIEW_REQUIRED", db_path=DEFAULT_DB
):
    if state not in (
        "SUBMITTED", "PENDING_MODERATION", "REVIEW_REQUIRED"
    ):
        raise ValueError("Invalid initial state")

    with connect(db_path) as db:
        db.execute("""
            INSERT INTO publications
            (queue_id, account_id, group_url, flow, state)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(queue_id) WHERE queue_id IS NOT NULL
            DO NOTHING
        """, (queue_id, account_id, group_url, flow, state))

def confirm_publication(
    queue_id, vk_post_id, post_url,
    published_at, delete_after=None, db_path=DEFAULT_DB
):
    raise RuntimeError('Автоматическое подтверждение публикации заблокировано: нет проверенного доказательства авторства')
    if not vk_post_id or not post_url or not published_at:
        raise ValueError("Publication proof is incomplete")

    with connect(db_path) as db:
        cursor = db.execute("""
            UPDATE publications
            SET vk_post_id=?, post_url=?,
                published_at=?, delete_after=?,
                state='PUBLISHED',
                updated_at=CURRENT_TIMESTAMP
            WHERE queue_id=?
              AND state IN (
                'SUBMITTED', 'PENDING_MODERATION',
                'REVIEW_REQUIRED'
              )
        """, (
            vk_post_id, post_url, published_at,
            delete_after, queue_id
        ))
        if cursor.rowcount != 1:
            raise ValueError("Publication not found or invalid state")

def get_due_deletions(db_path=DEFAULT_DB):
    with connect(db_path) as db:
        rows = db.execute("""
            SELECT * FROM publications
            WHERE state='PUBLISHED'
              AND delete_after IS NOT NULL
              AND delete_after <= CURRENT_TIMESTAMP
              AND vk_post_id IS NOT NULL
              AND post_url IS NOT NULL
            ORDER BY delete_after, id
        """).fetchall()
        return [dict(row) for row in rows]


def save_post_candidates(
    queue_id, candidates, db_path=DEFAULT_DB
):
    """Сохраняет только кандидатов, не подтверждая публикацию."""
    from vk_post_identity import extract_post_identity

    if not isinstance(candidates, list):
        return 0

    valid = {}

    for candidate in candidates[:100]:
        if not isinstance(candidate, dict):
            continue

        url = candidate.get("post_url")
        identity = extract_post_identity(url)

        if identity:
            valid[identity["vk_post_id"]] = identity

    with connect(db_path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS post_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_id INTEGER NOT NULL,
                vk_post_id TEXT NOT NULL,
                post_url TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0
                    CHECK(verified = 0),
                discovered_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(queue_id, vk_post_id)
            )
        """)

        for identity in valid.values():
            db.execute("""
                INSERT OR IGNORE INTO post_candidates
                (queue_id, vk_post_id, post_url)
                VALUES (?, ?, ?)
            """, (
                queue_id,
                identity["vk_post_id"],
                identity["post_url"]
            ))

    return len(valid)
