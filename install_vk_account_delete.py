#!/usr/bin/env python3
"""Add safe VK-account removal to the active Telegram admin menu."""
from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys

path = Path('/opt/vkbot/telegram_admin.py')
stop = Path('/opt/vkbot/runtime/production.stop')
if not stop.is_file():
    sys.exit('STOP: runtime/production.stop отсутствует; изменения не внесены')
src = path.read_text(encoding='utf-8')
if 'vk_multi_delete_confirm:' in src:
    sys.exit('STOP: обработчик удаления уже существует; изменения не внесены')

menu_anchor = '''    keyboard.extend([
        [
            InlineKeyboardButton(
                "🔐 Авторизация",'''
if src.count(menu_anchor) != 1:
    sys.exit('STOP: не найден однозначный участок меню; изменения не внесены')
menu_button = '''    if int(account_id) != 1:
        keyboard.append([
            InlineKeyboardButton(
                "🗑 Удалить аккаунт",
                callback_data=f"vk_multi_delete_ask:{account_id}",
            )
        ])

'''
src = src.replace(menu_anchor, menu_button + menu_anchor, 1)

handler_anchor = "    elif query.data.startswith('vk_multi_auth:'):"
if src.count(handler_anchor) != 1:
    sys.exit('STOP: не найден однозначный обработчик; изменения не внесены')
handlers = '''    elif query.data.startswith('vk_multi_delete_ask:'):
        account_id = int(query.data.split(':', 1)[1])
        account = vk_multi_account(account_id)
        if account_id == 1 or not account:
            await query.answer("Удаление недоступно", show_alert=True)
        else:
            keyboard = [
                [InlineKeyboardButton(
                    "🗑 Подтвердить удаление",
                    callback_data=f"vk_multi_delete_confirm:{account_id}",
                )],
                [InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=f"vk_multi_account:{account_id}",
                )],
            ]
            await query.message.edit_text(
                f"⚠️ Удалить подключение #{account_id} «{account['name']}»?\\n\\n"
                "Аккаунт ВКонтакте и файлы профиля сохранятся. "
                "Удаление возможно только при отсутствии связанных заданий и записей.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    elif query.data.startswith('vk_multi_delete_confirm:'):
        account_id = int(query.data.split(':', 1)[1])
        ok, message = vk_multi_delete_account_safely(account_id)
        await query.answer(message[:190], show_alert=True)
        if ok:
            await show_vk_multi_accounts(query)
        else:
            await show_vk_multi_account(query, account_id)

'''
src = src.replace(handler_anchor, handlers + handler_anchor, 1)

helper_anchor = 'def vk_multi_queue_stats():'
if src.count(helper_anchor) != 1:
    sys.exit('STOP: не найдена точка вставки функции; изменения не внесены')
helper = '''def vk_multi_delete_account_safely(account_id):
    """Fail-closed removal; never delete VK profile files or publication history."""
    if int(account_id) == 1:
        return False, "Основной аккаунт защищён"
    if not Path('/opt/vkbot/runtime/production.stop').is_file():
        return False, "Остановите публикации перед удалением"

    con = vk_multi_connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        account = con.execute(
            'SELECT id, code FROM accounts WHERE id=?', (int(account_id),)
        ).fetchone()
        if account is None:
            con.rollback()
            return False, "Аккаунт уже отсутствует"

        # A removed account must not leave dangling tasks, publications,
        # account-specific settings or other references in any DB table.
        for (table_name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            if table_name == 'accounts':
                continue
            quoted_table = '"' + table_name.replace('"', '""') + '"'
            columns = {
                row[1] for row in con.execute('PRAGMA table_info(' + quoted_table + ')')
            }
            for column, value in (
                ('account_id', int(account_id)),
                ('vk_account_id', int(account_id)),
                ('account_code', account['code']),
            ):
                if column in columns and value is not None:
                    quoted_column = '"' + column.replace('"', '""') + '"'
                    count = con.execute(
                        'SELECT COUNT(*) FROM ' + quoted_table +
                        ' WHERE ' + quoted_column + '=?', (value,)
                    ).fetchone()[0]
                    if count:
                        con.rollback()
                        return False, (
                            f"Удаление заблокировано: связанные записи в {table_name} ({count})"
                        )
            # Also check declared foreign keys pointing at accounts.
            for fk in con.execute('PRAGMA foreign_key_list(' + quoted_table + ')'):
                if fk[2] == 'accounts' and fk[3] in columns:
                    fk_col = '"' + fk[3].replace('"', '""') + '"'
                    count = con.execute(
                        'SELECT COUNT(*) FROM ' + quoted_table +
                        ' WHERE ' + fk_col + '=?', (int(account_id),)
                    ).fetchone()[0]
                    if count:
                        con.rollback()
                        return False, f"Удаление заблокировано: зависимость {table_name} ({count})"

        con.execute('DELETE FROM accounts WHERE id=?', (int(account_id),))
        con.commit()
        return True, "Подключение удалено; профиль VK сохранён"
    except Exception as exc:
        con.rollback()
        return False, 'Ошибка удаления: ' + str(exc)[:120]
    finally:
        con.close()


'''
src = src.replace(helper_anchor, helper + helper_anchor, 1)
# Verify generated Telegram text uses actual newline escapes, not double-escaped slashes.
if '«{account[\'name\']}»?\\\\n' in src:
    sys.exit('STOP: обнаружено двойное экранирование перевода строки')
ast.parse(src, filename=str(path))
backup = path.with_name(path.name + '.backup_delete_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
shutil.copy2(path, backup)
path.write_text(src, encoding='utf-8')
print('PASS: резервная копия:', backup)
print('PASS: синтаксис проверен, кнопка и обработчики добавлены')
print('Публикации не запускались. production.stop сохранён.')
print('Перезапуск Telegram-сервиса требуется отдельно.')
