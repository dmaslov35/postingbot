from pathlib import Path
from datetime import datetime, timedelta
import sqlite3
import shutil
import json

BASE = Path("/opt/vkbot")
DEST = BASE / "backups" / "daily"
DEST.mkdir(parents=True, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
target = DEST / today
target.mkdir(exist_ok=True)

files = ["messages.xlsx", "settings.json"]
databases = [
    "vk_multi_account.sqlite3",
    "runtime/publications.sqlite3",
]

for name in files:
    src = BASE / name
    if src.is_file():
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

for name in databases:
    src = BASE / name
    if src.is_file():
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(src)) as source:
            with sqlite3.connect(str(dst)) as backup:
                source.backup(backup)

cutoff = datetime.now() - timedelta(days=14)
for folder in DEST.iterdir():
    if folder.is_dir():
        try:
            if datetime.strptime(folder.name, "%Y-%m-%d") < cutoff:
                shutil.rmtree(folder)
        except ValueError:
            pass

print("Резервное копирование завершено:", target)
