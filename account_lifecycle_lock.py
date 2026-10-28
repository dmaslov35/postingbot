import fcntl
import os
from contextlib import contextmanager
from typing import Iterator


LOCK_DIR = "/opt/vkbot/.account_locks"


def normalize_account_user_id(user_id) -> int:
    if isinstance(user_id, bool):
        raise ValueError("invalid account user_id")

    try:
        value = int(str(user_id).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid account user_id"
        ) from exc

    if value <= 0:
        raise ValueError("invalid account user_id")

    return value


def _ensure_lock_dir() -> None:
    os.makedirs(
        LOCK_DIR,
        mode=0o700,
        exist_ok=True,
    )

    os.chmod(
        LOCK_DIR,
        0o700,
    )


def _lock_path(user_id) -> str:
    normalized = normalize_account_user_id(
        user_id
    )

    return os.path.join(
        LOCK_DIR,
        f"{normalized}.lock",
    )


@contextmanager
def account_lifecycle_shared(
    user_id,
) -> Iterator[None]:
    """
    Shared lock for one account.

    Intended for VK network actions.
    """
    _ensure_lock_dir()
    path = _lock_path(user_id)

    with open(
        path,
        "a+",
        encoding="utf-8",
    ) as lock_file:
        os.chmod(path, 0o600)

        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_SH,
        )

        try:
            yield
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


@contextmanager
def account_lifecycle_exclusive(
    user_id,
) -> Iterator[None]:
    """
    Exclusive lock for account lifecycle mutation.

    Intended for enable/disable/delete/token changes.
    """
    _ensure_lock_dir()
    path = _lock_path(user_id)

    with open(
        path,
        "a+",
        encoding="utf-8",
    ) as lock_file:
        os.chmod(path, 0o600)

        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            yield
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )
