#!/usr/bin/env python3
"""Install verified VK self-profile navigation (v4); no posting or DB edits."""
import ast
from datetime import datetime
from pathlib import Path
import shutil

path = Path('/opt/vkbot/vk_account_auth.py')
source = path.read_text(encoding='utf-8')
tree = ast.parse(source)
fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verified_self_id'), None)
if fn is None:
    raise SystemExit('STOP: verified_self_id missing')
lines = source.splitlines(keepends=True)
old = ''.join(lines[fn.lineno - 1:fn.end_lineno])
if 'profile navigation missing or ambiguous' not in old:
    raise SystemExit('STOP: unexpected function version; no changes made')
new = '''def verified_self_id(page):
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
        page.wait_for_url(re.compile(r'^https://(?:www\\.)?vk\\.(?:ru|com)/id[1-9][0-9]*/?(?:[?#].*)?$'), timeout=30000)
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
        print('IDENTITY: own profile confirmed', vk_id, flush=True)
        return vk_id
    except Exception as exc:
        print('IDENTITY: verification failed:', type(exc).__name__, flush=True)
        return None
'''
updated = ''.join(lines[:fn.lineno - 1]) + new + ''.join(lines[fn.end_lineno:])
ast.parse(updated)
backup = path.with_name(path.name + '.backup_identity_v4_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
shutil.copy2(path, backup)
try:
    path.write_text(updated, encoding='utf-8')
    ast.parse(path.read_text(encoding='utf-8'))
except Exception:
    shutil.copy2(backup, path)
    raise
print('PATCHED:', path)
print('BACKUP:', backup)
print('PASS: Python syntax')
print('UNCHANGED: browser profiles, database, production.stop')
