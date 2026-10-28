import asyncio
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

BOT_TOKEN = config['telegram']['bot_token']

# Поддержка списка администраторов
if 'admin_ids' in config['telegram']:
    ADMIN_IDS = config['telegram']['admin_ids']
else:
    ADMIN_IDS = [config['telegram']['admin_id']]

def load_settings():
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'post_interval': 30, 'check_interval': 7200, 'delete_delay': 10}

def save_settings(settings):
    with open('settings.json', 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def load_stats():
    try:
        with open('bot_stats.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'success': 0, 'errors': [], 'accounts_status': {}}

def load_groups():
    try:
        from openpyxl import load_workbook
        wb = load_workbook('chats.xlsx')
        sheet = wb.active
        groups = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0]:
                groups.append(int(row[0]))
        return groups
    except:
        return []

def load_messages():
    try:
        from openpyxl import load_workbook
        wb = load_workbook('messages.xlsx')
        sheet = wb.active
        messages = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0]:
                messages.append(str(row[0]))
        return messages
    except:
        return []

def save_messages(messages):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Messages'
    ws.append(['message'])
    for msg in messages:
        ws.append([msg])
    wb.save('messages.xlsx')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещён")
        return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Тексты", callback_data='messages_menu')],
        [InlineKeyboardButton("⏱️ Настройки времени", callback_data='settings_menu')],
        [InlineKeyboardButton("📋 Группы со ссылками", callback_data='groups_menu')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("👥 Аккаунты", callback_data='accounts')],
        [InlineKeyboardButton("📈 Логи", callback_data='logs')],
        [InlineKeyboardButton("⏸️ Пауза", callback_data='pause'),
         InlineKeyboardButton("▶️ Продолжить", callback_data='resume')],
        [InlineKeyboardButton("🔄 Перезапуск", callback_data='restart')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text("🤖 Панель управления ВК-ботом\n\nВыберите действие:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("🤖 Панель управления ВК-ботом\n\nВыберите действие:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    if query.data == 'main_menu':
        await show_main_menu(update, context)
    
    elif query.data == 'messages_menu':
        keyboard = [
            [InlineKeyboardButton("📋 Список текстов", callback_data='show_messages_page_0')],
            [InlineKeyboardButton("➕ Добавить текст", callback_data='add_message')],
            [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("📝 Управление текстами\n\nВыберите действие:", reply_markup=reply_markup)
    
    elif query.data.startswith('show_messages_page_'):
        page = int(query.data.split('_')[-1])
        messages = load_messages()
        
        if not messages:
            text = "📝 Текстов нет"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='messages_menu')]]
        else:
            per_page = 10
            total_pages = (len(messages) + per_page - 1) // per_page
            start = page * per_page
            end = start + per_page
            page_messages = messages[start:end]
            
            text = f"📝 Тексты (страница {page+1}/{total_pages})\nВсего: {len(messages)}\n\n"
            
            keyboard = []
            for i, msg in enumerate(page_messages, start + 1):
                preview = msg[:50].replace('\n', ' ') + "..." if len(msg) > 50 else msg.replace('\n', ' ')
                keyboard.append([InlineKeyboardButton(f"{i}. {preview}", callback_data=f'view_message_{i}')])
            
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f'show_messages_page_{page-1}'))
            if len(messages) > end:
                nav_row.append(InlineKeyboardButton("След. ➡️", callback_data=f'show_messages_page_{page+1}'))
            if nav_row:
                keyboard.append(nav_row)
            
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='messages_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data.startswith('view_message_'):
        msg_num = int(query.data.split('_')[-1])
        messages = load_messages()
        
        if 1 <= msg_num <= len(messages):
            msg = messages[msg_num - 1]
            text = f" Текст #{msg_num}:\n\n{msg}"
            
            keyboard = [
                [InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_message_{msg_num}')],
                [InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_message_{msg_num}')],
                [InlineKeyboardButton("◀️ К списку", callback_data='show_messages_page_0')]
            ]
        else:
            text = "❌ Текст не найден"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='messages_menu')]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data.startswith('edit_message_'):
        msg_num = int(query.data.split('_')[-1])
        context.user_data['action'] = f'edit_message_{msg_num}'
        
        messages = load_messages()
        if 1 <= msg_num <= len(messages):
            msg = messages[msg_num - 1]
            text = f"✏️ Редактирование текста #{msg_num}\n\nТекущий текст:\n{msg[:100]}...\n\nОтправьте новый текст:\n\n(Отмена: /cancel)"
        else:
            text = "❌ Текст не найден"
        
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f'view_message_{msg_num}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data.startswith('delete_message_'):
        msg_num = int(query.data.split('_')[-1])
        messages = load_messages()
        
        if 1 <= msg_num <= len(messages):
            deleted = messages.pop(msg_num - 1)
            save_messages(messages)
            text = f"✅ Текст #{msg_num} удалён:\n\n{deleted[:100]}..."
        else:
            text = "❌ Текст не найден"
        
        keyboard = [[InlineKeyboardButton("◀️ К списку", callback_data='show_messages_page_0')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'add_message':
        context.user_data['action'] = 'add_message'
        text = " Отправьте текст сообщения:\n\n(Отмена: /cancel)"
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data='messages_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'settings_menu':
        settings = load_settings()
        text = f"⏱️ Текущие настройки:\n\n"
        text += f"• Пауза между постами: {settings['post_interval']} сек\n"
        text += f"• Интервал проверки: {settings['check_interval'] // 3600} ч\n"
        text += f"• Время перед удалением: {settings['delete_delay']} мин\n\n"
        text += "Что изменить?"
        keyboard = [
            [InlineKeyboardButton("Пауза между постами", callback_data='set_post_interval')],
            [InlineKeyboardButton("Интервал проверки", callback_data='set_check_interval')],
            [InlineKeyboardButton("Время перед удалением", callback_data='set_delete_delay')],
            [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'set_post_interval':
        context.user_data['action'] = 'set_post_interval'
        text = "⏱️ Введите паузу (сек):\n\n(Отмена: /cancel)"
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data='settings_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'set_check_interval':
        context.user_data['action'] = 'set_check_interval'
        text = "⏱️ Введите интервал (часов):\n\n(Отмена: /cancel)"
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data='settings_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'set_delete_delay':
        context.user_data['action'] = 'set_delete_delay'
        text = "⏱️ Введите время (мин):\n\n(Отмена: /cancel)"
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data='settings_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'groups_menu':
        groups = load_groups()
        if not groups:
            text = "📋 Групп нет"
            keyboard = [[InlineKeyboardButton("️ Назад", callback_data='main_menu')]]
        else:
            per_page = 15
            page = 0
            start = page * per_page
            end = start + per_page
            page_groups = groups[start:end]
            total_pages = (len(groups) + per_page - 1) // per_page
            
            text = f"📋 Группы ({page+1}/{total_pages})\nВсего: {len(groups)}\n\n"
            keyboard = []
            for i, g in enumerate(page_groups, start + 1):
                link = f"https://vk.com/club{abs(g)}"
                keyboard.append([InlineKeyboardButton(f"{i}. {g}", url=link)])
            
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("️", callback_data=f'groups_page_{page-1}'))
            if len(groups) > end:
                nav_row.append(InlineKeyboardButton("➡️", callback_data=f'groups_page_{page+1}'))
            if nav_row:
                keyboard.append(nav_row)
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='main_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data.startswith('groups_page_'):
        page = int(query.data.split('_')[-1])
        groups = load_groups()
        
        if not groups:
            text = "📋 Групп нет"
            keyboard = [[InlineKeyboardButton("️ Назад", callback_data='main_menu')]]
        else:
            per_page = 15
            start = page * per_page
            end = start + per_page
            page_groups = groups[start:end]
            total_pages = (len(groups) + per_page - 1) // per_page
            
            text = f"📋 Группы ({page+1}/{total_pages})\nВсего: {len(groups)}\n\n"
            keyboard = []
            for i, g in enumerate(page_groups, start + 1):
                link = f"https://vk.com/club{abs(g)}"
                keyboard.append([InlineKeyboardButton(f"{i}. {g}", url=link)])
            
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("⬅️", callback_data=f'groups_page_{page-1}'))
            if len(groups) > end:
                nav_row.append(InlineKeyboardButton("➡️", callback_data=f'groups_page_{page+1}'))
            if nav_row:
                keyboard.append(nav_row)
            keyboard.append([InlineKeyboardButton("️ Назад", callback_data='main_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'stats':
        stats = load_stats()
        success = stats.get('success', 0)
        errors = stats.get('errors', [])
        text = f"📊 Статистика:\n\n✅ Успешных постов: {success}\n❌ Ошибок: {len(errors)}\n\n"
        if errors:
            text += "Последние ошибки:\n"
            for err in errors[-5:]:
                text += f"• Группа {err['group']}: {err['error'][:50]}\n"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'accounts':
        stats = load_stats()
        accounts = stats.get('accounts_status', {})
        text = "👥 Статус аккаунтов:\n\n"
        if accounts:
            for acc_id, status in accounts.items():
                emoji = "✅" if status == "OK" else "❌"
                text += f"{emoji} {acc_id}: {status}\n"
        else:
            text += "Нет данных. Запустите бота."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'logs':
        try:
            with open('logs/bot.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-20:] if len(lines) >= 20 else lines
                log_text = ''.join(last_lines)
            text = f" Последние 20 строк:\n\n<pre>{log_text}</pre>"
        except:
            text = "Логов пока нет"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, parse_mode='HTML', reply_markup=reply_markup)
    
    elif query.data == 'pause':
        if not os.path.exists('pause.flag'):
            open('pause.flag', 'w').close()
            text = "⏸️ Бот на паузе"
        else:
            text = "⏸️ Уже на паузе"
        keyboard = [[InlineKeyboardButton("️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'resume':
        if os.path.exists('pause.flag'):
            os.remove('pause.flag')
            text = "▶️ Бот возобновил работу"
        else:
            text = "▶️ Уже работает"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'restart':
        text = "🔄 Как перезапустить:\n\n1. Остановить: Ctrl+C\n2. Запустить: python3 bot.py"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    action = context.user_data.get('action')
    
    if action == 'add_message':
        text = update.message.text
        messages = load_messages()
        messages.append(text)
        save_messages(messages)
        await update.message.reply_text(f"✅ Текст добавлен!\n\nВсего: {len(messages)}")
        context.user_data['action'] = None
    
    elif action and action.startswith('edit_message_'):
        msg_num = int(action.split('_')[-1])
        new_text = update.message.text
        messages = load_messages()
        
        if 1 <= msg_num <= len(messages):
            messages[msg_num - 1] = new_text
            save_messages(messages)
            await update.message.reply_text(f"✅ Текст #{msg_num} обновлён!")
        else:
            await update.message.reply_text("❌ Текст не найден")
        
        context.user_data['action'] = None
    
    elif action == 'set_post_interval':
        try:
            seconds = int(update.message.text)
            settings = load_settings()
            settings['post_interval'] = seconds
            save_settings(settings)
            await update.message.reply_text(f"✅ Пауза: {seconds} сек")
        except:
            await update.message.reply_text("❌ Введите число")
        context.user_data['action'] = None
    
    elif action == 'set_check_interval':
        try:
            hours = int(update.message.text)
            settings = load_settings()
            settings['check_interval'] = hours * 3600
            save_settings(settings)
            await update.message.reply_text(f"✅ Интервал: {hours} ч")
        except:
            await update.message.reply_text("❌ Введите число")
        context.user_data['action'] = None
    
    elif action == 'set_delete_delay':
        try:
            minutes = int(update.message.text)
            settings = load_settings()
            settings['delete_delay'] = minutes
            save_settings(settings)
            await update.message.reply_text(f"✅ Время удаления: {minutes} мин")
        except:
            await update.message.reply_text("❌ Введите число")
        context.user_data['action'] = None

def main():
    print("Telegram админка запущена")
    print(f"Администраторы: {ADMIN_IDS}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('cancel', lambda u, c: show_main_menu(u, c)))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == '__main__':
    main()
