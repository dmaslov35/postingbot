from pathlib import Path
from zipfile import ZipFile
from datetime import datetime
import ast
import shutil
import subprocess
import sys

base=Path('/opt/vkbot')
archive=base/'vkbot_audit_step530.zip'
assert (base/'runtime/production.stop').is_file(), 'production.stop missing'
assert archive.is_file(), 'archive missing'
with ZipFile(archive) as z:
    assert z.testzip() is None
    for name in ('vk_publication_audit.py','offline_test_step530.py'):
        content=z.read(name)
        ast.parse(content.decode('utf-8'))
        dest=base/name
        if dest.exists():
            backup=base/(name+'.bak_step530_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
            shutil.copy2(dest,backup)
            print('Backup:',backup)
        dest.write_bytes(content)
result=subprocess.run([sys.executable,str(base/'offline_test_step530.py')],cwd=base)
assert (base/'runtime/production.stop').is_file()
if result.returncode: raise SystemExit(result.returncode)
print('PASS: installed read-only audit; existing worker and dispatcher unchanged')
