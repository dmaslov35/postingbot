#!/opt/vkbot/venv/bin/python3

import fcntl
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path
from account_lifecycle_lock import account_lifecycle_exclusive


BASE_DIR = Path("/opt/vkbot")
CONFIG_PATH = BASE_DIR / "config.json"
LOCK_PATH = BASE_DIR / ".config.lock"


def normalize_user_id(value):
    if isinstance(value, bool):
        return None

    try:
        user_id = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    if user_id <= 0:
        return None

    return user_id


def load_config():
    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:
        cfg = json.load(f)

    if not isinstance(cfg, dict):
        raise ValueError(
            "config.json root is not an object"
        )

    accounts = cfg.get("vk_accounts")

    if not isinstance(accounts, list):
        raise ValueError(
            "vk_accounts is not a list"
        )

    return cfg


def save_config_atomic(cfg):
    fd, tmp_name = tempfile.mkstemp(
        prefix=".config.token.",
        suffix=".tmp",
        dir=str(BASE_DIR),
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                cfg,
                f,
                ensure_ascii=False,
                indent=2,
            )

            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(tmp_name, 0o600)
        os.replace(
            tmp_name,
            CONFIG_PATH,
        )
        os.chmod(CONFIG_PATH, 0o600)

    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

        raise


def install_token(
    user_id,
    token,
):
    user_id = normalize_user_id(user_id)

    if user_id is None:
        return "bad_user_id"

    if not isinstance(token, str):
        return "bad_token"

    token = token.strip()

    if not token:
        return "bad_token"

    # Basic defensive size bound only.
    # This is NOT VK token validation.
    if len(token) > 8192:
        return "bad_token"

    LOCK_PATH.touch(
        mode=0o600,
        exist_ok=True,
    )
    os.chmod(LOCK_PATH, 0o600)

    with account_lifecycle_exclusive(user_id):
        with LOCK_PATH.open(
            "a+",
            encoding="utf-8",
        ) as lock_file:
    
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX,
            )
    
            try:
                cfg = load_config()
                accounts = cfg["vk_accounts"]
    
                matches = []
    
                for index, account in enumerate(accounts):
                    if not isinstance(account, dict):
                        continue
    
                    account_id = normalize_user_id(
                        account.get("user_id")
                    )
    
                    if account_id == user_id:
                        matches.append(index)
    
                # Duplicate UID is unsafe.
                if len(matches) > 1:
                    return "duplicate_user_id"
    
                if not matches:
                    return "not_found"
    
                index = matches[0]
                account = accounts[index]
    
                # Token installation NEVER enables account.
                account["token"] = token
                account["enabled"] = False
    
                save_config_atomic(cfg)
    
                return "installed"
    
            finally:
                fcntl.flock(
                    lock_file.fileno(),
                    fcntl.LOCK_UN,
                )


def main():
    if os.geteuid() != 0:
        print(
            "ERROR: run this installer as root.",
            file=sys.stderr,
        )
        return 1

    print("Secure VK Token Installer")
    print()
    print(
        "Токен не будет показан на экране "
        "и не передаётся в аргументах команды."
    )
    print(
        "Установка токена НЕ включает аккаунт "
        "и НЕ выполняет запрос к VK API."
    )
    print()

    raw_user_id = input(
        "VK user_id: "
    ).strip()

    user_id = normalize_user_id(
        raw_user_id
    )

    if user_id is None:
        print("ERROR: invalid VK user_id.")
        return 2

    token = getpass.getpass(
        "VK access token: "
    )

    if not token.strip():
        print("ERROR: empty token.")
        return 3

    confirm = getpass.getpass(
        "Repeat VK access token: "
    )

    if token != confirm:
        print("ERROR: tokens do not match.")
        return 4

    result = install_token(
        user_id,
        token,
    )

    if result == "installed":
        print()
        print("TOKEN: INSTALLED")
        print(
            f"VK user_id: {user_id}"
        )
        print("enabled: False")
        print("VK API validation: NOT PERFORMED")
        return 0

    messages = {
        "bad_user_id":
            "invalid VK user_id",
        "bad_token":
            "invalid/empty token",
        "not_found":
            "account does not exist in config",
        "duplicate_user_id":
            "duplicate VK user_id in config",
    }

    print(
        "ERROR:",
        messages.get(
            result,
            "unknown installer error",
        ),
    )

    return 5


if __name__ == "__main__":
    raise SystemExit(main())
