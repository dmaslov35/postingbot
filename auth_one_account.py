import json
import os
import sys
import time
import getpass
import shutil
from datetime import datetime

import vk_api


CONFIG_FILE = "config.json"
TARGET_USER_ID = 431975582


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_account(config, user_id):
    for index, account in enumerate(config.get("vk_accounts", [])):
        if int(account.get("user_id", 0)) == int(user_id):
            return index, account
    return None, None


def captcha_handler(captcha):
    print()
    print("VK запросил CAPTCHA.")
    print("URL CAPTCHA:")
    print(captcha.get_url())
    print()
    key = input("Введите код CAPTCHA: ").strip()
    return captcha.try_again(key)


def auth_handler():
    print()
    print("VK запросил код подтверждения / 2FA.")
    code = input("Введите код подтверждения: ").strip()
    remember_device = True
    return code, remember_device


def main():
    print("=" * 60)
    print("БЕЗОПАСНАЯ АВТОРИЗАЦИЯ ОДНОГО VK-АККАУНТА")
    print("=" * 60)
    print(f"Target user_id: {TARGET_USER_ID}")
    print()

    config = load_config()

    index, account = find_account(config, TARGET_USER_ID)

    if account is None:
        print("ERROR: аккаунт не найден в config.json")
        sys.exit(1)

    print(f"Найден аккаунт #{index + 1}")
    print(f"user_id: {account['user_id']}")
    print(f"enabled: {account.get('enabled', True)}")
    print()

    login = input(
        "Введите логин/телефон VK для этого аккаунта: "
    ).strip()

    password = getpass.getpass(
        "Введите пароль VK (на экране не отображается): "
    )

    if not login or not password:
        print("ERROR: логин или пароль пустой")
        sys.exit(1)

    print()
    print("Авторизация...")

    try:
        session = vk_api.VkApi(
            login=login,
            password=password,
            auth_handler=auth_handler,
            captcha_handler=captcha_handler,
            api_version="5.199",
        )

        session.auth(token_only=True)

        token = session.token.get("access_token")

        if not token:
            print("ERROR: VK не вернул access_token")
            sys.exit(1)

        print("Авторизация выполнена.")
        print("Проверяем принадлежность токена...")

        vk = session.get_api()
        users = vk.users.get()

        if not users:
            print("ERROR: users.get вернул пустой ответ")
            sys.exit(1)

        actual_user_id = int(users[0]["id"])

        print(f"VK подтвердил user_id: {actual_user_id}")

        if actual_user_id != TARGET_USER_ID:
            print()
            print("ERROR: получен токен ДРУГОГО аккаунта.")
            print("config.json НЕ изменён.")
            sys.exit(1)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"config.json.before_auth_{TARGET_USER_ID}_{stamp}"

        shutil.copy2(CONFIG_FILE, backup)
        os.chmod(backup, 0o600)

        account["token"] = token

        tmp = CONFIG_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                config,
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())

        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)

        print()
        print("SUCCESS")
        print(f"Аккаунт {TARGET_USER_ID} подтверждён.")
        print("Новый token сохранён в config.json.")
        print("Сам token на экран НЕ выводился.")
        print(f"Backup: {backup}")

    except Exception as e:
        print()
        print("AUTH FAILED")
        print(f"{type(e).__name__}: {e}")
        print("config.json НЕ изменён.")
        sys.exit(1)


if __name__ == "__main__":
    main()
