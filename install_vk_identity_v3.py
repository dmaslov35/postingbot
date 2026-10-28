#!/usr/bin/env python3
"""Patch only verified_self_id in /opt/vkbot/vk_account_auth.py."""
import ast
from datetime import datetime
from pathlib import Path
import shutil

path = Path('/opt/vkbot/vk_account_auth.py')
source = path.read_text(encoding='utf-8')
tree = ast.parse(source)
fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verified_self_id'), None)
if fn is None:
    raise SystemExit('STOP: verified_self_id not found')
lines = source.splitlines(keepends=True)
old = ''.join(lines[fn.lineno - 1:fn.end_lineno])
if 'self-profile link missing or ambiguous' not in old:
    raise SystemExit('STOP: unexpected identity function; nothing changed')
new = '''def verified_self_id(page):
    """Verify the logged-in user's own profile through VK's Profile navigation."""
    import re
    from urllib.parse import urlparse

    allowed = {'vk.ru', 'www.vk.ru', 'vk.com', 'www.vk.com'}

    def numeric_id(url):
        parsed = urlparse(url)
        if parsed.hostname not in allowed:
            return None
        match = re.fullmatch(r'/id([1-9][0-9]*)/?', parsed.path)
        return int(match.group(1)) if match else None

    if any(x in (page.url or '').lower() for x in ('login', 'id.vk.com', 'challenge', 'captcha')):
        return None

    # Only links explicitly labelled as *my* Profile, never arbitrary profile
    # links in the feed or URLs pasted by a user.
    try:
        links = page.locator('a').evaluate_all(''' + "'''" + '''(els) => els.filter(a => {
            const label = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' ');
            const aria = (a.getAttribute('aria-label') || '').trim();
            return label === 'Профиль' || label === 'Моя страница' ||
                   aria === 'Профиль' || aria === 'Моя страница' ||
                   a.id === 'top_profile_link';
        }).map(a => a.href)''' + "'''" + ''')
    except Exception as exc:
        print('IDENTITY: profile navigation error:', type(exc).__name__, flush=True)
        return None

    candidates = set()
    for url in links:
        parsed = urlparse(url)
        if parsed.hostname in allowed and parsed.path.strip('/'):
            candidates.add(url.split('#', 1)[0].split('?', 1)[0])
    if len(candidates) != 1:
        print('IDENTITY: profile navigation missing or ambiguous:', len(candidates), flush=True)
        return None

    own_url = next(iter(candidates))
    tab = None
    try:
        tab = page.context.new_page()
        tab.goto(own_url, wait_until='domcontentloaded', timeout=30000)
        tab.wait_for_timeout(1500)
        # Verify that the destination offers owner-only profile editing.
        owner_control = tab.get_by_text('Редактировать профиль', exact=True)
        if owner_control.count() < 1 or not owner_control.first.is_visible():
            print('IDENTITY: own-profile edit control missing', flush=True)
            return None

        urls = [tab.url, own_url]
        for selector, attr in (('link[rel="canonical"]', 'href'),
                               ('meta[property="og:url"]', 'content')):
            try:
                urls.extend(tab.locator(selector).evaluate_all(
                    '(els, attr) => els.map(e => e.getAttribute(attr) || "")', attr))
            except Exception:
                pass
        ids = {n for url in urls if (n := numeric_id(url)) is not None}
        if len(ids) == 1:
            print('IDENTITY: own profile confirmed', flush=True)
            return next(iter(ids))
        print('IDENTITY: own profile ID unresolved or conflicting', flush=True)
    except Exception as exc:
        print('IDENTITY: profile verification error:', type(exc).__name__, flush=True)
    finally:
        if tab is not None:
            try:
                tab.close()
            except Exception:
                pass
    return None
'''
updated = ''.join(lines[:fn.lineno-1]) + new + ''.join(lines[fn.end_lineno:])
ast.parse(updated)
backup = path.with_name(path.name + '.backup_identity_v3_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
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
