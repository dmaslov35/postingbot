from pathlib import Path
from zipfile import ZipFile
from datetime import datetime
import ast,hashlib,shutil,subprocess,sys
base=Path('/opt/vkbot'); archive=base/'vkbot_step544.zip'
assert (base/'runtime/production.stop').is_file(),'production.stop отсутствует'
with ZipFile(archive) as z:
    assert z.testzip() is None
    for name in ('vk_deletion_review.py','offline_test_step544.py'):
        content=z.read(name)
        ast.parse(content.decode('utf-8'))
        dest=base/name
        if dest.exists():
            backup=base/(name+'.bak_step544_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
            shutil.copy2(dest,backup)
            print('Резервная копия:',backup)
        dest.write_bytes(content)
result=subprocess.run([sys.executable,str(base/'offline_test_step544.py')],cwd=base)
assert (base/'runtime/production.stop').is_file()
if result.returncode: raise SystemExit(result.returncode)
print('PASS: модуль установлен; рабочие файлы не изменялись; автоудаление выключено')
