"""Read-only publication verification audit. Never authorizes publishing or deletion."""
import argparse
import json
import sqlite3
from pathlib import Path
from vk_post_identity import extract_post_identity

DEFAULT_BASE = Path('/opt/vkbot')

def audit(base=DEFAULT_BASE):
    base = Path(base)
    if not (base / 'runtime/production.stop').is_file():
        raise RuntimeError('production.stop missing: refusing audit')
    dbpath = base / 'runtime/publications.sqlite3'
    if not dbpath.is_file():
        return {'status': 'NO_REGISTRY', 'total': 0, 'entries': [], 'deletion_allowed': False}
    uri = dbpath.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id,queue_id,account_id,group_url,flow,vk_post_id,post_url,state,delete_after FROM publications ORDER BY id').fetchall()
    entries = []
    for row in rows:
        r = dict(row)
        reasons = []
        if r['state'] in ('PUBLISHED','DELETE_DUE','DELETED'):
            reasons.append('TRUSTED_AUTHORSHIP_NOT_ESTABLISHED')
        else:
            reasons.append('PUBLICATION_NOT_CONFIRMED')
        identity = extract_post_identity(r['post_url'])
        if r['post_url'] and identity is None:
            reasons.append('INVALID_POST_URL')
        if identity and r['vk_post_id'] != identity['vk_post_id']:
            reasons.append('POST_ID_MISMATCH')
        if not r['account_id']:
            reasons.append('MISSING_ACCOUNT_ID')
        entries.append({'id': r['id'], 'queue_id': r['queue_id'], 'state': r['state'], 'reasons': reasons, 'verified': False, 'deletion_allowed': False})
    return {'status': 'AUDIT_COMPLETE', 'total': len(entries), 'entries': entries, 'deletion_allowed': False}

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--base', default=str(DEFAULT_BASE))
    args=p.parse_args()
    print(json.dumps(audit(args.base), ensure_ascii=False, indent=2))
