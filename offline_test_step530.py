from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from vk_publication_audit import audit
from vk_publication_proof import assess_publication_proof
from vk_delete_guard import assess_delete_permission

with TemporaryDirectory() as d:
    base=Path(d)
    (base/'runtime').mkdir()
    (base/'runtime/production.stop').touch()
    assert audit(base)['status']=='NO_REGISTRY'
    with sqlite3.connect(base/'runtime/publications.sqlite3') as db:
        db.execute('CREATE TABLE publications(id INTEGER,queue_id INTEGER,account_id INTEGER,group_url TEXT,flow TEXT,vk_post_id TEXT,post_url TEXT,state TEXT,delete_after TEXT)')
        db.execute('INSERT INTO publications VALUES(1,10,1,?,?,?,?,?,?)',('https://vk.ru/club123','SUGGEST','-123_9','https://vk.ru/wall-123_9','PUBLISHED','2020-01-01'))
    r=audit(base)
    assert r['total']==1 and not r['deletion_allowed'] and not r['entries'][0]['verified']
    assert 'TRUSTED_AUTHORSHIP_NOT_ESTABLISHED' in r['entries'][0]['reasons']
    assert not assess_publication_proof(10,1,-123,'message','https://vk.ru/wall-123_9',{'verified':True})['verified']
    assert not assess_delete_permission({'state':'PUBLISHED','vk_post_id':'-123_9','post_url':'https://vk.ru/wall-123_9','group_url':'https://vk.ru/club123','account_id':1,'delete_after':'2020-01-01'}, {'verified':True})['allowed']
    (base/'runtime/production.stop').unlink()
    try: audit(base)
    except RuntimeError: pass
    else: raise AssertionError('missing stop not detected')
print('PASS: 6 offline assertions; no VK calls, no publishing, no deletion')
