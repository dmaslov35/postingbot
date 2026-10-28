import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


LOCK_PATH = Path(
    "/opt/vkbot/.published_posts.lock"
)


def _open_lock_file():
    """
    Open the persistent posts transaction lock.

    The lock file is intentionally persistent.
    Never unlink it during normal operation.
    """
    fd = os.open(
        LOCK_PATH,
        os.O_RDWR | os.O_CREAT,
        0o600,
    )

    try:
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "a+")
    except Exception:
        os.close(fd)
        raise


@contextmanager
def published_posts_shared():
    lock_file = _open_lock_file()

    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_SH,
        )

        yield

    finally:
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            lock_file.close()


@contextmanager
def published_posts_exclusive():
    lock_file = _open_lock_file()

    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        yield

    finally:
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            lock_file.close()
