from pathlib import Path
import ast,hashlib,zipfile
z=zipfile.ZipFile('/opt/vkbot/vkbot_safe_patch_step524.zip')
original=z.read('original/vk_queue_dispatcher.py').decode()
patched=z.read('patched/vk_queue_dispatcher.py').decode()
a=ast.parse(original); b=ast.parse(patched)
assert len(a.body)==len(b.body)
for before,after in zip(a.body,b.body):
    if isinstance(before,(ast.FunctionDef,ast.AsyncFunctionDef)) and before.name=='notify_dispatcher':
        continue
    assert ast.dump(before)==ast.dump(after), 'Неожиданное изменение вне уведомлений'
fn=next(x for x in b.body if isinstance(x,ast.FunctionDef) and x.name=='notify_dispatcher')
seg=patched.split('def notify_dispatcher',1)[1].split('def run_one',1)[0]
assert '\\\\n' not in seg, 'Остались буквальные слеш-n'
assert 'production.stop' in patched
assert Path('/opt/vkbot/runtime/production.stop').is_file()
print('PASS: AST-структура остальных функций не изменена')
print('PASS: переносы строк Telegram исправлены')
print('PASS: production.stop на месте')
print('VK не вызывался; публикаций и удалений не было')
