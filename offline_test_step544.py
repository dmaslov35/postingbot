import tempfile, sqlite3
from pathlib import Path
from vk_deletion_review import collect_due,send_once
from vk_publication_registry import connect
with tempfile.TemporaryDirectory() as td:
    base=Path(td)
    (base/'runtime').mkdir()
    (base/'runtime/production.stop').touch()
    dbpath=base/'runtime/publications.sqlite3'
    with connect(dbpath) as db:
        db.execute("""INSERT INTO publications(queue_id,account_id,group_url,flow,vk_post_id,post_url,state,published_at,delete_after)
        VALUES (1,1,'https://vk.ru/club240781173','SUGGEST','-240781173_7','https://vk.ru/wall-240781173_7','PUBLISHED','2026-01-01 00:00:00','2026-01-02 00:00:00')""")
    rows=collect_due(base,'2026-02-01 00:00:00')
    assert len(rows)==1 and rows[0]['action']=='TELEGRAM_REVIEW_REQUIRED'
    calls=[]
    notify=lambda event,details:calls.append((event,details))
    assert send_once(base,notify=notify,now='2026-02-01 00:00:00')['sent']==1
    assert send_once(base,notify=notify,now='2026-02-01 00:00:00')['sent']==0
    assert len(calls)==1 and 'wall-240781173_7' in calls[0][1]
    assert '\\n' not in calls[0][1], 'Telegram содержит буквальные слеш-n'
    assert '\n' in calls[0][1], 'Нет настоящих переносов строк'
    (base/'runtime/production.stop').unlink()
    try: collect_due(base)
    except RuntimeError: pass
    else: raise AssertionError('Отсутствие stop не блокируется')
print('PASS: срок, запрет удаления, однократное уведомление, переносы строк, stop')
print('VK не вызывался, записи не удалялись')
