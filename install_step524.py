from pathlib import Path
import ast, hashlib, shutil, sys
from datetime import datetime
from zipfile import ZipFile
BASE=Path('/opt/vkbot'); STOP=BASE/'runtime/production.stop'; TARGET=BASE/'vk_queue_dispatcher.py'
ARCHIVE=BASE/'vkbot_safe_patch_step524.zip'
assert STOP.is_file(), 'ОТКАЗ: production.stop отсутствует'
assert TARGET.is_file() and ARCHIVE.is_file()
with ZipFile(ARCHIVE) as z:
    new=z.read('patched/vk_queue_dispatcher.py')
    old_hash=z.read('original.sha256').decode().strip()
old=TARGET.read_bytes()
assert hashlib.sha256(old).hexdigest()==old_hash, 'ОТКАЗ: серверный файл отличается от присланного архива'
ast.parse(new.decode('utf-8'))
assert old != new
backup=TARGET.with_name(TARGET.name+'.bak_step524_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
shutil.copy2(TARGET,backup)
try:
    TARGET.write_bytes(new)
    assert STOP.is_file()
    assert TARGET.read_bytes()==new
    compile(new.decode('utf-8'),str(TARGET),'exec')
except Exception:
    shutil.copy2(backup,TARGET)
    raise
print('PASS: уведомления исправлены')
print('Резервная копия:',backup)
print('production.stop: НА МЕСТЕ')
print('Публикации и удаления не включались')
