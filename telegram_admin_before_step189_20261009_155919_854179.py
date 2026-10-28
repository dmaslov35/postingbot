import asyncio
import subprocess
import sqlite3
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from pathlib import Path
from datetime import datetime

with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

BOT_TOKEN = config['telegram']['bot_token']

# Поддержка списка администраторов
if 'admin_ids' in config['telegram']:
    ADMIN_IDS = config['telegram']['admin_ids']
else:
    ADMIN_IDS = [config['telegram']['admin_id']]

from account_lifecycle_lock import account_lifecycle_exclusive
from posts_transaction_lock import published_posts_shared

def load_config_fresh():
    """Всегда читает актуальный config.json."""
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config_atomic(new_config):
    """Атомарно сохраняет config.json и не оставляет временный файл."""
    import tempfile

    config_path = os.path.abspath('config.json')
    config_dir = os.path.dirname(config_path)

    fd, tmp_path = tempfile.mkstemp(
        prefix='.config.',
        suffix='.tmp',
        dir=config_dir,
        text=True,
    )

    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(
                new_config,
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())

        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, config_path)
        os.chmod(config_path, 0o600)

    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


# CONFIG TRANSACTION CORE V1
CONFIG_LOCK_PATH = "/opt/vkbot/.config.lock"


def mutate_config_locked(mutator):
    """
    Serialize read-modify-write operations on config.json.

    mutator(cfg) may modify cfg in memory and return
    any result needed by the caller.

    The lock covers:
        fresh load
        mutation
        atomic save

    No VK API calls are performed here.
    """
    import fcntl

    lock_path = CONFIG_LOCK_PATH

    with open(
        lock_path,
        "a+",
        encoding="utf-8",
    ) as lock_file:
        os.chmod(lock_path, 0o600)

        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            cfg = load_config_fresh()

            if not isinstance(cfg, dict):
                raise ValueError(
                    "config root is not an object"
                )

            changed, result = mutator(cfg)

            if changed:
                save_config_atomic(cfg)

            return result

        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


# ACCOUNT TRANSACTION OPERATIONS V1
# CALLBACK MIGRATION V1


def _normalize_vk_user_id(user_id):
    try:
        value = int(user_id)
    except (TypeError, ValueError):
        return None

    if value <= 0:
        return None

    return value


def _find_account_index_by_user_id(accounts, user_id):
    target = _normalize_vk_user_id(user_id)

    if target is None:
        return None

    if not isinstance(accounts, list):
        return None

    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue

        current = _normalize_vk_user_id(
            account.get("user_id")
        )

        if current == target:
            return index

    return None


# SAFETY HELPERS RESTORED V1

def validate_account_for_enable(account):
    """
    Offline-only validation.
    Does NOT call VK API.
    """
    errors = []

    if not isinstance(account, dict):
        return False, [
            "Некорректная структура аккаунта."
        ]

    user_id = _normalize_vk_user_id(
        account.get("user_id")
    )

    if user_id is None:
        errors.append(
            "Некорректный VK ID."
        )

    token = account.get("token")

    if (
        not isinstance(token, str)
        or not token.strip()
    ):
        errors.append(
            "Токен не установлен."
        )

    phone = account.get("phone")

    if (
        not isinstance(phone, str)
        or not phone.strip()
    ):
        errors.append(
            "Телефон не указан."
        )

    return len(errors) == 0, errors


def get_pending_posts_for_account(user_id):
    """
    Fail-closed local queue check.
    Does NOT call VK API.

    Returns:
      >= 0  number of unfinished posts
      -1    queue cannot be checked safely
    """
    normalized_user_id = (
        _normalize_vk_user_id(user_id)
    )

    if normalized_user_id is None:
        return -1

    target = str(normalized_user_id)

    with published_posts_shared():
        try:
            with open(
                "published_posts.json",
                "r",
                encoding="utf-8",
            ) as f:
                posts = json.load(f)

        except FileNotFoundError:
            return 0

        except Exception:
            return -1

    if not isinstance(posts, list):
        return -1

    count = 0

    for post in posts:
        if not isinstance(post, dict):
            continue

        post_user_id = (
            _normalize_vk_user_id(
                post.get("account_user_id")
            )
        )

        if post_user_id is None:
            continue

        if str(post_user_id) != target:
            continue

        status = str(
            post.get(
                "status",
                "pending",
            )
        ).lower()

        if status not in {
            "deleted",
            "not_found",
        }:
            count += 1

    return count


def tx_add_vk_account_disabled(user_id, phone):
    normalized_id = _normalize_vk_user_id(user_id)

    if normalized_id is None:
        return {
            "status": "bad_user_id",
        }

    if not isinstance(phone, str):
        return {
            "status": "bad_phone",
        }

    normalized_phone = phone.strip()

    if (
        not normalized_phone
        or len(normalized_phone) > 40
    ):
        return {
            "status": "bad_phone",
        }

    def mutator(cfg):
        accounts = cfg.get("vk_accounts")

        if not isinstance(accounts, list):
            raise ValueError(
                "vk_accounts is not a list"
            )

        index = _find_account_index_by_user_id(
            accounts,
            normalized_id,
        )

        if index is not None:
            return False, {
                "status": "duplicate",
                "user_id": normalized_id,
            }

        accounts.append({
            "user_id": normalized_id,
            "phone": normalized_phone,
            "token": "",
            "enabled": False,
        })

        return True, {
            "status": "saved",
            "user_id": normalized_id,
        }

    return mutate_config_locked(mutator)


def tx_disable_vk_account(user_id):
    normalized_id = _normalize_vk_user_id(user_id)

    if normalized_id is None:
        return {
            "status": "bad_user_id",
        }

    def mutator(cfg):
        accounts = cfg.get("vk_accounts")

        if not isinstance(accounts, list):
            raise ValueError(
                "vk_accounts is not a list"
            )

        index = _find_account_index_by_user_id(
            accounts,
            normalized_id,
        )

        if index is None:
            return False, {
                "status": "not_found",
            }

        if accounts[index].get("enabled") is False:
            return False, {
                "status": "disabled",
                "user_id": normalized_id,
            }

        accounts[index]["enabled"] = False

        return True, {
            "status": "disabled",
            "user_id": normalized_id,
        }

    with account_lifecycle_exclusive(normalized_id):
        return mutate_config_locked(mutator)


def tx_set_vk_account_enabled(user_id, enabled):
    normalized_id = _normalize_vk_user_id(user_id)

    if normalized_id is None:
        return {
            "status": "bad_user_id",
        }

    desired = bool(enabled)

    def mutator(cfg):
        accounts = cfg.get("vk_accounts")

        if not isinstance(accounts, list):
            raise ValueError(
                "vk_accounts is not a list"
            )

        index = _find_account_index_by_user_id(
            accounts,
            normalized_id,
        )

        if index is None:
            return False, {
                "status": "not_found",
            }

        account = accounts[index]

        if desired:
            ready, errors = (
                validate_account_for_enable(
                    account
                )
            )

            if not ready:
                changed = (
                    account.get("enabled")
                    is not False
                )

                account["enabled"] = False

                return changed, {
                    "status": "not_ready",
                    "user_id": normalized_id,
                    "errors": list(errors),
                }

        if account.get("enabled") is desired:
            return False, {
                "status": (
                    "enabled"
                    if desired
                    else "disabled"
                ),
                "user_id": normalized_id,
            }

        account["enabled"] = desired

        return True, {
            "status": (
                "enabled"
                if desired
                else "disabled"
            ),
            "user_id": normalized_id,
        }

    with account_lifecycle_exclusive(normalized_id):
        return mutate_config_locked(mutator)



def tx_delete_vk_account(user_id):
    normalized_user_id = _normalize_vk_user_id(user_id)

    if normalized_user_id is None:
        return {
            "status": "bad_user_id",
            "user_id": user_id,
        }

    with account_lifecycle_exclusive(
        normalized_user_id
    ):
        # Phase 1:
        # inspect the CURRENT config under CONFIG EX.
        # If enabled, this action only disables it.
        def inspect_or_disable(cfg):
            accounts = cfg.get("vk_accounts")

            if not isinstance(accounts, list):
                return False, {
                    "status": "bad_config",
                    "user_id": normalized_user_id,
                }

            index = _find_account_index_by_user_id(
                accounts,
                normalized_user_id,
            )

            if index is None:
                return False, {
                    "status": "not_found",
                    "user_id": normalized_user_id,
                }

            account = accounts[index]

            if account.get("enabled") is True:
                account["enabled"] = False

                return True, {
                    "status": "disabled_first",
                    "user_id": normalized_user_id,
                }

            return False, {
                "status": "ready_for_queue_check",
                "user_id": normalized_user_id,
            }

        first_result = mutate_config_locked(
            inspect_or_disable
        )

        if not isinstance(first_result, dict):
            return {
                "status": "bad_config",
                "user_id": normalized_user_id,
            }

        if (
            first_result.get("status")
            != "ready_for_queue_check"
        ):
            return first_result

        # ACCOUNT EX is still held here.
        #
        # Any publication for this UID requires ACCOUNT SH
        # and holds it through save_new_post(), therefore
        # no same-UID post can appear between this queue
        # check and the final config transaction.
        #
        # CONFIG is NOT held while POSTS SH is acquired.
        pending = get_pending_posts_for_account(
            normalized_user_id
        )

        if pending < 0:
            return {
                "status": "queue_error",
                "user_id": normalized_user_id,
            }

        if pending > 0:
            return {
                "status": "pending_posts",
                "user_id": normalized_user_id,
                "pending_posts": pending,
            }

        # Phase 2:
        # ACCOUNT EX is still held.
        # Re-open CONFIG EX only after POSTS SH has been
        # released by get_pending_posts_for_account().
        #
        # Revalidate everything against fresh config.
        def hard_delete(cfg):
            accounts = cfg.get("vk_accounts")

            if not isinstance(accounts, list):
                return False, {
                    "status": "bad_config",
                    "user_id": normalized_user_id,
                }

            index = _find_account_index_by_user_id(
                accounts,
                normalized_user_id,
            )

            if index is None:
                return False, {
                    "status": "not_found",
                    "user_id": normalized_user_id,
                }

            account = accounts[index]

            # Fail closed if state unexpectedly changed.
            if account.get("enabled") is True:
                return False, {
                    "status": "state_changed",
                    "user_id": normalized_user_id,
                }

            accounts.pop(index)

            return True, {
                "status": "deleted",
                "user_id": normalized_user_id,
            }

        return mutate_config_locked(hard_delete)



# RESTORED UI HELPERS V2

def get_vk_accounts():
    cfg = load_config_fresh()
    accounts = cfg.get('vk_accounts', [])

    if not isinstance(accounts, list):
        return []

    return accounts


def account_label(account, index):
    user_id = account.get('user_id')
    enabled = account.get('enabled', True)

    emoji = '🟢' if enabled else '⏸️'

    if user_id:
        return f"{emoji} #{index + 1} · ID {user_id}"

    return f"{emoji} #{index + 1} · без ID"



async def show_accounts_menu(query):
    accounts = get_vk_accounts()

    if not accounts:
        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ Добавить аккаунт",
                    callback_data="account_add",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="accounts",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Назад",
                    callback_data="main_menu",
                )
            ],
        ]

        await query.edit_message_text(
            "👥 VK-аккаунты\n\n"
            "Список аккаунтов пуст.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    keyboard = []

    for index, account in enumerate(accounts):
        user_id = _normalize_vk_user_id(
            account.get("user_id")
        )

        # Invalid records must never receive a mutable
        # account callback.
        if user_id is None:
            continue

        keyboard.append(
            [
                InlineKeyboardButton(
                    account_label(account, index),
                    callback_data=(
                        f"account_view_uid_{user_id}"
                    ),
                )
            ]
        )

    keyboard.extend(
        [
            [
                InlineKeyboardButton(
                    "➕ Добавить аккаунт",
                    callback_data="account_add",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="accounts",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Назад",
                    callback_data="main_menu",
                )
            ],
        ]
    )

    await query.edit_message_text(
        "👥 VK-аккаунты\n\n"
        f"Всего: {len(accounts)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )




async def show_account_card(query, user_id):
    normalized_user_id = _normalize_vk_user_id(user_id)

    if normalized_user_id is None:
        await query.edit_message_text(
            "⚠️ Некорректный VK ID.\n\n"
            "Обновите список аккаунтов.",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "◀️ К аккаунтам",
                        callback_data="accounts",
                    )
                ]]
            ),
        )
        return

    accounts = get_vk_accounts()

    index = _find_account_index_by_user_id(
        accounts,
        normalized_user_id,
    )

    if index is None:
        await query.edit_message_text(
            "⚠️ Аккаунт больше не найден.\n\n"
            "Список был изменён другим действием. "
            "Обновите его.",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "◀️ К аккаунтам",
                        callback_data="accounts",
                    )
                ]]
            ),
        )
        return

    account = accounts[index]

    phone = account.get("phone") or "не указан"
    enabled = account.get("enabled") is True
    token = account.get("token")

    status = "🟢 включён" if enabled else "⚪ выключен"
    token_status = (
        "✅ установлен"
        if isinstance(token, str) and token.strip()
        else "❌ не установлен"
    )

    text = (
        f"👤 VK-аккаунт #{index + 1}\n\n"
        f"ID: {normalized_user_id}\n"
        f"Телефон: {phone}\n"
        f"Статус: {status}\n"
        f"Токен: {token_status}"
    )

    keyboard = []

    if enabled:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "⏸ Выключить",
                    callback_data=(
                        f"account_disable_uid_"
                        f"{normalized_user_id}"
                    ),
                )
            ]
        )
    else:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "▶️ Включить",
                    callback_data=(
                        f"account_enable_ask_uid_"
                        f"{normalized_user_id}"
                    ),
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🗑 Удалить",
                callback_data=(
                    f"account_delete_ask_uid_"
                    f"{normalized_user_id}"
                ),
            )
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton(
                "◀️ К аккаунтам",
                callback_data="accounts",
            )
        ]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )




# ============================================================
# VK WORKER PANEL V1
# READ ONLY / PRODUCTION LOCKED
#
# Этот раздел:
# - НЕ запускает VK Worker
# - НЕ публикует посты
# - НЕ подписывается
# - НЕ отправляет заявки
# - НЕ включает Production
# ============================================================

VK_WORKER_DIR = Path(
    os.environ.get("VK_WORKER_DIR", "/opt/vkbot")
)

VK_WORKER_STATE_FILES = [
    VK_WORKER_DIR / "vk_worker_final_state.json",
    VK_WORKER_DIR / "vk_worker_v3_state.json",
]

VK_WORKER_LOG_FILES = [
    VK_WORKER_DIR / "vk_worker_final.log",
    VK_WORKER_DIR / "vk_worker_v3.log",
]


def _vk_worker_existing(paths):
    for path in paths:
        try:
            if path.exists():
                return path
        except Exception:
            pass

    return None


def _vk_worker_load_json(path):
    if path is None:
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)
    except Exception:
        return None


def _vk_worker_rows(data):
    if not isinstance(data, dict):
        return []

    # Поддерживаем несколько форматов state-файлов.
    for key in (
        "groups",
        "states",
        "items",
        "results",
    ):
        value = data.get(key)

        if isinstance(value, dict):
            rows = []

            for url, item in value.items():
                if not isinstance(item, dict):
                    continue

                row = dict(item)
                row.setdefault("url", url)
                rows.append(row)

            return rows

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    # Некоторые версии worker хранят:
    # URL -> state прямо в корне JSON.
    rows = []

    for url, item in data.items():
        if (
            isinstance(url, str)
            and url.startswith("http")
            and isinstance(item, dict)
        ):
            row = dict(item)
            row.setdefault("url", url)
            rows.append(row)

    return rows


def vk_worker_status_text():
    state_path = _vk_worker_existing(
        VK_WORKER_STATE_FILES
    )

    log_path = _vk_worker_existing(
        VK_WORKER_LOG_FILES
    )

    state_data = _vk_worker_load_json(
        state_path
    )

    lines = [
        "🤖 VK Worker",
        "",
        "🔒 Автоматическая публикация: ЗАБЛОКИРОВАН",
    ]

    def fmt_time(value):
        if not value or value == "—":
            return "—"

        try:
            dt = datetime.fromisoformat(
                str(value)
            )
            return dt.strftime(
                "%d.%m.%Y %H:%M:%S"
            )
        except Exception:
            return str(value)

    if state_path is None:
        lines.extend([
            "",
            "🌉 Bridge: 🔴 OFFLINE",
            "🕒 Последняя связь: —",
            "",
            "📊 State-файл worker пока "
            "не найден на сервере.",
        ])

    elif not isinstance(state_data, dict):
        lines.extend([
            "",
            "🌉 Bridge: 🔴 OFFLINE",
            "🕒 Последняя связь: —",
            "",
            f"📊 State: {state_path.name}",
            "❌ State-файл не удалось прочитать.",
        ])

    else:
        updated_at = (
            state_data.get("updated_at")
            or "—"
        )

        source = state_data.get(
            "source",
            "unknown",
        )

        bridge_version = state_data.get(
            "bridge_version",
            "—",
        )

        controller_enabled = bool(
            state_data.get(
                "controller_enabled",
                False,
            )
        )

        # ====================================================
        # BRIDGE ONLINE/OFFLINE
        #
        # Bridge V3 currently reports approximately every
        # 10 seconds. 90 seconds gives enough margin for
        # network/SSH delays without showing false OFFLINE.
        # ====================================================

        bridge_online = False
        bridge_age_seconds = None

        # ONLINE/OFFLINE определяем по времени изменения
        # state-файла на самом Linux-сервере.
        # Так часовые пояса Windows/Linux не влияют
        # на результат.
        try:
            import time

            bridge_age_seconds = max(
                0,
                time.time() - state_path.stat().st_mtime,
            )

            bridge_online = (
                bridge_age_seconds <= 90
            )

        except Exception:
            bridge_online = False

        bridge_label = (
            "🟢 ONLINE"
            if bridge_online
            else "🔴 OFFLINE"
        )

        worker_running = bool(
            state_data.get(
                "worker_running",
                False,
            )
        )

        worker_file = (
            state_data.get("worker_file")
            or "—"
        )

        worker_pid = state_data.get(
            "worker_pid"
        )

        groups_total = state_data.get(
            "groups_total",
            0,
        )

        groups_in_state = state_data.get(
            "groups_in_state",
            0,
        )

        create_count = state_data.get(
            "create_count",
            0,
        )

        suggest_count = state_data.get(
            "suggest_count",
            0,
        )

        subscribed_count = state_data.get(
            "subscribed_count",
            0,
        )

        not_subscribed_count = state_data.get(
            "not_subscribed_count",
            0,
        )

        unknown_subscription_count = (
            state_data.get(
                "unknown_subscription_count",
                0,
            )
        )

        error_count = state_data.get(
            "error_count",
            0,
        )

        scan_status = state_data.get(
            "last_scan_status",
            "NOT_FOUND",
        )

        scan_finished = (
            state_data.get(
                "last_scan_finished_at"
            )
            or "—"
        )

        post_attempts = state_data.get(
            "post_attempts",
            0,
        )

        last_command = (
            state_data.get("last_command")
            or "—"
        )

        last_command_at = (
            state_data.get("last_command_at")
            or "—"
        )

        last_result_data = state_data.get(
            "last_command_result"
        )

        # ====================================================
        # LAST COMMAND RESULT
        # ====================================================

        if isinstance(last_result_data, dict):
            result_name = (
                last_result_data.get("result")
                or "—"
            )

            result_ok = last_result_data.get(
                "ok"
            )

            if result_ok is True:
                last_result_label = (
                    f"✅ {result_name}"
                )
            elif result_ok is False:
                last_result_label = (
                    f"❌ {result_name}"
                )
            else:
                last_result_label = str(
                    result_name
                )

        elif last_result_data:
            last_result_label = str(
                last_result_data
            )

        else:
            last_result_label = "—"

        scan_label = {
            "COMPLETED": "ЗАВЕРШЁН",
            "RUNNING": "ВЫПОЛНЯЕТСЯ",
            "NOT_FOUND": "НЕТ ДАННЫХ",
        }.get(
            str(scan_status).upper(),
            str(scan_status),
        )

        worker_label = (
            "🟢 ONLINE"
            if worker_running
            else "⚪ ОСТАНОВЛЕН"
        )

        controller_label = (
            "АКТИВЕН"
            if controller_enabled
            else "НЕ АКТИВЕН"
        )

        lines.extend([
            "",
            f"🌉 Bridge V{bridge_version}: "
            f"{bridge_label}",
            f"🕒 Последняя связь: "
            f"{fmt_time(updated_at)}",
        ])

        if bridge_age_seconds is not None:
            age = max(
                0,
                int(bridge_age_seconds),
            )

            lines.append(
                f"⏱ Возраст отчёта: {age} сек."
            )

        lines.extend([
            "",
            f"💻 Windows Worker: "
            f"{worker_label}",
            f"📄 Worker: {worker_file}",
        ])

        if worker_running and worker_pid:
            lines.append(
                f"🆔 PID: {worker_pid}"
            )

        lines.extend([
            "",
            f"🎛 SCAN-контроллер: "
            f"{controller_label}",
            f"📡 Последняя команда: "
            f"{last_command}",
            f"🕒 Команда получена: "
            f"{fmt_time(last_command_at)}",
            f"📬 Результат: "
            f"{last_result_label}",
            "",
            f"✅ Последний Проверка сообществ: "
            f"{scan_label}",
            f"🕒 SCAN завершён: "
            f"{fmt_time(scan_finished)}",
            "",
            f"📋 Групп в списке: "
            f"{groups_total}",
            f"📊 Групп со статусом: "
            f"{groups_in_state}",
            "",
            f"📝 CREATE: {create_count}",
            f"📨 SUGGEST: {suggest_count}",
            "",
            f"🟢 Подписаны: "
            f"{subscribed_count}",
            f"⚪ Не подписаны: "
            f"{not_subscribed_count}",
            f"❔ Статус неизвестен: "
            f"{unknown_subscription_count}",
            f"❌ Ошибок: {error_count}",
            "",
            f"🚫 POST ATTEMPTS: "
            f"{post_attempts}",
            "",
            "🛡 Публикация из Telegram: "
            "ОТКЛЮЧЕНА",
            "🛡 Подписки из Telegram: "
            "ОТКЛЮЧЕНЫ",
            "🛡 Join-заявки из Telegram: "
            "ОТКЛЮЧЕНЫ",
            "🛡 CREATE submit: "
            "ОТКЛЮЧЕН",
            "",
            f"📊 State: {state_path.name}",
            f"💻 Источник: {source}",
        ])

    lines.append("")

    if log_path is None:
        lines.append(
            "📜 Журнал событий пока не найден"
        )
    else:
        lines.append(
            f"📜 Журнал событий: {log_path.name}"
        )

    lines.extend([
        "",
        "🎛 Управление: только START/STOP "
        "безопасного SCAN.",
        "🔒 Публикация и другие изменения "
        "VK заблокированы.",
    ])

    return "\n".join(lines)



def vk_worker_log_summary():
    """Краткое представление журнала без исходных технических строк."""
    path = _vk_worker_existing(VK_WORKER_LOG_FILES)

    if path is None:
        return "📋 Журнал событий\n\nЗаписей пока нет."

    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            records = file.readlines()[-200:]
    except OSError:
        return "❌ Не удалось прочитать журнал событий."

    events = []

    for raw in records:
        low = raw.strip().lower()

        if not low:
            continue

        if "auth_required" in low:
            message = "🔐 Аккаунту требуется авторизация"
        elif "review_required" in low:
            message = "🔎 Задание требует проверки"
        elif "error" in low or "traceback" in low:
            message = "❌ Зафиксирована ошибка"
        elif "warning" in low or "warn" in low:
            message = "⚠️ Зафиксировано предупреждение"
        elif "production=locked" in low or "master lock" in low:
            message = "🔒 Автоматическая публикация заблокирована"
        elif "start" in low:
            message = "▶️ Запуск рабочего процесса"
        elif "finish" in low or "complete" in low:
            message = "🏁 Рабочий процесс завершён"
        else:
            continue

        if not events or events[-1] != message:
            events.append(message)

    if not events:
        return (
            "📋 Журнал событий\n\n"
            "Понятных событий пока нет.\n"
            "Подробности доступны в техническом журнале."
        )

    return (
        "📋 Журнал событий\n\n"
        + "\n".join(events[-12:])
        + "\n\nПодробности доступны в техническом журнале."
    )


def vk_worker_log_text():
    path = _vk_worker_existing(
        VK_WORKER_LOG_FILES
    )

    if path is None:
        return (
            "📈 Лог VK Worker пока "
            "не найден на сервере."
        )

    try:
        with path.open(
            "r",
            encoding="utf-8",
            errors="replace",
        ) as f:
            lines = f.readlines()

        tail = "".join(
            lines[-20:]
        ).strip()

    except Exception as exc:
        return (
            "❌ Не удалось прочитать "
            "worker log.\n\n"
            f"Ошибка: {type(exc).__name__}"
        )

    if not tail:
        tail = "(лог пуст)"

    # Не превышаем безопасный размер
    # сообщения Telegram.
    if len(tail) > 3200:
        tail = tail[-3200:]

    return (
        f"📈 Последние строки "
        f"{path.name}\n\n"
        f"{tail}"
    )



# ============================================================
# VK WORKER REMOTE SCAN CONTROL V1
# ONLY SCAN_START / SCAN_STOP
# ============================================================

VK_WORKER_COMMAND_FILE = (
    VK_WORKER_DIR / "vk_worker_command.json"
)

VK_WORKER_ALLOWED_COMMANDS = {
    "SCAN_START",
    "SCAN_STOP",
}


def vk_worker_write_command(command, admin_id=None):
    command = str(command).strip().upper()

    if command not in VK_WORKER_ALLOWED_COMMANDS:
        raise ValueError(
            f"VK Worker command is not allowed: {command}"
        )

    request_id = datetime.now().strftime(
        "%Y%m%d%H%M%S%f"
    )

    payload = {
        "id": request_id,
        "command": command,
        "created_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "source": "telegram_admin",
        "admin_id": admin_id,
    }

    tmp_path = VK_WORKER_COMMAND_FILE.with_name(
        VK_WORKER_COMMAND_FILE.name + ".tmp"
    )

    with tmp_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.flush()
        os.fsync(f.fileno())

    os.replace(
        tmp_path,
        VK_WORKER_COMMAND_FILE,
    )

    return payload




# ============================================================
# VK PRODUCTION TELEGRAM CONTROL V1
#
# Telegram may START/STOP the production systemd service,
# but the production launcher remains the final authority.
#
# While PRODUCTION_MASTER_UNLOCKED=False the START request
# cannot result in VK publication.
# ============================================================

VK_SCAN_SERVICE = "vkbot-cloud-scan.service"
VK_PRODUCTION_SERVICE = "vkbot-production.service"


def _vk_systemctl_is_active(service):
    try:
        result = subprocess.run(
            [
                "systemctl",
                "is-active",
                "--quiet",
                service,
            ],
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _vk_systemctl_action(action, service):
    if action not in {"start", "stop"}:
        raise ValueError(
            f"Unsupported systemctl action: {action}"
        )

    result = subprocess.run(
        [
            "systemctl",
            action,
            service,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    return {
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def vk_production_running():
    return _vk_systemctl_is_active(
        VK_PRODUCTION_SERVICE
    )


def vk_scan_running():
    return _vk_systemctl_is_active(
        VK_SCAN_SERVICE
    )


def vk_production_start():
    # Hard mutual exclusion.
    if vk_scan_running():
        return {
            "ok": False,
            "status": "SCAN_RUNNING",
            "message": (
                "SCAN сейчас работает. "
                "Production не запущен."
            ),
        }

    if vk_production_running():
        return {
            "ok": True,
            "status": "ALREADY_RUNNING",
            "message": "Автоматическая публикация уже запущена.",
        }

    result = _vk_systemctl_action(
        "start",
        VK_PRODUCTION_SERVICE,
    )

    # Give systemd a moment to execute the launcher.
    import time
    time.sleep(1)

    running = vk_production_running()

    if running:
        return {
            "ok": True,
            "status": "STARTED",
            "message": "Служба автоматической публикации запущена.",
        }

    # With MASTER LOCK=False this is the expected result:
    # launcher exits and service becomes inactive/failed.
    try:
        status_result = subprocess.run(
            [
                "systemctl",
                "show",
                VK_PRODUCTION_SERVICE,
                "--property=ExecMainStatus",
                "--value",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

        exit_code = (
            status_result.stdout or ""
        ).strip()

    except Exception:
        exit_code = ""

    if exit_code == "20":
        return {
            "ok": False,
            "status": "MASTER_LOCKED",
            "message": (
                "Production launcher отклонил запуск: "
                "MASTER LOCK закрыт."
            ),
        }

    details = (
        result.get("stderr")
        or result.get("stdout")
        or "service завершился"
    )

    return {
        "ok": False,
        "status": "START_FAILED",
        "message": details[:500],
    }


def vk_production_stop():
    result = _vk_systemctl_action(
        "stop",
        VK_PRODUCTION_SERVICE,
    )

    if vk_production_running():
        return {
            "ok": False,
            "status": "STOP_FAILED",
            "message": (
                result.get("stderr")
                or "Автоматическая публикация всё ещё работает."
            )[:500],
        }

    return {
        "ok": True,
        "status": "STOPPED",
        "message": "Автоматическая публикация остановлена.",
    }


def vk_production_status_text():
    prod = vk_production_running()
    scan = vk_scan_running()

    return (
        "⚙️ Автоматическая публикация\n\n"
        f"Автоматическая публикация: "
        f"{'🟢 РАБОТАЕТ' if prod else '⚪ ОСТАНОВЛЕН'}\n"
        f"Проверка сообществ: "
        f"{'🟢 РАБОТАЕТ' if scan else '⚪ ОСТАНОВЛЕН'}\n\n"
        "🔐 Финальное разрешение публикации "
        "контролируется production launcher.\n"
        "SCAN и Production одновременно "
        "не запускаются."
    )



# ============================================================
# VKBOT MULTI ACCOUNT TELEGRAM PANEL FINAL V1
# ============================================================

VK_MULTI_DB = Path(
    "/opt/vkbot/vk_multi_account.sqlite3"
)

VK_MULTI_MANAGER = Path(
    "/opt/vkbot/vk_multi_account.py"
)

VK_MULTI_PYTHON = Path(
    "/opt/vkbot/venv/bin/python"
)


def vk_multi_connect():
    con = sqlite3.connect(
        str(VK_MULTI_DB),
        timeout=10,
    )
    con.row_factory = sqlite3.Row
    return con


def vk_multi_accounts():
    if not VK_MULTI_DB.exists():
        return []

    con = vk_multi_connect()

    try:
        return con.execute(
            """
            SELECT *
            FROM accounts
            ORDER BY id
            """
        ).fetchall()
    finally:
        con.close()


def vk_multi_account(account_id):
    con = vk_multi_connect()

    try:
        return con.execute(
            """
            SELECT *
            FROM accounts
            WHERE id=?
            """,
            (int(account_id),),
        ).fetchone()
    finally:
        con.close()


def vk_multi_queue_stats():
    stats = {
        "WAITING": 0,
        "RUNNING": 0,
        "DONE": 0,
        "FAILED": 0,
        "SKIPPED": 0,
        "AUTH_REQUIRED": 0,
        "REVIEW_REQUIRED": 0,
    }

    if not VK_MULTI_DB.exists():
        return stats

    con = vk_multi_connect()

    try:
        rows = con.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM queue
            GROUP BY status
            """
        ).fetchall()

        for row in rows:
            stats[str(row["status"])] = int(
                row["n"]
            )

        return stats
    finally:
        con.close()


def vk_multi_queue_recent(limit=8):
    if not VK_MULTI_DB.exists():
        return []

    con = vk_multi_connect()

    try:
        return con.execute(
            """
            SELECT
                q.*,
                a.code AS account_code
            FROM queue q
            LEFT JOIN accounts a
              ON a.id=q.account_id
            ORDER BY q.id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        con.close()


def vk_multi_set_enabled(account_id, enabled):
    con = vk_multi_connect()

    try:
        account = con.execute(
            """
            SELECT *
            FROM accounts
            WHERE id=?
            """,
            (int(account_id),),
        ).fetchone()

        if not account:
            return False, "Аккаунт не найден"

        if enabled:
            if account["auth_status"] != "AUTHORIZED":
                return (
                    False,
                    "Сначала авторизуйте VK-аккаунт",
                )

            status = "READY"
        else:
            status = "PAUSED"

        con.execute(
            """
            UPDATE accounts
            SET enabled=?,
                status=?,
                updated_at=?
            WHERE id=?
            """,
            (
                1 if enabled else 0,
                status,
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                int(account_id),
            ),
        )

        con.commit()

        return (
            True,
            "Аккаунт включён"
            if enabled
            else "Аккаунт приостановлен",
        )

    finally:
        con.close()


def vk_multi_clear_queue():
    if vk_production_running():
        return (
            False,
            "Сначала остановите автоматическую публикацию",
        )

    con = vk_multi_connect()

    try:
        running = con.execute(
            """
            SELECT COUNT(*)
            FROM queue
            WHERE status='RUNNING'
            """
        ).fetchone()[0]

        if running:
            return (
                False,
                "В очереди есть выполняющееся задание",
            )

        cur = con.execute(
            """
            DELETE FROM queue
            WHERE status='WAITING'
            """
        )

        con.commit()

        return (
            True,
            f"Удалено заданий: {cur.rowcount}",
        )

    finally:
        con.close()


def vk_multi_fill_queue():
    if vk_production_running():
        return (
            False,
            "Автоматическая публикация сейчас работает",
        )

    result = subprocess.run(
        [
            str(VK_MULTI_PYTHON),
            str(VK_MULTI_MANAGER),
            "queue-file",
        ],
        cwd="/opt/vkbot",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    output = (
        (result.stdout or "")
        + "\n"
        + (result.stderr or "")
    ).strip()

    if result.returncode != 0:
        return (
            False,
            output[-1000:]
            or "Ошибка формирования очереди",
        )

    return True, output



# VK MULTI TELEGRAM ADD WIZARD V1

def vk_multi_make_code(name):
    """
    Generate safe unique account code:
    account2, account3, ...
    """
    accounts = vk_multi_accounts()

    existing = {
        str(a["code"]).strip().lower()
        for a in accounts
    }

    number = 1

    while True:
        code = f"account{number}"

        if code not in existing:
            return code

        number += 1


def vk_multi_create_account(name):
    name = str(name or "").strip()

    if not name:
        return False, "Название не может быть пустым", None

    if len(name) > 60:
        return False, "Название слишком длинное", None

    code = vk_multi_make_code(name)

    result = subprocess.run(
        [
            str(VK_MULTI_PYTHON),
            str(VK_MULTI_MANAGER),
            "add-account",
            code,
            name,
        ],
        cwd="/opt/vkbot",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    output = (
        (result.stdout or "")
        + "\n"
        + (result.stderr or "")
    ).strip()

    if result.returncode != 0:
        return (
            False,
            output[-1000:]
            or "Не удалось создать аккаунт",
            None,
        )

    accounts = vk_multi_accounts()

    created = None

    for account in reversed(accounts):
        if str(account["code"]) == code:
            created = account
            break

    if created is None:
        return (
            False,
            "Аккаунт создан, но не найден в базе",
            None,
        )

    # Новый аккаунт НЕ должен участвовать
    # в очереди до прохождения авторизации.
    con = vk_multi_connect()

    try:
        con.execute(
            """
            UPDATE accounts
            SET enabled=0,
                auth_status='UNKNOWN',
                status='AUTH_REQUIRED',
                updated_at=?
            WHERE id=?
            """,
            (
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                int(created["id"]),
            ),
        )

        con.commit()

    finally:
        con.close()

    return (
        True,
        f"Создан аккаунт {code}",
        int(created["id"]),
    )


def vk_multi_auth_command(account_id):
    return (
        "DISPLAY=:99 "
        "/opt/vkbot/venv/bin/python "
        "/opt/vkbot/vk_account_auth.py "
        f"{int(account_id)}"
    )



# VK MULTI ACCOUNT TELEGRAM AUTH V2

def vk_multi_auth_service_name(account_id):
    return (
        "vkbot-account-auth@"
        f"{int(account_id)}.service"
    )


def vk_multi_auth_service_active(account_id):
    service = vk_multi_auth_service_name(
        account_id
    )

    result = subprocess.run(
        [
            "systemctl",
            "is-active",
            service,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    return (
        result.stdout.strip()
        == "active"
    )


def vk_multi_prepare_auth(account_id):
    account = vk_multi_account(
        account_id
    )

    if not account:
        return False, "Аккаунт не найден"

    # Пока авторизация не подтверждена,
    # аккаунт запрещён для очереди.
    con = vk_multi_connect()

    try:
        con.execute(
            """
            UPDATE accounts
            SET enabled=0,
                auth_status='AUTH_REQUIRED',
                status='AUTH_REQUIRED',
                updated_at=?
            WHERE id=?
            """,
            (
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                int(account_id),
            ),
        )

        con.commit()

    finally:
        con.close()

    service = vk_multi_auth_service_name(
        account_id
    )

    subprocess.run(
        [
            "systemctl",
            "reset-failed",
            service,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    result = subprocess.run(
        [
            "systemctl",
            "start",
            service,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    if result.returncode != 0:
        error = (
            (result.stderr or "")
            + "\n"
            + (result.stdout or "")
        ).strip()

        return (
            False,
            error[-800:]
            or "Не удалось запустить авторизацию"
        )

    return (
        True,
        "Сессия авторизации запущена"
    )


def vk_multi_stop_auth(account_id):
    service = vk_multi_auth_service_name(
        account_id
    )

    subprocess.run(
        [
            "systemctl",
            "stop",
            service,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def vk_multi_auth_log(account_id):
    service = vk_multi_auth_service_name(
        account_id
    )

    result = subprocess.run(
        [
            "journalctl",
            "-u",
            service,
            "-n",
            "25",
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    return (
        (result.stdout or "")
        + "\n"
        + (result.stderr or "")
    )


def vk_multi_force_safe_auth_states():
    """
    Любой аккаунт без AUTHORIZED не может быть enabled.
    """
    con = vk_multi_connect()

    try:
        con.execute(
            """
            UPDATE accounts
            SET enabled=0,
                status='AUTH_REQUIRED'
            WHERE COALESCE(auth_status, '') != 'AUTHORIZED'
            """
        )

        con.commit()

    finally:
        con.close()


vk_multi_force_safe_auth_states()



def vk_account_status_ru(account):
    auth = str(account["auth_status"] or "").upper()
    status = str(account["status"] or "").upper()

    if not bool(account["enabled"]):
        return "⚪ Отключён"
    if auth != "AUTHORIZED":
        return "🔴 Требуется вход в VK"
    if status == "READY":
        return "🟢 Готов к работе"
    if status in ("ERROR", "FAILED"):
        return "🔴 Ошибка подключения"
    return "🟡 Требуется проверка"


def vk_auth_status_ru(value):
    labels = {
        "AUTHORIZED": "✅ Выполнена",
        "AUTH_REQUIRED": "🔴 Требуется вход",
    }
    return labels.get(str(value or "").upper(), "🟡 Не проверена")

async def show_vk_multi_menu(query):
    accounts = vk_multi_accounts()
    stats = vk_multi_queue_stats()

    authorized = sum(
        1 for a in accounts
        if a["auth_status"] == "AUTHORIZED"
    )

    enabled = sum(
        1 for a in accounts
        if bool(a["enabled"])
    )

    text = (
        "📊 Управление VK-аккаунтами\n\n"
        f"👤 Аккаунтов: {len(accounts)}\n"
        f"🟢 Включено: {enabled}\n"
        f"🔐 Авторизовано: {authorized}\n\n"
        f"⏳ Ожидают: {stats.get('WAITING', 0)}\n"
        f"⚙️ Выполняются: {stats.get('RUNNING', 0)}\n"
        f"✅ Завершены: {stats.get('DONE', 0)}\n"
        f"🔎 Требуют проверки: {stats.get('REVIEW_REQUIRED', 0)}\n"
        f"❌ Ошибки: {stats.get('FAILED', 0)}\n\n"
        f"Проверка сообществ: "
        f"{'🟢 Выполняется' if vk_scan_running() else '⏸ Остановлена'}\n"
        f"Автоматическая публикация: "
        f"{'🟢 Выполняется' if vk_production_running() else '⏸ Остановлена'}\n\n"
        "🔒 Автоматическая публикация заблокирована."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "👤 Аккаунты",
                callback_data="vk_multi_accounts",
            ),
            InlineKeyboardButton(
                "📋 Очередь",
                callback_data="vk_multi_queue",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="vk_multi",
            ),
        ],
        [
            InlineKeyboardButton(
                "◀️ Публикации",
                callback_data="vk_worker",
            ),
        ],
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


async def show_vk_multi_accounts(query):
    accounts = vk_multi_accounts()

    lines = [
        "👤 Подключённые VK-аккаунты",
        "",
    ]

    keyboard = []

    if not accounts:
        lines.append("Аккаунтов нет.")

    for account in accounts:
        auth = account["auth_status"] or "UNKNOWN"
        status = account["status"] or "UNKNOWN"

        if auth != "AUTHORIZED":
            icon = "🔐"
        elif account["enabled"]:
            icon = "🟢"
        else:
            icon = "⏸"

        lines.extend([
            (
                f"{icon} #{account['id']} "
                f"{account['name']}"
            ),
            f"Обозначение: {account['code']}",
            f"Авторизация: {vk_auth_status_ru(auth)}",
            f"Состояние: {vk_account_status_ru(account)}",
            "",
        ])

        keyboard.append([
            InlineKeyboardButton(
                f"👤 #{account['id']} {account['name'][:20]}",
                callback_data=(
                    f"vk_multi_account:{account['id']}"
                ),
            )
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(
                "➕ Добавить аккаунт",
                callback_data="vk_multi_add_help",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="vk_multi_accounts",
            ),
            InlineKeyboardButton(
                "◀️ Назад",
                callback_data="vk_multi",
            ),
        ],
    ])

    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


async def show_vk_multi_account(query, account_id):
    account = vk_multi_account(account_id)

    if not account:
        await query.answer(
            "Аккаунт не найден",
            show_alert=True,
        )
        return

    text = (
        "👤 VK-аккаунт\n\n"
        f"ID: #{account['id']}\n"
        f"Название: {account['name']}\n"
        f"Код: {account['code']}\n"
        f"Авторизация: {vk_auth_status_ru(account['auth_status'])}\n"
        f"Состояние: {vk_account_status_ru(account)}\n"
        f"Включён: "
        f"{'ДА' if account['enabled'] else 'НЕТ'}\n\n"
        "🔒 Данные профиля хранятся на сервере"
    )

    keyboard = []

    if account["enabled"]:
        keyboard.append([
            InlineKeyboardButton(
                "⏸ Приостановить",
                callback_data=(
                    f"vk_multi_pause:{account_id}"
                ),
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                "▶️ Включить",
                callback_data=(
                    f"vk_multi_enable:{account_id}"
                ),
            )
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(
                "🔐 Авторизация",
                callback_data=(
                    f"vk_multi_auth:{account_id}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "◀️ К аккаунтам",
                callback_data="vk_multi_accounts",
            )
        ],
    ])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )



def vk_queue_status_ru(value):
    labels = {
        "WAITING": "⏳ Ожидает отправки",
        "RUNNING": "⚙️ Выполняется",
        "DONE": "✅ Задание завершено",
        "FAILED": "❌ Ошибка выполнения",
        "SKIPPED": "⏭ Пропущено",
        "AUTH_REQUIRED": "🔐 Требуется вход в VK",
        "REVIEW_REQUIRED": "🔎 Требует проверки",
    }
    return labels.get(
        str(value or "").upper(),
        "🟡 Неизвестное состояние"
    )


def vk_queue_account_ru(value):
    if not value or str(value).upper() == "AUTO":
        return "Аккаунт выбирается автоматически"
    return "Аккаунт: " + str(value)

async def show_vk_multi_queue(query):
    stats = vk_multi_queue_stats()
    rows = vk_multi_queue_recent()

    lines = [
        "📋 Очередь публикаций",
        "",
        f"⏳ Ожидают: {stats.get('WAITING', 0)}",
        f"⚙️ Выполняются: {stats.get('RUNNING', 0)}",
        f"✅ Завершены: {stats.get('DONE', 0)}",
        f"🔎 Требуют проверки: {stats.get('REVIEW_REQUIRED', 0)}",
        f"❌ Ошибки: {stats.get('FAILED', 0)}",
        f"⏭ Пропущены: {stats.get('SKIPPED', 0)}",
        (
            "🔐 Нужна авторизация: "
            f"{stats.get('AUTH_REQUIRED', 0)}"
        ),
    ]

    if rows:
        lines.extend([
            "",
            "Последние задания (не все завершённые подтверждены VK):",
        ])

        for row in rows:
            group = row["group_url"] or ""

            if len(group) > 34:
                group = group[:31] + "..."

            lines.append(
                f"#{row['id']} "
                f"{vk_queue_status_ru(row['status'])} | "
                f"{vk_queue_account_ru(row['account_code'])} → "
                f"{group}"
            )

    keyboard = [
        [
            InlineKeyboardButton(
                "➕ Сформировать очередь",
                callback_data="vk_multi_queue_fill_ask",
            )
        ],
        [
            InlineKeyboardButton(
                "🧹 Очистить ожидающие",
                callback_data="vk_multi_queue_clear_ask",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="vk_multi_queue",
            ),
            InlineKeyboardButton(
                "◀️ Назад",
                callback_data="vk_multi",
            ),
        ],
    ]

    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


async def show_vk_worker_menu(query):
    accounts = vk_multi_accounts()
    stats = vk_multi_queue_stats()

    authorized = sum(
        1 for account in accounts
        if account["auth_status"] == "AUTHORIZED"
        and bool(account["enabled"])
    )

    waiting = stats.get("WAITING", 0)
    running = stats.get("RUNNING", 0)
    done = stats.get("DONE", 0)
    review = stats.get("REVIEW_REQUIRED", 0)
    failed = stats.get("FAILED", 0)

    production_running = vk_production_running()
    scan_running = vk_scan_running()

    if production_running:
        status = "🟢 Работает"
    else:
        status = "🔒 Остановлена"

    text = (
        "⚙️ Управление публикациями\n\n"
        f"Автоматическая публикация: {status}\n"
        f"👥 Активных VK-аккаунтов: {authorized}\n"
        f"📋 Ожидают отправки: {waiting}\n"
        f"⚙️ Выполняются: {running}\n"
        f"✅ Задания завершены: {done}\n"
        f"🔎 Требуют проверки: {review}\n"
        f"❌ Ошибки: {failed}\n\n"
        "🔍 Проверка сообществ: "
        + ("🟢 Работает" if scan_running else "⚪ Остановлена")
        + "\n\n"
        "Публикации запускаются только после "
        "завершения настройки и проверки безопасности."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📋 Очередь",
                callback_data="vk_multi_queue"
            ),
            InlineKeyboardButton(
                "👥 VK-аккаунты",
                callback_data="vk_multi_accounts"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Отчёт",
                callback_data="vk_production_status"
            ),
            InlineKeyboardButton(
                "📜 Журнал событий",
                callback_data="vk_worker_log"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="vk_worker_status"
            ),
        ],
        [
            InlineKeyboardButton(
                "◀️ Главное меню",
                callback_data="main_menu"
            ),
        ],
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def load_settings():
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'post_interval': 30, 'check_interval': 7200, 'delete_delay': 10}

def save_settings(settings):
    import json
    import os
    import shutil
    import tempfile
    from pathlib import Path
    from datetime import datetime

    if not isinstance(settings, dict):
        raise ValueError("Настройки должны быть словарём")

    limits = {
        "post_interval": (10, 86400),
        "check_interval": (3600, 604800),
        "delete_delay": (1, 10080),
    }

    for key, (minimum, maximum) in limits.items():
        value = settings.get(key)

        if type(value) is not int:
            raise ValueError(f"Некорректное значение {key}")

        if not minimum <= value <= maximum:
            raise ValueError(f"Значение {key} вне допустимого диапазона")

    target = Path(__file__).resolve().parent / "settings.json"
    backup_dir = target.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=".settings_",
        suffix=".json",
        dir=str(target.parent)
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())

        with open(temporary, encoding="utf-8") as file:
            verified = json.load(file)

        if verified != settings:
            raise RuntimeError("Проверка настроек не пройдена")

        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = backup_dir / f"settings_before_save_{stamp}.json"
            shutil.copy2(target, backup)

        os.replace(temporary, target)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

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
    from openpyxl import Workbook, load_workbook
    from pathlib import Path
    from datetime import datetime
    import tempfile
    import shutil
    import os

    target = Path(__file__).resolve().parent / "messages.xlsx"
    backup_dir = target.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Messages"
    ws.append(["message"])

    for message in messages:
        ws.append([message])

    fd, temp_path = tempfile.mkstemp(
        prefix=".messages_",
        suffix=".xlsx",
        dir=str(target.parent)
    )
    os.close(fd)

    try:
        wb.save(temp_path)

        check = load_workbook(temp_path, read_only=True)
        try:
            actual = [
                str(row[0])
                for row in check.active.iter_rows(
                    min_row=2, values_only=True
                )
                if row[0] is not None
            ]
        finally:
            check.close()

        if actual != [str(m) for m in messages]:
            raise RuntimeError("Проверка сохранённых данных не пройдена")

        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = backup_dir / f"messages_before_save_{stamp}.xlsx"
            shutil.copy2(target, backup)

        os.replace(temp_path, target)
    finally:
        wb.close()
        if os.path.exists(temp_path):
            os.unlink(temp_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещён")
        return
    await show_main_menu(update, context)

async def show_main_menu(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "📝 Объявления",
                callback_data="messages_menu"
            ),
            InlineKeyboardButton(
                "📋 Сообщества",
                callback_data="groups_menu"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 VK-аккаунты",
                callback_data="vk_multi_accounts"
            ),
            InlineKeyboardButton(
                "⏱️ Настройки времени",
                callback_data="settings_menu"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Статистика",
                callback_data="stats"
            ),
            InlineKeyboardButton(
                "📤 Публикации",
                callback_data="vk_worker"
            ),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "🤖 Панель управления ВК\n\n"
        "Управление объявлениями, сообществами "
        "и публикациями.\n\n"
        "⏸ Автопубликация временно остановлена.\n\n" "Выберите нужный раздел 👇"
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Сбрасываем ожидание текстового ввода при выходе из формы.
    if query.data in ("main_menu", "settings_menu", "messages_menu"):
        context.user_data.pop("action", None)
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
        msg_num = int(query.data.rsplit("_", 1)[-1])
        messages = load_messages()

        if 1 <= msg_num <= len(messages):
            preview = messages[msg_num - 1][:200]

            text = (
                f"⚠️ Удалить объявление №{msg_num}?\n\n"
                f"{preview}\n\n"
                "Подтвердите удаление."
            )

            keyboard = [
                [InlineKeyboardButton(
                    "🗑️ Подтвердить удаление",
                    callback_data=f"confirm_delete_message_{msg_num}"
                )],
                [InlineKeyboardButton(
                    "◀️ Отмена",
                    callback_data=f"view_message_{msg_num}"
                )]
            ]
        else:
            text = "❌ Объявление не найдено"
            keyboard = [[InlineKeyboardButton(
                "◀️ К списку",
                callback_data="show_messages_page_0"
            )]]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("confirm_delete_message_"):
        msg_num = int(query.data.rsplit("_", 1)[-1])
        messages = load_messages()

        if 1 <= msg_num <= len(messages):
            messages.pop(msg_num - 1)
            save_messages(messages)
            text = f"✅ Объявление №{msg_num} удалено."
        else:
            text = "❌ Объявление не найдено"

        keyboard = [[InlineKeyboardButton(
            "◀️ К списку",
            callback_data="show_messages_page_0"
        )]]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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
        per_page = 10
        total_pages = max(1, (len(groups) + per_page - 1) // per_page)
        page = max(0, min(0, total_pages - 1))
        start = page * per_page
        page_groups = groups[start:start + per_page]

        text = (
            f"📋 Сообщества VK\n"
            f"Всего: {len(groups)} | Страница {page + 1}/{total_pages}\n\n"
        )

        keyboard = []

        if not groups:
            text += "Список сообществ пуст."
        else:
            text += "Нажмите кнопку с номером, чтобы открыть сообщество VK.\n\n"

            for index, group_id in enumerate(page_groups, start + 1):
                text += f"{index}. club{abs(group_id)}\n"

            for offset in range(0, len(page_groups), 2):
                row = []
                for position in range(offset, min(offset + 2, len(page_groups))):
                    group_id = page_groups[position]
                    number = start + position + 1
                    row.append(
                        InlineKeyboardButton(
                            f"🔗 {number}. club{abs(group_id)}",
                            url=f"https://vk.com/club{abs(group_id)}"
                        )
                    )
                keyboard.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton("⬅️", callback_data=f"groups_page_{page-1}")
            )
        if page + 1 < total_pages:
            nav_row.append(
                InlineKeyboardButton("➡️", callback_data=f"groups_page_{page+1}")
            )
        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([
            InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)    
    elif query.data.startswith('groups_page_'):
        groups = load_groups()
        per_page = 10
        total_pages = max(1, (len(groups) + per_page - 1) // per_page)
        page = max(0, min(int(query.data.rsplit('_', 1)[-1]), total_pages - 1))
        start = page * per_page
        page_groups = groups[start:start + per_page]

        text = (
            f"📋 Сообщества VK\n"
            f"Всего: {len(groups)} | Страница {page + 1}/{total_pages}\n\n"
        )

        keyboard = []

        if not groups:
            text += "Список сообществ пуст."
        else:
            text += "Нажмите кнопку с номером, чтобы открыть сообщество VK.\n\n"

            for index, group_id in enumerate(page_groups, start + 1):
                text += f"{index}. club{abs(group_id)}\n"

            for offset in range(0, len(page_groups), 2):
                row = []
                for position in range(offset, min(offset + 2, len(page_groups))):
                    group_id = page_groups[position]
                    number = start + position + 1
                    row.append(
                        InlineKeyboardButton(
                            f"🔗 {number}. club{abs(group_id)}",
                            url=f"https://vk.com/club{abs(group_id)}"
                        )
                    )
                keyboard.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton("⬅️", callback_data=f"groups_page_{page-1}")
            )
        if page + 1 < total_pages:
            nav_row.append(
                InlineKeyboardButton("➡️", callback_data=f"groups_page_{page+1}")
            )
        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([
            InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)    
    elif query.data == 'stats':
        import sqlite3 as _stats_sqlite3

        stats = load_stats()
        historical_success = stats.get("success", 0)
        historical_errors = stats.get("errors", [])
        if not isinstance(historical_errors, list):
            historical_errors = []

        current_total = 0
        confirmed = 0
        state_counts = {}
        db_file = "/opt/vkbot/runtime/publications.sqlite3"
        db_available = False

        try:
            from pathlib import Path as _StatsPath
            if _StatsPath(db_file).is_file():
                with _stats_sqlite3.connect(
                    "file:" + db_file + "?mode=ro", uri=True
                ) as _stats_db:
                    db_available = True
                    rows = _stats_db.execute(
                        "SELECT state, COUNT(*) FROM publications GROUP BY state"
                    ).fetchall()
                    state_counts = {str(k): int(v) for k, v in rows}
                    current_total = sum(state_counts.values())
                    confirmed = state_counts.get("PUBLISHED_CONFIRMED", 0)
        except Exception:
            db_available = False

        text = "📊 Статистика\n\n"
        text += "🆕 Новая система\n"
        if db_available:
            text += f"📋 Зарегистрировано попыток: {current_total}\n"
            text += f"✅ Подтверждённых публикаций: {confirmed}\n"
            if state_counts:
                text += "Статусы записей:\n"
                for state, count in sorted(state_counts.items()):
                    text += f"• {state}: {count}\n"
        else:
            text += "⚠️ База публикаций недоступна\n"

        text += "\n📚 Историческая статистика старого бота\n"
        text += f"Счётчик успешных операций: {historical_success}\n"
        text += f"Записей об ошибках: {len(historical_errors)}\n"
        text += "Эти цифры не подтверждают публикации новой системы.\n"

        if _StatsPath("/opt/vkbot/runtime/production.stop").exists():
            text += "\n⛔ Автопубликация остановлена"

        keyboard = [[InlineKeyboardButton(
            "◀️ Назад", callback_data="main_menu"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup)
    
    elif query.data == 'accounts':
        await show_accounts_menu(query)

    # STABLE IDENTITY V2
    elif query.data.startswith(
        "account_view_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]

        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            await show_account_card(query, user_id)

    elif query.data.startswith(
        "account_disable_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]
        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            result = tx_disable_vk_account(user_id)

            status = result.get("status")

            if status == "not_found":
                await show_accounts_menu(query)
            else:
                await show_account_card(query, user_id)

    elif query.data.startswith(
        "account_enable_ask_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]
        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            accounts = get_vk_accounts()

            index = _find_account_index_by_user_id(
                accounts,
                user_id,
            )

            if index is None:
                await show_accounts_menu(query)
            else:
                account = accounts[index]

                ready, errors = (
                    validate_account_for_enable(account)
                )

                if not ready:
                    error_text = "\n".join(
                        f"• {error}"
                        for error in errors
                    )

                    await query.edit_message_text(
                        "⚠️ Аккаунт нельзя включить.\n\n"
                        f"ID: {user_id}\n\n"
                        f"{error_text}",
                        reply_markup=InlineKeyboardMarkup(
                            [[
                                InlineKeyboardButton(
                                    "◀️ Назад",
                                    callback_data=(
                                        f"account_view_uid_"
                                        f"{user_id}"
                                    ),
                                )
                            ]]
                        ),
                    )
                else:
                    await query.edit_message_text(
                        "▶️ Включить VK-аккаунт?\n\n"
                        f"ID: {user_id}\n\n"
                        "После включения основной бот "
                        "сможет использовать этот аккаунт.",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Включить",
                                        callback_data=(
                                            f"account_enable_"
                                            f"confirm_uid_{user_id}"
                                        ),
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        "◀️ Отмена",
                                        callback_data=(
                                            f"account_view_uid_"
                                            f"{user_id}"
                                        ),
                                    )
                                ],
                            ]
                        ),
                    )

    elif query.data.startswith(
        "account_enable_confirm_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]
        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            result = tx_set_vk_account_enabled(
                user_id,
                True,
            )

            status = result.get("status")

            if status == "not_found":
                await show_accounts_menu(query)

            elif status == "not_ready":
                errors = result.get("errors") or []

                error_text = "\n".join(
                    f"• {error}"
                    for error in errors
                )

                await query.edit_message_text(
                    "⚠️ Аккаунт не включён.\n\n"
                    f"ID: {user_id}\n\n"
                    f"{error_text}",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "◀️ Назад",
                                callback_data=(
                                    f"account_view_uid_"
                                    f"{user_id}"
                                ),
                            )
                        ]]
                    ),
                )
            else:
                await show_account_card(
                    query,
                    user_id,
                )

    elif query.data.startswith(
        "account_delete_ask_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]
        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            accounts = get_vk_accounts()

            index = _find_account_index_by_user_id(
                accounts,
                user_id,
            )

            if index is None:
                await show_accounts_menu(query)
            else:
                account = accounts[index]
                enabled = (
                    account.get("enabled") is True
                )

                if enabled:
                    warning = (
                        "\n\n⚠️ Аккаунт сейчас включён. "
                        "Первое подтверждение только "
                        "выключит его. Для физического "
                        "удаления потребуется открыть "
                        "аккаунт и подтвердить удаление "
                        "ещё раз."
                    )
                else:
                    warning = ""

                await query.edit_message_text(
                    "🗑 Удалить VK-аккаунт?\n\n"
                    f"ID: {user_id}"
                    f"{warning}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🗑 Подтвердить",
                                    callback_data=(
                                        f"account_delete_"
                                        f"confirm_uid_{user_id}"
                                    ),
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "◀️ Отмена",
                                    callback_data=(
                                        f"account_view_uid_"
                                        f"{user_id}"
                                    ),
                                )
                            ],
                        ]
                    ),
                )

    elif query.data.startswith(
        "account_delete_confirm_uid_"
    ):
        raw_user_id = query.data.rsplit("_", 1)[-1]
        user_id = _normalize_vk_user_id(raw_user_id)

        if user_id is None:
            await show_accounts_menu(query)
        else:
            result = tx_delete_vk_account(user_id)
            status = result.get("status")

            if status == "disabled_first":
                await query.edit_message_text(
                    "⏸ Аккаунт выключен.\n\n"
                    f"ID: {user_id}\n\n"
                    "Физическое удаление не выполнено. "
                    "Откройте аккаунт снова и удалите "
                    "его отдельным действием.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "👤 Открыть аккаунт",
                                    callback_data=(
                                        f"account_view_uid_"
                                        f"{user_id}"
                                    ),
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "◀️ К аккаунтам",
                                    callback_data="accounts",
                                )
                            ],
                        ]
                    ),
                )

            elif status == "pending_posts":
                pending = result.get(
                    "pending_posts",
                    0,
                )

                await query.edit_message_text(
                    "⚠️ Аккаунт не удалён.\n\n"
                    f"ID: {user_id}\n"
                    f"Незавершённых постов: {pending}",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "◀️ Назад",
                                callback_data=(
                                    f"account_view_uid_"
                                    f"{user_id}"
                                ),
                            )
                        ]]
                    ),
                )

            elif status == "queue_error":
                await query.edit_message_text(
                    "⚠️ Аккаунт не удалён.\n\n"
                    "Не удалось безопасно проверить "
                    "очередь публикаций.",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton(
                                "◀️ Назад",
                                callback_data=(
                                    f"account_view_uid_"
                                    f"{user_id}"
                                ),
                            )
                        ]]
                    ),
                )

            elif status in {
                "deleted",
                "not_found",
            }:
                await show_accounts_menu(query)

            else:
                await show_account_card(
                    query,
                    user_id,
                )

    # LEGACY INDEX CALLBACKS — READ ONLY / EXPIRED.
    # They MUST be below all UID branches.
    elif (
        query.data.startswith("account_view_")
        or query.data.startswith("account_disable_")
        or query.data.startswith("account_enable_ask_")
        or query.data.startswith("account_delete_ask_")
        or query.data.startswith("account_enable_confirm_")
        or query.data.startswith("account_delete_confirm_")
    ):
        await query.edit_message_text(
            "⚠️ Эта кнопка устарела.\n\n"
            "Список аккаунтов был обновлён. "
            "Откройте его заново.",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "👥 К аккаунтам",
                        callback_data="accounts",
                    )
                ]]
            ),
        )

    elif query.data == 'account_add':
        # SAFE ACCOUNT WIZARD V1
        # Черновик хранится только в context.user_data.
        # config.json здесь НЕ изменяется.
        context.user_data.pop(
            'vk_account_draft',
            None,
        )
        
        context.user_data[
            'vk_account_draft'
        ] = {}
        
        context.user_data[
            'action'
        ] = 'account_add_user_id'
        
        text = (
            "➕ Новый VK-аккаунт — шаг 1/2\n\n"
            "Отправьте числовой VK ID аккаунта.\n\n"
            "Пример: 123456789\n\n"
            "⚠️ Создаётся только временный "
            "черновик.\n"
            "config.json не изменяется.\n"
            "VK API не вызывается."
        )
        
        keyboard = [[
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data='account_add_cancel',
            )
        ]]
        
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )
    elif query.data == 'account_add_cancel':
        context.user_data.pop(
            'vk_account_draft',
            None,
        )

        context.user_data.pop(
            'action',
            None,
        )

        text = (
            "❌ Добавление отменено.\n\n"
            "Черновик удалён.\n"
            "Рабочая конфигурация не изменялась."
        )

        keyboard = [[
            InlineKeyboardButton(
                "◀️ К аккаунтам",
                callback_data='accounts',
            )
        ]]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'account_add_save':
        # SAFE SAVE V1.1
        # Transactional.
        # Always disabled.
        # Token always empty.
        # No VK API.
        draft = context.user_data.get(
            'vk_account_draft'
        )

        if not isinstance(draft, dict):
            await query.message.edit_text(
                "❌ Черновик не найден.\n\n"
                "Ничего не сохранено.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "👥 К аккаунтам",
                            callback_data='accounts',
                        )
                    ]
                ]),
            )
            return

        user_id = draft.get('user_id')
        phone = draft.get('phone')

        try:
            result = (
                tx_add_vk_account_disabled(
                    user_id,
                    phone,
                )
            )
        except Exception:
            await query.message.edit_text(
                "❌ Ошибка безопасного "
                "сохранения.\n\n"
                "Аккаунт НЕ сохранён "
                "и НЕ активирован."
            )
            return

        status = result.get('status')

        if status == 'saved':
            saved_user_id = result.get(
                'user_id'
            )

            context.user_data.pop(
                'vk_account_draft',
                None,
            )
            context.user_data.pop(
                'action',
                None,
            )

            text = (
                "✅ VK-аккаунт сохранён.\n\n"
                f"🆔 VK ID: {saved_user_id}\n"
                f"📞 Телефон: "
                f"{str(phone).strip()}\n"
                "⏸️ Статус: ОТКЛЮЧЁН\n"
                "🔐 Токен: НЕ УСТАНОВЛЕН\n\n"
                "Основной бот НЕ может "
                "использовать этот аккаунт.\n"
                "VK API не вызывался."
            )

        elif status == 'duplicate':
            text = (
                "❌ Аккаунт с таким VK ID "
                "уже существует.\n\n"
                "Дубликат НЕ создан.\n"
                "Черновик сохранён."
            )

        elif status == 'bad_user_id':
            text = (
                "❌ Некорректный VK ID.\n\n"
                "Аккаунт НЕ сохранён."
            )

        elif status == 'bad_phone':
            text = (
                "❌ Некорректный телефон.\n\n"
                "Аккаунт НЕ сохранён."
            )

        else:
            text = (
                "❌ Аккаунт НЕ сохранён.\n\n"
                "Неизвестный результат "
                "транзакции."
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👥 К аккаунтам",
                        callback_data='accounts',
                    )
                ]
            ]),
        )

    elif query.data == 'account_add_discard':
        context.user_data.pop(
            'vk_account_draft',
            None,
        )

        context.user_data.pop(
            'action',
            None,
        )

        text = (
            "🗑 Черновик удалён.\n\n"
            "Данные не записывались "
            "в config.json."
        )

        keyboard = [[
            InlineKeyboardButton(
                "◀️ К аккаунтам",
                callback_data='accounts',
            )
        ]]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    
    elif query.data == 'vk_multi':
        await show_vk_multi_menu(query)

    elif query.data == 'vk_multi_accounts':
        await show_vk_multi_accounts(query)

    elif query.data.startswith(
        'vk_multi_account:'
    ):
        account_id = int(
            query.data.split(':', 1)[1]
        )
        await show_vk_multi_account(
            query,
            account_id,
        )

    elif query.data.startswith(
        'vk_multi_pause:'
    ):
        account_id = int(
            query.data.split(':', 1)[1]
        )

        ok, message = vk_multi_set_enabled(
            account_id,
            False,
        )

        await query.answer(
            message,
            show_alert=not ok,
        )

        await show_vk_multi_account(
            query,
            account_id,
        )

    elif query.data.startswith(
        'vk_multi_enable:'
    ):
        account_id = int(
            query.data.split(':', 1)[1]
        )

        ok, message = vk_multi_set_enabled(
            account_id,
            True,
        )

        await query.answer(
            message,
            show_alert=not ok,
        )

        await show_vk_multi_account(
            query,
            account_id,
        )

    # VK ACCOUNT AUTH SYSTEMD V1
    elif query.data.startswith('vk_multi_auth:'):
        account_id = int(
            query.data.split(':', 1)[1]
        )

        account = vk_multi_account(
            account_id
        )

        if not account:
            await query.answer(
                "Аккаунт не найден",
                show_alert=True,
            )

        else:
            # До подтверждённой авторизации
            # аккаунт обязательно исключаем из очереди.
            con = vk_multi_connect()

            try:
                con.execute(
                    """
                    UPDATE accounts
                    SET enabled=0,
                        auth_status='AUTH_REQUIRED',
                        status='AUTH_REQUIRED',
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        datetime.now().isoformat(
                            timespec="seconds"
                        ),
                        account_id,
                    ),
                )

                con.commit()

            finally:
                con.close()

            runtime = Path(
                "/opt/vkbot/runtime"
            )

            runtime.mkdir(
                parents=True,
                exist_ok=True,
            )

            (
                runtime / "auth_account_id"
            ).write_text(
                str(account_id),
                encoding="utf-8",
            )

            # Останавливаем только старую
            # AUTH-сессию, если она осталась.
            subprocess.run(
                [
                    "systemctl",
                    "stop",
                    "vkbot-account-auth.service",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            subprocess.run(
                [
                    "systemctl",
                    "reset-failed",
                    "vkbot-account-auth.service",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            result = subprocess.run(
                [
                    "systemctl",
                    "start",
                    "vkbot-account-auth.service",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            await asyncio.sleep(2)

            check = subprocess.run(
                [
                    "systemctl",
                    "is-active",
                    "vkbot-account-auth.service",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            service_state = (
                check.stdout or ""
            ).strip()

            if (
                result.returncode != 0
                or service_state
                not in {
                    "active",
                    "activating",
                }
            ):
                journal = subprocess.run(
                    [
                        "journalctl",
                        "-u",
                        "vkbot-account-auth.service",
                        "-n",
                        "15",
                        "--no-pager",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                error_text = (
                    journal.stdout
                    or result.stderr
                    or "unknown error"
                )

                await query.message.edit_text(
                    "❌ Не удалось запустить "
                    "авторизацию VK.\n\n"
                    "Аккаунт оставлен выключенным.\n\n"
                    "Последняя ошибка:\n"
                    + error_text[-1500:],
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "◀️ Назад",
                                callback_data=(
                                    f"vk_multi_account:"
                                    f"{account_id}"
                                ),
                            )
                        ]
                    ]),
                )

            else:
                await query.message.edit_text(
                    "🔐 Авторизация VK запущена\n\n"
                    f"Аккаунт: {account['name']}\n"
                    f"ID: #{account_id}\n\n"
                    "1. Открой VNC в браузере:\n"
                    "http://127.0.0.1:6080/vnc.html\n\n"
                    "2. В открытом окне VK войди "
                    "в этот аккаунт.\n\n"
                    "3. Пароль/код/2FA вводи "
                    "только на странице VK.\n\n"
                    "4. После появления обычной "
                    "страницы VK нажми "
                    "«Проверить вход».\n\n"
                    "До подтверждения аккаунт "
                    "выключен из очереди.",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "🔄 Проверить вход",
                                callback_data=(
                                    "vk_multi_auth_check:"
                                    f"{account_id}"
                                ),
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "❌ Остановить авторизацию",
                                callback_data=(
                                    "vk_multi_auth_stop:"
                                    f"{account_id}"
                                ),
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "◀️ Назад",
                                callback_data=(
                                    f"vk_multi_account:"
                                    f"{account_id}"
                                ),
                            )
                        ],
                    ]),
                )


    elif query.data.startswith(
        'vk_multi_auth_check:'
    ):
        account_id = int(
            query.data.split(':', 1)[1]
        )

        account = vk_multi_account(
            account_id
        )

        if not account:
            await query.answer(
                "Аккаунт не найден",
                show_alert=True,
            )

        elif account['auth_status'] == 'AUTHORIZED':
            vk_multi_stop_auth(
                account_id
            )

            con = vk_multi_connect()

            try:
                con.execute(
                    """
                    UPDATE accounts
                    SET enabled=1,
                        status='READY',
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        datetime.now().isoformat(
                            timespec="seconds"
                        ),
                        account_id,
                    ),
                )

                con.commit()

            finally:
                con.close()

            await query.answer(
                "VK успешно авторизован",
                show_alert=True,
            )

            await show_vk_multi_account(
                query,
                account_id,
            )

        else:
            active = vk_multi_auth_service_active(
                account_id
            )

            text = (
                "⏳ Вход в VK пока не подтверждён.\n\n"
                f"Авторизация: {account['auth_status']}\n"
                f"Сессия браузера: "
                f"{'РАБОТАЕТ' if active else 'ОСТАНОВЛЕНА'}\n\n"
            )

            if active:
                text += (
                    "Заверши вход в окне VNC и "
                    "нажми «Проверить вход» ещё раз."
                )
            else:
                text += (
                    "Сессия авторизации уже завершилась. "
                    "Вернись к аккаунту и запусти "
                    "«Авторизация» ещё раз."
                )

            await query.answer(
                "Вход пока не подтверждён",
                show_alert=True,
            )

            await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🔄 Проверить ещё раз",
                            callback_data=(
                                f"vk_multi_auth_check:"
                                f"{account_id}"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "◀️ К аккаунту",
                            callback_data=(
                                f"vk_multi_account:"
                                f"{account_id}"
                            ),
                        )
                    ],
                ]),
            )

    elif query.data.startswith(
        'vk_multi_auth_stop:'
    ):
        account_id = int(
            query.data.split(':', 1)[1]
        )

        vk_multi_stop_auth(
            account_id
        )

        con = vk_multi_connect()

        try:
            con.execute(
                """
                UPDATE accounts
                SET enabled=0,
                    auth_status='AUTH_REQUIRED',
                    status='AUTH_REQUIRED',
                    updated_at=?
                WHERE id=?
                """,
                (
                    datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    account_id,
                ),
            )

            con.commit()

        finally:
            con.close()

        await query.answer(
            "Авторизация остановлена"
        )

        await show_vk_multi_account(
            query,
            account_id,
        )

    elif query.data == 'vk_multi_queue':
        await show_vk_multi_queue(query)

    elif query.data == 'vk_multi_queue_fill_ask':
        await query.message.edit_text(
            "📋 Сформировать очередь?\n\n"
            "Группы будут распределены "
            "последовательно между включёнными "
            "аккаунтами.\n\n"
            "Одновременной отправки всеми "
            "аккаунтами не будет.\n\n"
            "⚠️ Это только создаёт очередь. "
            "Публикация НЕ запускается.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Сформировать",
                        callback_data=(
                            "vk_multi_queue_fill_confirm"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data="vk_multi_queue",
                    )
                ],
            ]),
        )

    elif query.data == 'vk_multi_queue_fill_confirm':
        ok, message = vk_multi_fill_queue()

        await query.answer(
            "Очередь сформирована"
            if ok
            else "Ошибка формирования",
            show_alert=not ok,
        )

        await show_vk_multi_queue(query)

    elif query.data == 'vk_multi_queue_clear_ask':
        await query.message.edit_text(
            "🧹 Очистить ожидающие задания?\n\n"
            "DONE-история сохранится.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🧹 Очистить",
                        callback_data=(
                            "vk_multi_queue_clear_confirm"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data="vk_multi_queue",
                    )
                ],
            ]),
        )

    elif query.data == 'vk_multi_queue_clear_confirm':
        ok, message = vk_multi_clear_queue()

        await query.answer(
            message,
            show_alert=not ok,
        )

        await show_vk_multi_queue(query)

    elif query.data in (
        'vk_worker',
        'vk_worker_status',
    ):
        await show_vk_worker_menu(
            query
        )


    elif query.data == 'vk_production_status':
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="vk_production_status",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ],
        ]

        await query.message.edit_text(
            vk_production_status_text(),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'vk_production_start_ask':
        if vk_scan_running():
            text = (
                "⚠️ Production не может быть запущен.\n\n"
                "Сейчас работает SCAN.\n"
                "Сначала остановите SCAN."
            )

            keyboard = [[
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ]]

        else:
            text = (
                "🚀 Запустить Production Worker?\n\n"
                "Это отдельный production-контур.\n\n"
                "Сейчас MASTER LOCK остаётся "
                "финальным предохранителем.\n"
                "Если он закрыт, launcher отклонит запуск."
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "▶️ Подтвердить запуск",
                        callback_data=(
                            "vk_production_start_confirm"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data="vk_worker",
                    )
                ],
            ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'vk_production_start_confirm':
        result = vk_production_start()

        status = result.get("status")
        message = result.get("message", "")

        if status == "MASTER_LOCKED":
            text = (
                "🔒 Production НЕ запущен.\n\n"
                "MASTER LOCK закрыт.\n"
                "Launcher штатно заблокировал запуск.\n\n"
                "Ни одного разрешения на публикацию "
                "эта кнопка сама не включает."
            )

        elif status == "SCAN_RUNNING":
            text = (
                "⚠️ Production НЕ запущен.\n\n"
                "Работает SCAN.\n"
                "Одновременный запуск запрещён."
            )

        elif result.get("ok"):
            text = (
                "🚀 Production START\n\n"
                f"{message}"
            )

        else:
            text = (
                "❌ Production не запущен.\n\n"
                f"{message}"
            )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 Состояние публикаций",
                    callback_data="vk_production_status",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ],
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'vk_production_stop':
        result = vk_production_stop()

        if result.get("ok"):
            text = (
                "⛔ Production STOP\n\n"
                "Production worker остановлен."
            )
        else:
            text = (
                "❌ Не удалось остановить Production.\n\n"
                f"{result.get('message', '')}"
            )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 Состояние публикаций",
                    callback_data="vk_production_status",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ],
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'vk_worker_scan_start':
        try:
            payload = vk_worker_write_command(
                "SCAN_START",
                admin_id=query.from_user.id,
            )

            text = (
                "▶️ Команда запуска SCAN отправлена.\n\n"
                f"ID: {payload['id']}\n"
                "Windows Bridge заберёт её "
                "при следующей проверке.\n\n"
                "🔒 Production остаётся "
                "ЗАБЛОКИРОВАН."
            )

        except Exception as exc:
            text = (
                "❌ Не удалось создать "
                "команду SCAN_START.\n\n"
                f"Ошибка: {type(exc).__name__}"
            )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Проверить статус",
                    callback_data="vk_worker_status",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ],
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data == 'vk_worker_scan_stop':
        try:
            payload = vk_worker_write_command(
                "SCAN_STOP",
                admin_id=query.from_user.id,
            )

            text = (
                "⏹ Команда остановки SCAN отправлена.\n\n"
                f"ID: {payload['id']}\n"
                "Windows Bridge заберёт её "
                "при следующей проверке.\n\n"
                "🔒 Production остаётся "
                "ЗАБЛОКИРОВАН."
            )

        except Exception as exc:
            text = (
                "❌ Не удалось создать "
                "команду SCAN_STOP.\n\n"
                f"Ошибка: {type(exc).__name__}"
            )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Проверить статус",
                    callback_data="vk_worker_status",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data="vk_worker",
                )
            ],
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    elif query.data in ('vk_worker_log', 'vk_worker_log_raw'):
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Обновить журнал",
                    callback_data=(
                        "vk_worker_log"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Публикации",
                    callback_data=(
                        "vk_worker"
                    ),
                )
            ],
        ]


        keyboard.insert(
            1,
            [
                InlineKeyboardButton(
                    (
                        "📋 Обычный журнал"
                        if query.data == "vk_worker_log_raw"
                        else "🔧 Технический журнал"
                    ),
                    callback_data=(
                        "vk_worker_log"
                        if query.data == "vk_worker_log_raw"
                        else "vk_worker_log_raw"
                    ),
                )
            ],
        )

        await query.message.edit_text(
            (vk_worker_log_text() if query.data == 'vk_worker_log_raw' else vk_worker_log_summary()),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

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
    # VK MULTI ACCOUNT ADD WIZARD
    if context.user_data.get(
        'action'
    ) == 'vk_multi_add_name':

        if update.effective_user.id not in ADMIN_IDS:
            return

        name = (
            update.message.text or ""
        ).strip()

        ok, message, account_id = (
            vk_multi_create_account(name)
        )

        if not ok:
            await update.message.reply_text(
                "❌ Аккаунт не создан.\n\n"
                f"{message}\n\n"
                "Отправьте другое название "
                "или /cancel."
            )
            return

        context.user_data.pop(
            'action',
            None,
        )

        account = vk_multi_account(
            account_id
        )

        command = vk_multi_auth_command(
            account_id
        )

        await update.message.reply_text(
            "✅ VK-аккаунт создан.\n\n"
            f"ID: #{account_id}\n"
            f"Название: {account['name']}\n"
            f"Код: {account['code']}\n"
            "Статус: AUTH_REQUIRED\n"
            "Включён: НЕТ\n\n"
            "🔐 Следующий шаг — авторизация.\n\n"
            "Команда на VPS:\n\n"
            f"{command}\n\n"
            "После запуска откройте VNC "
            "и войдите в этот VK-аккаунт.\n\n"
            "До завершения авторизации "
            "аккаунт не используется "
            "диспетчером.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👤 Открыть аккаунт",
                        callback_data=(
                            f"vk_multi_account:"
                            f"{account_id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "👥 Все аккаунты",
                        callback_data=(
                            "vk_multi_accounts"
                        ),
                    )
                ],
            ]),
        )

        return

    if update.effective_user.id not in ADMIN_IDS:
        return
    
    action = context.user_data.get('action')

    # =====================================================
    # SAFE VK ACCOUNT WIZARD V1
    # =====================================================

    if action == 'account_add_user_id':
        raw_user_id = update.message.text.strip()

        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            await update.message.reply_text(
                "❌ VK ID должен состоять "
                "только из цифр."
            )
            return

        if user_id <= 0:
            await update.message.reply_text(
                "❌ VK ID должен быть "
                "положительным числом."
            )
            return

        try:
            cfg = load_config_fresh()
            accounts = cfg.get(
                'vk_accounts',
                [],
            )
        except Exception:
            await update.message.reply_text(
                "❌ Не удалось безопасно "
                "прочитать config.json.\n"
                "Добавление остановлено."
            )
            return

        duplicate = any(
            isinstance(account, dict)
            and str(
                account.get('user_id')
            ) == str(user_id)
            for account in accounts
        )

        if duplicate:
            context.user_data.pop(
                'vk_account_draft',
                None,
            )
            context.user_data.pop(
                'action',
                None,
            )

            await update.message.reply_text(
                "❌ Такой VK ID уже есть "
                "в рабочей конфигурации.\n"
                "Черновик удалён."
            )
            return

        draft = context.user_data.setdefault(
            'vk_account_draft',
            {},
        )

        draft['user_id'] = user_id

        context.user_data[
            'action'
        ] = 'account_add_phone'

        await update.message.reply_text(
            "➕ Новый VK-аккаунт — шаг 2/2\n\n"
            f"VK ID: {user_id}\n\n"
            "Теперь отправьте телефон, "
            "который будет использоваться "
            "в объявлении.\n\n"
            "Пароль VK и токен "
            "НЕ отправляйте."
        )
        return

    if action == 'account_add_phone':
        phone = update.message.text.strip()

        if not phone:
            await update.message.reply_text(
                "❌ Телефон не может быть пустым."
            )
            return

        if len(phone) > 40:
            await update.message.reply_text(
                "❌ Слишком длинное значение.\n"
                "Введите только телефон."
            )
            return

        draft = context.user_data.get(
            'vk_account_draft',
        )

        if not isinstance(draft, dict):
            context.user_data.pop(
                'action',
                None,
            )

            await update.message.reply_text(
                "❌ Черновик потерян.\n"
                "Начните добавление заново."
            )
            return

        user_id = draft.get('user_id')

        if user_id is None:
            context.user_data.pop(
                'vk_account_draft',
                None,
            )
            context.user_data.pop(
                'action',
                None,
            )

            await update.message.reply_text(
                "❌ В черновике отсутствует VK ID.\n"
                "Начните добавление заново."
            )
            return

        draft['phone'] = phone

        context.user_data.pop(
            'action',
            None,
        )

        text = (
            "📋 Черновик VK-аккаунта готов\n\n"
            f"🆔 VK ID: {user_id}\n"
            f"📞 Телефон: {phone}\n"
            "⏸️ Статус: НЕ СОХРАНЁН\n"
            "🔐 Авторизация VK: "
            "НЕ ПОДКЛЮЧЕНА\n\n"
            "Черновик находится только "
            "во временной памяти админки.\n"
            "config.json не изменён.\n"
            "VK API не вызывался."
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "💾 Сохранить отключённым",
                    callback_data='account_add_save',
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 Удалить черновик",
                    callback_data='account_add_discard',
                ),
                InlineKeyboardButton(
                    "👥 К аккаунтам",
                    callback_data='accounts',
                ),
            ],
        ]

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )
        return

    
    if action == 'add_message':
        text = update.message.text
        messages = load_messages()
        messages.append(text)
        save_messages(messages)
        await update.message.reply_text(f"✅ Текст добавлен!\n\nВсего: {len(messages)}", reply_markup=InlineKeyboardMarkup([
    [InlineKeyboardButton(
        "📋 Список объявлений",
        callback_data="show_messages_page_0"
    )],
    [InlineKeyboardButton(
        "🏠 Главное меню",
        callback_data="main_menu"
    )]
]))
        context.user_data['action'] = None
    
    elif action and action.startswith('edit_message_'):
        msg_num = int(action.split('_')[-1])
        new_text = update.message.text
        messages = load_messages()
        
        if 1 <= msg_num <= len(messages):
            messages[msg_num - 1] = new_text
            save_messages(messages)
            await update.message.reply_text(f"✅ Текст #{msg_num} обновлён!", reply_markup=InlineKeyboardMarkup([
    [InlineKeyboardButton(
        "📋 Список объявлений",
        callback_data="show_messages_page_0"
    )],
    [InlineKeyboardButton(
        "🏠 Главное меню",
        callback_data="main_menu"
    )]
]))
        else:
            await update.message.reply_text("❌ Текст не найден")
        
        context.user_data['action'] = None
    
    elif action == 'set_post_interval':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⏱️ Настройки времени",
                callback_data="settings_menu"
            )],
            [InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="main_menu"
            )]
        ])

        raw_value = update.message.text.strip()

        try:
            value = int(raw_value)
        except ValueError:
            await update.message.reply_text(
                "❌ Введите целое число от 10 до 86400.",
                reply_markup=keyboard
            )
            return

        if not 10 <= value <= 86400:
            await update.message.reply_text(
                "❌ Допустимый диапазон: от 10 до 86400. "
                "Введите другое число.",
                reply_markup=keyboard
            )
            return

        try:
            settings = load_settings()
            settings["post_interval"] = value * 1
            save_settings(settings)
        except Exception:
            await update.message.reply_text(
                "❌ Не удалось сохранить настройки. "
                "Попробуйте ещё раз или обратитесь к администратору.",
                reply_markup=keyboard
            )
            return

        context.user_data["action"] = None

        await update.message.reply_text(
            f"✅ Пауза между публикациями: {value} сек.",
            reply_markup=keyboard
        )
    
    elif action == 'set_check_interval':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⏱️ Настройки времени",
                callback_data="settings_menu"
            )],
            [InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="main_menu"
            )]
        ])

        raw_value = update.message.text.strip()

        try:
            value = int(raw_value)
        except ValueError:
            await update.message.reply_text(
                "❌ Введите целое число от 1 до 168.",
                reply_markup=keyboard
            )
            return

        if not 1 <= value <= 168:
            await update.message.reply_text(
                "❌ Допустимый диапазон: от 1 до 168. "
                "Введите другое число.",
                reply_markup=keyboard
            )
            return

        try:
            settings = load_settings()
            settings["check_interval"] = value * 3600
            save_settings(settings)
        except Exception:
            await update.message.reply_text(
                "❌ Не удалось сохранить настройки. "
                "Попробуйте ещё раз или обратитесь к администратору.",
                reply_markup=keyboard
            )
            return

        context.user_data["action"] = None

        await update.message.reply_text(
            f"✅ Интервал проверки: {value} ч.",
            reply_markup=keyboard
        )
    
    elif action == 'set_delete_delay':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⏱️ Настройки времени",
                callback_data="settings_menu"
            )],
            [InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="main_menu"
            )]
        ])

        raw_value = update.message.text.strip()

        try:
            value = int(raw_value)
        except ValueError:
            await update.message.reply_text(
                "❌ Введите целое число от 1 до 10080.",
                reply_markup=keyboard
            )
            return

        if not 1 <= value <= 10080:
            await update.message.reply_text(
                "❌ Допустимый диапазон: от 1 до 10080. "
                "Введите другое число.",
                reply_markup=keyboard
            )
            return

        try:
            settings = load_settings()
            settings["delete_delay"] = value * 1
            save_settings(settings)
        except Exception:
            await update.message.reply_text(
                "❌ Не удалось сохранить настройки. "
                "Попробуйте ещё раз или обратитесь к администратору.",
                reply_markup=keyboard
            )
            return

        context.user_data["action"] = None

        await update.message.reply_text(
            f"✅ Время до удаления: {value} мин.",
            reply_markup=keyboard
        )


async def vkbot_telegram_error_handler(update, context):
    """Обработка ошибок Telegram без изменения пользовательских команд."""
    import logging
    from telegram.error import BadRequest, NetworkError, TimedOut

    error = context.error

    if error is None:
        return

    if isinstance(error, BadRequest):
        if "message is not modified" in str(error).lower():
            return

    logger = logging.getLogger("vkbot.telegram")

    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(
            "Временная ошибка соединения Telegram: %s",
            error,
        )
        return

    logger.error(
        "Ошибка обработки Telegram update",
        exc_info=(type(error), error, error.__traceback__),
    )

def main():
    print("Telegram админка запущена")
    print(f"Администраторы: {ADMIN_IDS}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('cancel', lambda u, c: show_main_menu(u, c)))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(vkbot_telegram_error_handler)
    app.run_polling()

if __name__ == '__main__':
    main()
