#!/opt/vkbot/venv/bin/python

from pathlib import Path
import os
import subprocess
import sys
import time

BASE = Path("/opt/vkbot")
RUNTIME = BASE / "runtime"

REQUEST_FILE = RUNTIME / "auth_account_id"
LOG_FILE = RUNTIME / "vk_account_auth_service.log"

PYTHON = BASE / "venv" / "bin" / "python"
AUTH_SCRIPT = BASE / "vk_account_auth.py"


def log(text):
    line = (
        time.strftime("%Y-%m-%d %H:%M:%S")
        + " "
        + str(text)
    )

    print(line, flush=True)

    with LOG_FILE.open(
        "a",
        encoding="utf-8",
    ) as f:
        f.write(line + "\n")


def main():
    RUNTIME.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not REQUEST_FILE.exists():
        log("ERROR: auth_account_id missing")
        return 10

    raw = REQUEST_FILE.read_text(
        encoding="utf-8"
    ).strip()

    try:
        account_id = int(raw)
    except Exception:
        log(
            "ERROR: invalid account id: "
            + repr(raw)
        )
        return 11

    if account_id <= 0:
        log("ERROR: account id <= 0")
        return 12

    if not AUTH_SCRIPT.exists():
        log("ERROR: vk_account_auth.py missing")
        return 13

    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    env["PYTHONUNBUFFERED"] = "1"

    log(
        f"START account_id={account_id}"
    )

    result = subprocess.run(
        [
            str(PYTHON),
            str(AUTH_SCRIPT),
            str(account_id),
        ],
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.stdout:
        for line in result.stdout.splitlines():
            log("AUTH: " + line)

    log(
        "FINISH "
        f"account_id={account_id} "
        f"returncode={result.returncode}"
    )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
