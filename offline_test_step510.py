from pathlib import Path
import ast
import sys

base=Path(__file__).resolve().parent
src=(base/'vk_worker_production.py').read_text(encoding='utf-8')
node=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='inspect_submit')
ns={'pause':lambda *a:None,'assert_no_block':lambda p:None,'visible':lambda x:x,'dialog_buttons':lambda *a:True}
exec(compile(ast.Module(body=[node],type_ignores=[]),'<test>','exec'),ns)
class Page:
 def __init__(self,marker):self.marker=marker
 def get_by_text(self,text,exact=False):return exact and text==self.marker
f=ns['inspect_submit']
assert f(Page('Пост предложен'),'SUGGEST')[0]=='PENDING_MODERATION'
assert f(Page('Запись опубликована'),'SUGGEST')[0]=='UNCERTAIN'
assert f(Page('Отправлено'),'SUGGEST')[0]=='UNCERTAIN'
assert f(Page('Пост опубликован'),'CREATE')[0]=='CONFIRMED'
assert f(Page('Пост предложен'),'CREATE')[0]=='UNCERTAIN'
assert '"PENDING_MODERATION", "PROBABLE", "UNCERTAIN"' in src
assert 'raise RuntimeError' in (base/'vk_publication_registry.py').read_text().split('def confirm_publication(',1)[1].split('def get_due_deletions(',1)[0]
assert '"allowed": False' in (base/'vk_delete_guard.py').read_text()
assert 'PENDING_MODERATION' in (base/'vk_queue_dispatcher.py').read_text()
assert 'PENDING_MODERATION' in (base/'vk_queue_worker_adapter.py').read_text()
assert (base/'runtime/production.stop').is_file(), 'production.stop отсутствует'
print('PASS: 10 безопасных офлайн-проверок, VK не вызывался')
