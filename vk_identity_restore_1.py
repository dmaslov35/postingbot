from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import sqlite3
import re

BASE = Path("/opt/vkbot")
STOP = BASE / "runtime/production.stop"
DB = BASE / "vk_multi_account.sqlite3"
CHROME = '/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'

assert STOP.is_file()

def verified_self_id(page):
    """Verify VK ID through logged-in session's own Profile navigation."""
    import re
    from urllib.parse import urlparse

    allowed = {'vk.ru', 'www.vk.ru', 'vk.com', 'www.vk.com'}
    if any(x in (page.url or '').lower() for x in ('login', 'id.vk.com', 'challenge', 'captcha')):
        return None

    try:
        # VK sidebar is hydrated asynchronously; an early DOM query returns zero.
        profile_link = page.get_by_text('Профиль', exact=True)
        profile_link.first.wait_for(state='visible', timeout=60000)
        if profile_link.count() != 1:
            print('IDENTITY: profile navigation ambiguous:', profile_link.count(), flush=True)
            return None
        profile_link.first.click(timeout=15000)
        page.wait_for_url(re.compile(r'^https://(?:www\.)?vk\.(?:ru|com)/id[1-9][0-9]*/?(?:[?#].*)?$'), timeout=30000)
        parsed = urlparse(page.url)
        if parsed.hostname not in allowed:
            return None
        match = re.fullmatch(r'/id([1-9][0-9]*)/?', parsed.path)
        if not match:
            print('IDENTITY: profile numeric ID missing', flush=True)
            return None
        owner_control = page.get_by_text('Редактировать профиль', exact=True)
        owner_control.first.wait_for(state='visible', timeout=30000)
        if owner_control.count() != 1:
            print('IDENTITY: edit control ambiguous', flush=True)
            return None
        vk_id = int(match.group(1))
        print('IDENTITY: own profile confirmed [ID HIDDEN]', flush=True)
        return vk_id
    except Exception as exc:
        print('IDENTITY: verification failed:', type(exc).__name__, flush=True)
        return None

def main():
    assert STOP.is_file()

    con = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT profile_dir FROM accounts WHERE id=1"
        ).fetchone()

        assert row is not None
        profile = Path(row[0]).resolve()

        existing = con.execute(
            "SELECT COUNT(*) FROM account_verified_identity WHERE account_id=1"
        ).fetchone()[0]

        assert existing == 0, "IDENTITY_ALREADY_EXISTS"
    finally:
        con.close()

    assert profile.is_dir()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=CHROME,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport=None,
            timeout=120000,
        )

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            page.goto(
                "https://vk.ru/feed",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            vk_id = verified_self_id(page)

            if not vk_id:
                print("IDENTITY_RESULT: NOT_VERIFIED")
                return

            print("IDENTITY_RESULT: VERIFIED")
            print("VK_ID_HIDDEN: YES")

        finally:
            ctx.close()

    # Сохранение только после подтверждения личности.
    assert STOP.is_file()

    con = sqlite3.connect(DB, timeout=10)

    try:
        con.execute("BEGIN IMMEDIATE")

        existing = con.execute(
            "SELECT 1 FROM account_verified_identity WHERE account_id=1"
        ).fetchone()

        assert existing is None, "IDENTITY_ALREADY_EXISTS"

        collision = con.execute(
            """
            SELECT 1 FROM account_verified_identity
            WHERE vk_user_id=?
            """,
            (vk_id,),
        ).fetchone()

        assert collision is None, "VK_ID_ALREADY_ASSIGNED"

        con.execute(
            """
            INSERT INTO account_verified_identity
            (account_id, vk_user_id, verified_at)
            VALUES (1, ?, datetime('now'))
            """,
            (vk_id,),
        )

        con.commit()

    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print("PASS: ACCOUNT_1_IDENTITY_RESTORED")
    print("PASS: VK_ID_NOT_DISCLOSED")
    print("PASS: PRODUCTION_STOP_PRESERVED")


if __name__ == "__main__":
    main()
