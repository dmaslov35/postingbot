from pathlib import Path
import ast
import shutil
from datetime import datetime

path = Path('/opt/vkbot/vk_account_auth.py')
src = path.read_text(encoding='utf-8')
tree = ast.parse(src)
fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verified_self_id'), None)
if fn is None:
    raise SystemExit('STOP: verified_self_id not found')
old = ''.join(src.splitlines(keepends=True)[fn.lineno-1:fn.end_lineno])
if 'a#top_profile_link' not in old or 'return next(iter(found))' not in old:
    raise SystemExit('STOP: function differs from expected version')
new = '''def verified_self_id(page):
    """Resolve only a dedicated SELF profile link; fail closed on ambiguity."""
    import re
    from urllib.parse import urlparse

    allowed = {'vk.ru', 'www.vk.ru', 'vk.com', 'www.vk.com'}
    if any(x in (page.url or '').lower() for x in ('login', 'id.vk.com', 'challenge', 'captcha')):
        return None

    selectors = (
        'a#top_profile_link',
        'a[data-testid="header-avatar"]',
        'a[aria-label="Моя страница"]',
    )
    self_links = set()
    for selector in selectors:
        try:
            hrefs = page.locator(selector).evaluate_all('(els) => els.map(e => e.href)')
            for href in hrefs:
                u = urlparse(href)
                if u.hostname in allowed and u.path.strip('/'):
                    self_links.add(href.split('#', 1)[0].split('?', 1)[0])
        except Exception:
            pass
    if len(self_links) != 1:
        print('IDENTITY: self-profile link missing or ambiguous', flush=True)
        return None

    self_url = next(iter(self_links))
    u = urlparse(self_url)
    direct = re.fullmatch(r'/id([1-9][0-9]*)/?', u.path)
    if direct:
        return int(direct.group(1))

    # Short profile URLs must be resolved from that exact self-profile page,
    # never from arbitrary numeric links in the news feed.
    tab = None
    try:
        tab = page.context.new_page()
        tab.goto(self_url, wait_until='domcontentloaded', timeout=25000)
        tab.wait_for_timeout(1500)
        candidates = [tab.url]
        for selector, attribute in (
            ('link[rel="canonical"]', 'href'),
            ('meta[property="og:url"]', 'content'),
        ):
            try:
                candidates += tab.locator(selector).evaluate_all(
                    '(els, attr) => els.map(e => e.getAttribute(attr) || "")', attribute
                )
            except Exception:
                pass
        ids = set()
        for candidate in candidates:
            parsed = urlparse(candidate)
            if parsed.hostname not in allowed:
                continue
            match = re.fullmatch(r'/id([1-9][0-9]*)/?', parsed.path)
            if match:
                ids.add(int(match.group(1)))
        if len(ids) == 1:
            return next(iter(ids))
        print('IDENTITY: self-profile short URL unresolved', flush=True)
    except Exception as exc:
        print('IDENTITY: self-profile resolution error:', type(exc).__name__, flush=True)
    finally:
        if tab is not None:
            try:
                tab.close()
            except Exception:
                pass
    return None
'''
updated = src.replace(old, new, 1)
ast.parse(updated)
backup = path.with_name(path.name + '.backup_identity_v2_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
shutil.copy2(path, backup)
path.write_text(updated, encoding='utf-8')
print('PATCHED:', path)
print('BACKUP:', backup)
print('PASS: Python syntax')
print('NOTICE: Does not alter browser profiles, database or production.stop')
