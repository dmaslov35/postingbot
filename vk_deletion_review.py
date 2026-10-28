"""Безопасные уведомления о наступившем сроке удаления. VK не вызывается."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from vk_delete_guard import assess_delete_permission

BASE = Path('/opt/vkbot')

def collect_due(base=BASE, now=None):
    base=Path(base)
    if not (base/'runtime/production.stop').is_file():
        raise RuntimeError('production.stop отсутствует')
    dbpath=base/'runtime/publications.sqlite3'
    if not dbpath.is_file():
        return []
    now=now or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("""SELECT id,queue_id,account_id,group_url,flow,vk_post_id,
            post_url,state,delete_after FROM publications
            WHERE state IN ('PUBLISHED','DELETE_DUE','DELETE_FAILED')
              AND delete_after IS NOT NULL AND delete_after<=?
            ORDER BY delete_after,id""",(now,)).fetchall()
    out=[]
    for row in rows:
        record=dict(row)
        decision=assess_delete_permission(record)
        # Даже если защитный модуль когда-либо изменится, этот процесс НЕ удаляет.
        out.append({'id':record['id'],'post_url':record['post_url'],
            'group_url':record['group_url'],'state':record['state'],
            'delete_after':record['delete_after'],'reason':decision['reason'],
            'action':'TELEGRAM_REVIEW_REQUIRED'})
    return out

def send_once(base=BASE, notify=None, now=None):
    base=Path(base)
    entries=collect_due(base,now)
    if not entries:
        return {'due':0,'sent':0,'errors':0}
    if notify is None:
        from vk_notifications import enqueue_notification
        notify=enqueue_notification
    ledger=base/'runtime/deletion_review_notifications.sqlite3'
    with sqlite3.connect(str(ledger),timeout=10) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS sent (
            publication_id INTEGER PRIMARY KEY,
            post_url TEXT, sent_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        sent=errors=0
        for entry in entries:
            if db.execute('SELECT 1 FROM sent WHERE publication_id=?',(entry['id'],)).fetchone():
                continue
            url=entry['post_url'] or entry['group_url']
            details=(f"Публикация #{entry['id']}\n"
                     f"Срок удаления наступил: {entry['delete_after']} UTC\n"
                     f"Ссылка: {url}\n"
                     f"Автоматическое удаление заблокировано. Требуется проверка прав VK.")
            try:
                notify('DELETE_REVIEW_REQUIRED',details)
                db.execute('INSERT INTO sent(publication_id,post_url) VALUES (?,?)',
                           (entry['id'],entry['post_url']))
                db.commit()
                sent+=1
            except Exception as exc:
                print('Ошибка уведомления для публикации',entry['id'],type(exc).__name__)
                errors+=1
        return {'due':len(entries),'sent':sent,'errors':errors}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default=str(BASE))
    parser.add_argument('--notify',action='store_true',help='Отправить уведомления через существующую очередь Telegram')
    args=parser.parse_args()
    result=send_once(args.base) if args.notify else collect_due(args.base)
    print(json.dumps(result,ensure_ascii=False,indent=2))
