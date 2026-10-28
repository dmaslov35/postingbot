from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from playwright.sync_api import (
    sync_playwright,
)

BASE = Path("/opt/vkbot")

DB = BASE / "vk_multi_account.sqlite3"

CHROME = (
    "/root/.cache/ms-playwright/"
    "chromium-1243/chrome-linux64/chrome"
)


def get_account(account_id):
    con = sqlite3.connect(DB)

    con.row_factory = sqlite3.Row

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


def set_auth(account_id, status):
    con = sqlite3.connect(DB)

    con.execute(
        """
        UPDATE accounts
        SET auth_status=?,
            status=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            status,
            (
                "READY"
                if status == "AUTHORIZED"
                else "AUTH_REQUIRED"
            ),
            account_id,
        ),
    )

    con.commit()
    con.close()


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: "
            "python vk_account_auth.py ID"
        )

    account_id = int(
        sys.argv[1]
    )

    account = get_account(
        account_id
    )

    if not account:
        raise SystemExit(
            "ACCOUNT_NOT_FOUND"
        )

    profile = Path(
        account["profile_dir"]
    )

    profile.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "ACCOUNT:",
        account["name"],
    )

    print(
        "PROFILE:",
        profile,
    )

    print(
        "Opening VK..."
    )

    with sync_playwright() as p:
        ctx = (
            p.chromium
            .launch_persistent_context(
                user_data_dir=str(
                    profile
                ),
                executable_path=CHROME,
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                viewport=None,
                timeout=120000,
            )
        )

        page = (
            ctx.pages[0]
            if ctx.pages
            else ctx.new_page()
        )

        page.goto(
            "https://vk.ru/feed",
            wait_until="domcontentloaded",
            timeout=120000,
        )

        print()
        print(
            "Complete login in VNC."
        )

        print(
            "When VK feed is visible, "
            "return here and press ENTER."
        )

        print()
        print("Complete login in VNC.")
        print("Authorization will be detected automatically.")

        print("Waiting for VK authorization...", flush=True)

        deadline = time.time() + 900
        authorized = False

        while time.time() < deadline:
            try:
                page.wait_for_timeout(2000)

                url = (page.url or "").lower()
                title = (page.title() or "").lower()

                body = ""
                try:
                    body = (
                        page.locator("body")
                        .inner_text(timeout=3000)
                        .lower()
                    )
                except Exception:
                    pass

                challenge = (
                    "проверяем, что вы не робот" in body
                    or "captcha" in url
                )

                login_page = (
                    "login" in url
                    or "id.vk.com" in url
                    or "войти" in title
                    or "вход" in title
                )

                normal_vk = (
                    (
                        "vk.ru" in url
                        or "vk.com" in url
                    )
                    and not login_page
                    and not challenge
                    and (
                        "/feed" in url
                        or "/im" in url
                        or "/friends" in url
                        or "/groups" in url
                        or "/id" in url
                        or "/club" in url
                        or "/public" in url
                    )
                )

                if normal_vk:
                    authorized = True
                    print(
                        "VK AUTHORIZATION DETECTED",
                        flush=True,
                    )
                    break

            except Exception as e:
                print(
                    "AUTH WAIT:",
                    type(e).__name__,
                    flush=True,
                )

        if not authorized:
            print(
                "AUTHORIZATION TIMEOUT",
                flush=True,
            )
            try:
                context.close()
            except Exception:
                pass
            browser.close()
            multi.set_auth_status(
                account_id,
                "AUTH_REQUIRED",
            )
            return 20

        page.goto(
            "https://vk.ru/feed",
            wait_until="domcontentloaded",
            timeout=120000,
        )

        time.sleep(2)

        title = page.title()

        body = page.locator(
            "body"
        ).inner_text()[:3000]

        bad = (
            "Проверяем, что вы не робот"
            in body
            or "Подтвердите вход"
            in body
            or "login"
            in page.url.lower()
        )

        if bad:
            set_auth(
                account_id,
                "AUTH_REQUIRED",
            )

            print(
                "AUTH NOT CONFIRMED"
            )

        else:
            set_auth(
                account_id,
                "AUTHORIZED",
            )

            print(
                "AUTHORIZED"
            )

        ctx.close()


if __name__ == "__main__":
    main()
