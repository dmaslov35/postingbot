from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys

BASE = Path("/opt/vkbot")
RUNTIME = BASE / "runtime"

DB = BASE / "vk_multi_account.sqlite3"
PYTHON = BASE / "venv" / "bin" / "python"
ADAPTER = BASE / "vk_queue_worker_adapter.py"

TEST_GROUP = "https://vk.ru/club240781173"
TEST_QUEUE_ID = "TEST999001"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

account = con.execute("""
SELECT *
FROM accounts
WHERE id=1
""").fetchone()

con.close()

if not account:
    raise SystemExit("ACCOUNT_NOT_FOUND")

result_file = RUNTIME / f"queue_{TEST_QUEUE_ID}.json"

try:
    result_file.unlink()
except FileNotFoundError:
    pass

env = os.environ.copy()

env["VKBOT_MULTI_ACCOUNT"] = "1"
env["VKBOT_ACCOUNT_ID"] = str(account["id"])
env["VKBOT_ACCOUNT_CODE"] = account["code"]
env["VKBOT_PROFILE"] = account["profile_dir"]
env["VKBOT_SINGLE_GROUP"] = TEST_GROUP
env["VKBOT_QUEUE_ID"] = TEST_QUEUE_ID
env["VKBOT_REQUESTED_FLOW"] = "SUGGEST"

print("TEST GROUP:", TEST_GROUP)
print(
    "ACCOUNT:",
    f"#{account['id']} {account['code']}"
)
print("FLOW: SUGGEST")
print("MAX JOBS: 1")
print()

p = subprocess.run(
    [str(PYTHON), str(ADAPTER)],
    cwd=str(BASE),
    env=env,
)

print()
print("ADAPTER EXIT:", p.returncode)

if result_file.exists():
    print("RESULT:")
    print(
        result_file.read_text(
            encoding="utf-8"
        )
    )
else:
    print("RESULT FILE: MISSING")

sys.exit(p.returncode)
