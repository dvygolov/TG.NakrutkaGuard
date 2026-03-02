from typing import Optional, List, Callable, Awaitable, Any, Dict, Set
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.database import db
from bot.config import ADMIN_IDS, DEFAULT_THRESHOLD, DEFAULT_TIME_WINDOW, DEFAULT_PROTECT_PREMIUM
from bot.utils.daily_digest import send_daily_digest
import html
import re
import secrets
import time

router = Router()

OFF_KEYWORDS = {"off", "disable", "none", "0"}
BAN_PICKER_TTL_SECONDS = 60 * 30
ban_picker_sessions: Dict[str, Dict[str, Any]] = {}


async def _is_group_chat(bot, chat_id: int) -> bool:
    """Определить является ли чат группой/супергруппой"""
    try:
        chat_info = await bot.get_chat(chat_id)
        return chat_info.type in ["group", "supergroup"]
    except Exception:
        return True


class AddChatStates(StatesGroup):
    waiting_for_chat_id = State()


class TextSettingsStates(StatesGroup):
    waiting_for_welcome = State()
    waiting_for_rules = State()


class StopWordsStates(StatesGroup):
    waiting_for_words = State()


def _format_current_text_block(current_text: Optional[str]) -> str:
    """Формирует блок с превью и raw-текстом для копирования."""
    if not current_text:
        return (
            "🔹 <b>Текущее значение:</b> <i>не задано</i>"
        )
    
    return (
        "🔹 <b>Текущее значение:</b>\n"
        f"{current_text}"
    )


def _format_stop_words_block(words: List[str]) -> str:
    if not words:
        return "🔹 <b>Текущее значение:</b> <i>не заданы</i>"
    preview = ", ".join(words)
    return f"🔹 <b>Текущее значение:</b> {html.escape(preview)}"


async def _start_text_setting_flow(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    chat_id: int,
    title: str,
    instructions: str,
    current_block: str,
):
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        f"{title}\n\n{instructions}\n\n{current_block}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()


async def _process_text_setting_input(
    message: Message,
    state: FSMContext,
    *,
    parse_value: Callable[[Message], Awaitable[Optional[Any]]],
    save_value: Callable[[int, Optional[Any]], Awaitable[str]],
    empty_text_error: str = "❌ Отправьте текстовое сообщение.",
):
    if not is_admin(message.from_user.id):
        return
    
    if not message.text:
        await message.answer(empty_text_error)
        return
    
    plain_text = message.text.strip()
    data = await state.get_data()
    chat_id = data.get('chat_id')
    
    if not chat_id:
        await message.answer("⚠️ Чат не найден. Попробуйте ещё раз.")
        await state.clear()
        return
    
    if plain_text.lower() in OFF_KEYWORDS:
        status_text = await save_value(chat_id, None)
    else:
        value = await parse_value(message)
        if value is None:
            return
        status_text = await save_value(chat_id, value)
    
    is_group = await _is_group_chat(message.bot, chat_id)
    await message.answer(
        f"✅ {status_text}",
        reply_markup=get_chat_settings_keyboard(chat_id, is_group=is_group)
    )
    await state.clear()


async def _parse_html_text(message: Message, *, limit: int, too_long_error: str) -> Optional[str]:
    html_text_value = (message.html_text or message.text or "").strip()
    if len(html_text_value) > limit:
        await message.answer(too_long_error)
        return None
    return html_text_value


async def _parse_stop_words_message(message: Message) -> Optional[List[str]]:
    words = _parse_stop_words(message.text.strip())
    if not words:
        await message.answer("❌ Не найдено ни одного слова. Укажите через запятую или с новой строки.")
        return None
    return words


async def _save_welcome_setting(chat_id: int, value: Optional[str]) -> str:
    await db.update_chat_settings(chat_id, welcome_message=value)
    return "Приветствие отключено." if value is None else "Приветствие сохранено."


async def _save_rules_setting(chat_id: int, value: Optional[str]) -> str:
    await db.update_chat_settings(chat_id, rules_message=value)
    return "Правила отключены." if value is None else "Правила сохранены."


async def _save_stop_words_setting(chat_id: int, value: Optional[List[str]]) -> str:
    await db.set_stop_words(chat_id, value or [])
    if not value:
        return "Стоп-слова очищены."
    unique_count = len(set(value))
    return f"Стоп-слова обновлены ({unique_count} шт.)."


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню настроек"""
    raise RuntimeError("get_main_menu_keyboard is async; call await get_main_menu_keyboard()")


async def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню настроек"""
    chats = await db.get_all_chats()

    buttons = []
    if chats:
        for chat in chats:
            status = "🟢" if chat['protection_active'] else "⚪️"
            name = chat['username'] if chat['username'] else chat['title'][:20]
            buttons.append([
                InlineKeyboardButton(
                    text=f"{status} {name}",
                    callback_data=f"chat_{chat['chat_id']}"
                )
            ])

    buttons.append([InlineKeyboardButton(text="➕ Добавить чат/канал", callback_data="add_chat")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_scoring_menu_keyboard(chat_id: int, is_group: bool = True, has_linked_chat: bool = False, 
                               scoring_enabled: bool = False) -> InlineKeyboardMarkup:
    """Подменю настроек скоринга"""
    buttons = []
    
    # Вкл/Выкл скоринга
    if scoring_enabled:
        buttons.append([InlineKeyboardButton(text="❌ Выключить скоринг", callback_data=f"scoring_disable_{chat_id}")])
        buttons.append([InlineKeyboardButton(text="⚙️ Изменить порог", callback_data=f"scoring_set_threshold_{chat_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="✅ Включить скоринг", callback_data=f"scoring_enable_{chat_id}")])
    
    # Для каналов со связанным чатом - опция использования скоринга чата
    if not is_group and has_linked_chat and scoring_enabled:
        buttons.append([InlineKeyboardButton(text="🔗 Скоринг связанного чата", callback_data=f"toggle_linked_scoring_{chat_id}")])
    
    # Назад
    buttons.append([InlineKeyboardButton(text="◀️ Назад к настройкам", callback_data=f"chat_{chat_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chat_settings_keyboard(chat_id: int, is_group: bool = True, has_linked_chat: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура настроек конкретного чата"""
    buttons = [
        [
            InlineKeyboardButton(text="⚙️ Изменить порог", callback_data=f"set_threshold_{chat_id}"),
            InlineKeyboardButton(text="⏱ Изменить окно", callback_data=f"set_window_{chat_id}")
        ],
        [InlineKeyboardButton(text="👑 Premium защита", callback_data=f"toggle_premium_{chat_id}")],
        [InlineKeyboardButton(text="🚷 Kick all", callback_data=f"toggle_kickall_{chat_id}")],
        [InlineKeyboardButton(text="🎯 Скоринг", callback_data=f"toggle_scoring_{chat_id}")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"stats_menu_{chat_id}")],
    ]
    
    # Капча и другие функции только для групп (не для каналов)
    if is_group:
        buttons.append([InlineKeyboardButton(text="🤖 Капча для вступающих", callback_data=f"toggle_captcha_{chat_id}")])
        buttons.append([
            InlineKeyboardButton(text="👋 Приветствие", callback_data=f"set_welcome_{chat_id}"),
            InlineKeyboardButton(text="📜 Правила /rules", callback_data=f"set_rules_{chat_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="🚫 Стоп-слова", callback_data=f"set_stopwords_{chat_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="📣 Сообщения от каналов", callback_data=f"toggle_channel_posts_{chat_id}")
        ])
    
    buttons.extend([
        [InlineKeyboardButton(text="🗑 Удалить чат", callback_data=f"remove_chat_{chat_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="list_chats")],
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_admin(user_id: int) -> bool:
    """Проверка является ли пользователь админом"""
    return user_id in ADMIN_IDS


def _extract_unban_target(message: Message) -> Optional[str]:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip()


def _normalize_username(value: str) -> str:
    return value if value.startswith("@") else f"@{value}"


def _format_chat_label(chat_data: dict) -> str:
    username = chat_data.get("username")
    if username:
        return f"@{username}"
    title = chat_data.get("title")
    if title:
        return title
    return str(chat_data.get("chat_id"))


async def _unban_and_unrestrict(bot: Bot, chat_id: int, user_id: int) -> str:
    unrestrict_note = ""
    unban_note = ""
    try:
        await bot.unban_chat_member(chat_id, user_id)
    except Exception as e:
        unban_note = f" Разбан не выполнен: {e}"
    try:
        chat_info = await bot.get_chat(chat_id)
        permissions = chat_info.permissions
        if permissions is None:
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
                can_invite_users=True,
            )
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=permissions
        )
        unrestrict_note = " Ограничения сняты."
    except Exception as e:
        unrestrict_note = f" Ограничения снять не удалось: {e}"
    await db.add_allowlisted_user(chat_id, user_id)
    return f"{unban_note}{unrestrict_note}"


async def _find_unban_targets(bot: Bot, user_id: int):
    chats = await db.get_all_chats()
    results = []
    for chat in chats:
        chat_id = chat["chat_id"]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            continue
        status = getattr(member, "status", None)
        if status in {"kicked", "restricted"}:
            results.append((chat, status))
    return results


def _cleanup_expired_ban_sessions():
    now = int(time.time())
    expired_tokens = [
        token for token, data in ban_picker_sessions.items()
        if now - int(data.get("created_at", now)) > BAN_PICKER_TTL_SECONDS
    ]
    for token in expired_tokens:
        ban_picker_sessions.pop(token, None)


def _get_ban_session(token: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired_ban_sessions()
    return ban_picker_sessions.get(token)


def _build_ban_picker_keyboard(token: str, chats: List[Dict[str, Any]], selected_chat_ids: Set[int]) -> InlineKeyboardMarkup:
    buttons = []
    for chat in chats:
        chat_id = int(chat["chat_id"])
        label = str(chat.get("label")) if chat.get("label") else _format_chat_label(chat)
        mark = "✅" if chat_id in selected_chat_ids else "☑️"
        button_text = f"{mark} {label}"
        buttons.append([
            InlineKeyboardButton(
                text=button_text[:64],
                callback_data=f"banpick:{token}:{chat_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="✅ Выбрать все", callback_data=f"banpickall:{token}"),
        InlineKeyboardButton(text="⬜ Снять все", callback_data=f"banpicknone:{token}")
    ])
    buttons.append([
        InlineKeyboardButton(text="🚫 Забанить выбранные", callback_data=f"banapply:{token}")
    ])
    buttons.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"bancancel:{token}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_ban_picker_text(target_label: str, target_kind: str, selected_count: int, total_count: int) -> str:
    target_type = "канал/чат (sender)" if target_kind == "sender_chat" else "пользователь"
    return (
        "🚫 <b>Выбор чатов для бана</b>\n\n"
        f"Цель: <b>{html.escape(target_label)}</b>\n"
        f"Тип: <b>{target_type}</b>\n\n"
        f"Выбрано: <b>{selected_count}</b> из <b>{total_count}</b>\n"
        "Нажмите по чатам, где нужно забанить."
    )


async def _resolve_ban_target(bot: Bot, raw_target: str) -> Optional[Dict[str, Any]]:
    target = raw_target.strip()
    if not target:
        return None

    if target.lstrip("-").isdigit():
        target_id = int(target)
        target_kind = "sender_chat" if target_id < 0 else "user"
        target_label = str(target_id)
        try:
            chat_obj = await bot.get_chat(target_id)
            if chat_obj.type in {"channel", "supergroup"}:
                target_kind = "sender_chat"
                target_label = f"@{chat_obj.username}" if chat_obj.username else (chat_obj.title or str(chat_obj.id))
            else:
                target_kind = "user"
                target_label = f"@{chat_obj.username}" if getattr(chat_obj, "username", None) else str(chat_obj.id)
        except Exception:
            pass
        return {"target_id": target_id, "target_kind": target_kind, "target_label": target_label}

    username = _normalize_username(target)
    try:
        chat_obj = await bot.get_chat(username)
        if chat_obj.type in {"channel", "supergroup"}:
            target_kind = "sender_chat"
        else:
            target_kind = "user"
        target_label = f"@{chat_obj.username}" if getattr(chat_obj, "username", None) else (chat_obj.title or str(chat_obj.id))
        return {"target_id": chat_obj.id, "target_kind": target_kind, "target_label": target_label}
    except Exception:
        user_id = await db.find_user_id_global_by_username(username)
        if user_id:
            return {"target_id": user_id, "target_kind": "user", "target_label": username}
        return None


async def _ban_target_in_chat(bot: Bot, chat_id: int, target_id: int, target_kind: str):
    if target_kind == "sender_chat":
        if not hasattr(bot, "ban_chat_sender_chat"):
            raise RuntimeError("ban_chat_sender_chat не поддерживается текущей версией aiogram")
        await bot.ban_chat_sender_chat(chat_id, target_id)
        return

    try:
        await bot.ban_chat_member(chat_id, target_id, revoke_messages=True)
    except TypeError:
        await bot.ban_chat_member(chat_id, target_id)


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    """Админская команда /ban @username|id (в личке): мультивыбор чатов/каналов для бана."""
    if not is_admin(message.from_user.id):
        return

    # Обрабатываем /ban только в личке; в группах/каналах просто игнорируем.
    if message.chat.type != "private":
        return

    target = _extract_unban_target(message)
    if not target:
        await bot.send_message(
            message.from_user.id,
            "Укажите цель: /ban @username или /ban user_id/channel_id"
        )
        return

    resolved = await _resolve_ban_target(bot, target)
    if not resolved:
        await bot.send_message(
            message.from_user.id,
            "Не удалось определить цель по этому username/id.\n"
            "Попробуйте указать numeric id."
        )
        return

    chats = await db.get_all_chats()
    if not chats:
        await bot.send_message(message.from_user.id, "Нет чатов/каналов в базе для применения бана.")
        return

    token = secrets.token_hex(4)
    ban_picker_sessions[token] = {
        "owner_id": message.from_user.id,
        "target_id": int(resolved["target_id"]),
        "target_kind": resolved["target_kind"],
        "target_label": str(resolved["target_label"]),
        "selected_chat_ids": set(),
        "created_at": int(time.time()),
        "chats": [{"chat_id": int(chat["chat_id"]), "label": _format_chat_label(chat)} for chat in chats],
    }

    selected: Set[int] = ban_picker_sessions[token]["selected_chat_ids"]
    picker_text = _build_ban_picker_text(
        target_label=ban_picker_sessions[token]["target_label"],
        target_kind=ban_picker_sessions[token]["target_kind"],
        selected_count=len(selected),
        total_count=len(chats),
    )
    keyboard = _build_ban_picker_keyboard(token, chats, selected)
    await bot.send_message(message.from_user.id, picker_text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("banpick:"))
async def ban_pick_chat_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, token, chat_id_str = callback.data.split(":", 2)
        chat_id = int(chat_id_str)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    session = _get_ban_session(token)
    if not session:
        await callback.answer("Сессия истекла, запустите /ban снова.", show_alert=True)
        return
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("Это меню другого администратора.", show_alert=True)
        return

    selected: Set[int] = session["selected_chat_ids"]
    if chat_id in selected:
        selected.remove(chat_id)
    else:
        selected.add(chat_id)

    picker_text = _build_ban_picker_text(
        target_label=session["target_label"],
        target_kind=session["target_kind"],
        selected_count=len(selected),
        total_count=len(session["chats"]),
    )
    keyboard = _build_ban_picker_keyboard(token, session["chats"], selected)
    await callback.message.edit_text(picker_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("banpickall:"))
async def ban_pick_all_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, token = callback.data.split(":", 1)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    session = _get_ban_session(token)
    if not session:
        await callback.answer("Сессия истекла, запустите /ban снова.", show_alert=True)
        return
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("Это меню другого администратора.", show_alert=True)
        return

    selected: Set[int] = session["selected_chat_ids"]
    selected.clear()
    for item in session["chats"]:
        selected.add(int(item["chat_id"]))

    picker_text = _build_ban_picker_text(
        target_label=session["target_label"],
        target_kind=session["target_kind"],
        selected_count=len(selected),
        total_count=len(session["chats"]),
    )
    keyboard = _build_ban_picker_keyboard(token, session["chats"], selected)
    await callback.message.edit_text(picker_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer("Выбраны все")


@router.callback_query(F.data.startswith("banpicknone:"))
async def ban_pick_none_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, token = callback.data.split(":", 1)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    session = _get_ban_session(token)
    if not session:
        await callback.answer("Сессия истекла, запустите /ban снова.", show_alert=True)
        return
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("Это меню другого администратора.", show_alert=True)
        return

    selected: Set[int] = session["selected_chat_ids"]
    selected.clear()

    picker_text = _build_ban_picker_text(
        target_label=session["target_label"],
        target_kind=session["target_kind"],
        selected_count=len(selected),
        total_count=len(session["chats"]),
    )
    keyboard = _build_ban_picker_keyboard(token, session["chats"], selected)
    await callback.message.edit_text(picker_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer("Снято")


@router.callback_query(F.data.startswith("banapply:"))
async def ban_apply_callback(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, token = callback.data.split(":", 1)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    session = _get_ban_session(token)
    if not session:
        await callback.answer("Сессия истекла, запустите /ban снова.", show_alert=True)
        return
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("Это меню другого администратора.", show_alert=True)
        return

    selected_chat_ids = set(session["selected_chat_ids"])
    if not selected_chat_ids:
        await callback.answer("Выберите хотя бы один чат.", show_alert=True)
        return

    label_map = {int(item["chat_id"]): item["label"] for item in session["chats"]}
    success_labels: List[str] = []
    fail_rows: List[str] = []
    for chat_id in selected_chat_ids:
        try:
            await _ban_target_in_chat(
                bot,
                chat_id=chat_id,
                target_id=int(session["target_id"]),
                target_kind=str(session["target_kind"]),
            )
            success_labels.append(label_map.get(chat_id, str(chat_id)))
        except Exception as e:
            fail_rows.append(f"• {html.escape(label_map.get(chat_id, str(chat_id)))}: {html.escape(str(e))}")

    ban_picker_sessions.pop(token, None)

    target_label = html.escape(str(session["target_label"]))
    target_type = "канал/чат (sender)" if session["target_kind"] == "sender_chat" else "пользователь"
    text = (
        "✅ <b>Бан выполнен</b>\n\n"
        f"Цель: <b>{target_label}</b>\n"
        f"Тип: <b>{target_type}</b>\n"
        f"Успешно: <b>{len(success_labels)}</b>\n"
        f"Ошибок: <b>{len(fail_rows)}</b>"
    )
    if fail_rows:
        text += "\n\n⚠️ Ошибки:\n" + "\n".join(fail_rows[:10])

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("bancancel:"))
async def ban_cancel_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, token = callback.data.split(":", 1)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    session = _get_ban_session(token)
    if not session:
        await callback.answer("Сессия истекла.", show_alert=True)
        return
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("Это меню другого администратора.", show_alert=True)
        return

    ban_picker_sessions.pop(token, None)
    await callback.message.edit_text("❌ Операция бана отменена.")
    await callback.answer("Отменено")


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    """Админская команда /unban @username|user_id для разбана пользователя в чате."""
    if not is_admin(message.from_user.id):
        return

    # Удаляем команду из чата сразу
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    target = _extract_unban_target(message)
    if not target:
        await bot.send_message(
            message.from_user.id,
            "Укажите пользователя: /unban @username или /unban 123456789"
        )
        return

    user_id: Optional[int] = None
    if target.lstrip("-").isdigit():
        user_id = int(target)
    else:
        username = _normalize_username(target)
        try:
            user_chat = await bot.get_chat(username)
            user_id = user_chat.id
        except Exception:
            chat_id_for_lookup = message.chat.id if message.chat.type in {"group", "supergroup"} else None
            if chat_id_for_lookup:
                user_id = await db.find_user_id_by_username(chat_id_for_lookup, username)
            if not user_id:
                user_id = await db.find_user_id_global_by_username(username)
            if not user_id:
                await bot.send_message(
                    message.from_user.id,
                    f"Не удалось найти пользователя {html.escape(username)}. "
                    "Укажите user_id: /unban 123456789"
                )
                return

    if message.chat.type == "private":
        targets = await _find_unban_targets(bot, user_id)
        if not targets:
            chats = await db.get_all_chats()
            if not chats:
                await bot.send_message(
                    message.from_user.id,
                    f"Не найдено банов/ограничений для пользователя {user_id}."
                )
                return
            buttons = []
            for chat in chats:
                label = _format_chat_label(chat)
                buttons.append([
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"allowlist_chat:{chat['chat_id']}:{user_id}"
                    )
                ])
            await bot.send_message(
                message.from_user.id,
                f"Пользователь {user_id} не забанен. Куда добавить в allowlist?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return
        buttons = []
        for chat, status in targets:
            label = _format_chat_label(chat)
            status_text = "banned" if status == "kicked" else "restricted"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{label} ({status_text})",
                    callback_data=f"unban_chat:{chat['chat_id']}:{user_id}"
                )
            ])
        if len(targets) > 1:
            buttons.append([
                InlineKeyboardButton(
                    text="All",
                    callback_data=f"unban_all:{user_id}"
                )
            ])
        await bot.send_message(
            message.from_user.id,
            f"Где разбанить пользователя {user_id}?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        return

    if message.chat.type not in {"group", "supergroup"}:
        await bot.send_message(message.from_user.id, "Команда /unban работает только в группах.")
        return

    try:
        unrestrict_note = await _unban_and_unrestrict(bot, message.chat.id, user_id)
        chat_title = message.chat.title or str(message.chat.id)
        await bot.send_message(
            message.from_user.id,
            f"Разбан выполнен: пользователь {user_id} в чате {html.escape(chat_title)}.{unrestrict_note}"
        )
    except Exception as e:
        chat_title = message.chat.title or str(message.chat.id)
        await bot.send_message(
            message.from_user.id,
            f"Не удалось разбанить {user_id} в чате {html.escape(chat_title)}: {e}"
        )


@router.callback_query(F.data.startswith("unban_chat:"))
async def unban_chat_callback(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, chat_id_str, user_id_str = callback.data.split(":")
        chat_id = int(chat_id_str)
        user_id = int(user_id_str)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    try:
        unrestrict_note = await _unban_and_unrestrict(bot, chat_id, user_id)
        chat_data = await db.get_chat(chat_id)
        chat_label = _format_chat_label(chat_data) if chat_data else str(chat_id)
        await bot.send_message(
            callback.from_user.id,
            f"Разбан выполнен: пользователь {user_id} в чате {html.escape(chat_label)}.{unrestrict_note}"
        )
        await callback.answer("Готово")
    except Exception as e:
        chat_data = await db.get_chat(chat_id)
        chat_label = _format_chat_label(chat_data) if chat_data else str(chat_id)
        await bot.send_message(
            callback.from_user.id,
            f"Не удалось разбанить {user_id} в чате {html.escape(chat_label)}: {e}"
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("unban_all:"))
async def unban_all_callback(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, user_id_str = callback.data.split(":")
        user_id = int(user_id_str)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    targets = await _find_unban_targets(bot, user_id)
    if not targets:
        await callback.answer("Нечего разбанивать", show_alert=True)
        return
    success = 0
    for chat, _ in targets:
        try:
            await _unban_and_unrestrict(bot, chat["chat_id"], user_id)
            success += 1
        except Exception:
            pass
    await bot.send_message(
        callback.from_user.id,
        f"Готово: разбанено {success} чатов для пользователя {user_id}."
    )
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("allowlist_chat:"))
async def allowlist_chat_callback(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, chat_id_str, user_id_str = callback.data.split(":")
        chat_id = int(chat_id_str)
        user_id = int(user_id_str)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    await db.add_allowlisted_user(chat_id, user_id)
    chat_data = await db.get_chat(chat_id)
    chat_label = _format_chat_label(chat_data) if chat_data else str(chat_id)
    await bot.send_message(
        callback.from_user.id,
        f"Пользователь {user_id} добавлен в allowlist для чата {html.escape(chat_label)}."
    )
    await callback.answer("Готово")


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет доступа к этому боту.")
        return
    
    await message.answer(
        "🛡 <b>Nakrutka Guard Bot</b>\n\n"
        "Бот для защиты телеграм-групп и каналов от накрутки.\n\n"
        "Выберите чат или канал для настройки:",
        reply_markup=await get_main_menu_keyboard(),
        parse_mode="HTML"
    )


@router.message(Command("digest"))
async def cmd_digest(message: Message):
    """Глобальные настройки ежедневного дайджеста: /digest [on|off]"""
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) >= 2:
        mode = parts[1].strip().lower()
        if mode in {"on", "1", "true", "enable"}:
            await db.set_daily_digest_settings(enabled=True)
        elif mode in {"off", "0", "false", "disable"}:
            await db.set_daily_digest_settings(enabled=False)
        else:
            await message.answer("❌ Используйте: /digest on или /digest off")
            return

    settings = await db.get_daily_digest_settings()
    status = "✅ Включен" if settings["enabled"] else "⛔️ Выключен"
    await message.answer(
        "📰 <b>Ежедневный дайджест</b>\n\n"
        f"Статус: {status}\n"
        f"Время: <b>{settings['hour']:02d}:{settings['minute']:02d}</b> (серверное локальное)\n\n"
        "Команды:\n"
        "• /digest on|off\n"
        "• /digest_time HH:MM\n"
        "• /digest_now",
        parse_mode="HTML"
    )


@router.message(Command("digest_time"))
async def cmd_digest_time(message: Message):
    """Установить время ежедневного дайджеста: /digest_time HH:MM"""
    if not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Используйте формат: /digest_time HH:MM")
        return

    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", parts[1].strip())
    if not match:
        await message.answer("❌ Неверный формат времени. Пример: /digest_time 09:30")
        return

    hour = int(match.group(1))
    minute = int(match.group(2))
    await db.set_daily_digest_settings(hour=hour, minute=minute)
    await message.answer(f"✅ Время дайджеста установлено: <b>{hour:02d}:{minute:02d}</b>", parse_mode="HTML")


@router.message(Command("digest_now"))
async def cmd_digest_now(message: Message, bot: Bot):
    """Принудительно отправить дайджест за последние 24 часа."""
    if not is_admin(message.from_user.id):
        return

    sent = await send_daily_digest(bot)
    if sent:
        await message.answer("✅ Дайджест отправлен.")
    else:
        await message.answer("ℹ️ За последние 24 часа нет событий для дайджеста.")


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    """Показать главное меню"""
    await callback.message.edit_text(
        "🛡 <b>Nakrutka Guard Bot</b>\n\n"
        "Выберите чат для настройки:",
        reply_markup=await get_main_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "add_chat")
async def start_add_chat(callback: CallbackQuery, state: FSMContext):
    """Начать процесс добавления чата"""
    await callback.message.edit_text(
        "➕ <b>Добавление чата</b>\n\n"
        "Перешлите мне любое сообщение из чата/канала, который нужно защитить, "
        "или отправьте его ID (например: -1001234567890)",
        parse_mode="HTML"
    )
    await state.set_state(AddChatStates.waiting_for_chat_id)
    await callback.answer()


@router.message(AddChatStates.waiting_for_chat_id)
async def process_chat_id(message: Message, state: FSMContext):
    """Обработать добавление чата"""
    if not is_admin(message.from_user.id):
        return
    
    chat_id = None
    title = None
    username = None
    
    # Если переслано из чата
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        title = message.forward_from_chat.title
        username = message.forward_from_chat.username
    # Если отправлен ID
    elif message.text and message.text.lstrip('-').isdigit():
        chat_id = int(message.text)
        try:
            chat = await message.bot.get_chat(chat_id)
            title = chat.title
            username = chat.username
        except Exception as e:
            await message.answer(f"❌ Не удалось получить информацию о чате: {e}")
            return
    else:
        await message.answer("❌ Неверный формат. Отправьте ID чата или перешлите сообщение.")
        return
    
    # Добавляем чат в БД
    await db.add_chat(
        chat_id=chat_id,
        title=title or f"Chat {chat_id}",
        username=username,
        threshold=DEFAULT_THRESHOLD,
        time_window=DEFAULT_TIME_WINDOW,
        protect_premium=DEFAULT_PROTECT_PREMIUM
    )
    
    await message.answer(
        f"✅ <b>Чат добавлен!</b>\n\n"
        f"📝 Название: {title}\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"📊 Порог: {DEFAULT_THRESHOLD} вступлений/{DEFAULT_TIME_WINDOW}с\n"
        f"👑 Premium защита: {'Да' if DEFAULT_PROTECT_PREMIUM else 'Нет'}\n\n"
        f"⚠️ <b>Важно!</b> Убедитесь, что бот добавлен в чат/канал с правами администратора "
        f"(включая право на удаление пользователей).",
        parse_mode="HTML",
        reply_markup=await get_main_menu_keyboard()
    )
    
    await state.clear()


def _parse_stop_words(raw_text: str) -> List[str]:
    """Разбивает текст на стоп-слова (рожать по строкам/запятым)."""
    separators = [segment for line in raw_text.splitlines() for segment in line.split(",")]
    cleaned = [segment.strip().lower() for segment in separators if segment.strip()]
    return cleaned


@router.callback_query(F.data.startswith("set_stopwords_"))
async def start_set_stopwords(callback: CallbackQuery, state: FSMContext):
    """Начать настройку стоп-слов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    words = await db.get_stop_words(chat_id)
    
    await _start_text_setting_flow(
        callback,
        state,
        chat_id=chat_id,
        title="🚫 <b>Стоп-слова</b>",
        instructions=(
            "Отправьте список слов/фраз, каждое с новой строки (или через запятую).\n"
            "Любое сообщение в чате, содержащее одно из слов (без учёта регистра), будет удалено.\n\n"
            "Чтобы очистить список, отправьте <code>off</code>."
        ),
        current_block=_format_stop_words_block(words)
    )
    await state.set_state(StopWordsStates.waiting_for_words)


@router.message(StopWordsStates.waiting_for_words)
async def process_stop_words(message: Message, state: FSMContext):
    """Сохранить стоп-слова"""
    await _process_text_setting_input(
        message,
        state,
        parse_value=_parse_stop_words_message,
        save_value=_save_stop_words_setting,
        empty_text_error="❌ Отправьте список слов текстом."
    )


@router.callback_query(F.data.startswith("set_welcome_"))
async def start_set_welcome(callback: CallbackQuery, state: FSMContext):
    """Начать настройку приветственного сообщения"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)
    current_welcome = chat_data.get('welcome_message') if chat_data else None
    current_block = _format_current_text_block(current_welcome)
    
    await _start_text_setting_flow(
        callback,
        state,
        chat_id=chat_id,
        title="👋 <b>Настройка приветственного сообщения</b>",
        instructions=(
            "Отправьте текст, который бот будет показывать после успешной капчи.\n"
            "Сообщение автоматически удаляется через ~3 минуты.\n\n"
            "Поддерживается <b>HTML-разметка</b> и плейсхолдер <code>{username}</code> для упоминания новенького.\n\n"
            "Чтобы отключить приветствие, отправьте <code>off</code>."
        ),
        current_block=current_block
    )
    await state.set_state(TextSettingsStates.waiting_for_welcome)


@router.message(TextSettingsStates.waiting_for_welcome)
async def process_welcome_message(message: Message, state: FSMContext):
    """Сохранить новое приветствие"""
    async def _parse(message: Message) -> Optional[str]:
        return await _parse_html_text(
            message,
            limit=2000,
            too_long_error="❌ Слишком длинное сообщение (лимит 1000 символов)."
        )
    
    await _process_text_setting_input(
        message,
        state,
        parse_value=_parse,
        save_value=_save_welcome_setting
    )


@router.callback_query(F.data.startswith("set_rules_"))
async def start_set_rules(callback: CallbackQuery, state: FSMContext):
    """Начать настройку текста /rules"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Нет доступа", show_alert=True)
        return
    
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)
    current_rules = chat_data.get('rules_message') if chat_data else None
    current_block = _format_current_text_block(current_rules)
    
    await _start_text_setting_flow(
        callback,
        state,
        chat_id=chat_id,
        title="📜 <b>Настройка правил (/rules)</b>",
        instructions=(
            "Отправьте текст правил. Пользователи смогут получить его командой <code>/rules</code>, "
            "бот удалит сообщение через ~3 минуты.\n\n"
            "Можно использовать <b>HTML-разметку</b> и ссылки.\n\n"
            "Чтобы отключить правила, отправьте <code>off</code>."
        ),
        current_block=current_block
    )
    await state.set_state(TextSettingsStates.waiting_for_rules)


@router.message(TextSettingsStates.waiting_for_rules)
async def process_rules_message(message: Message, state: FSMContext):
    """Сохранить текст правил"""
    async def _parse(message: Message) -> Optional[str]:
        return await _parse_html_text(
            message,
            limit=4000,
            too_long_error="❌ Слишком длинное сообщение (лимит 1500 символов)."
        )
    
    await _process_text_setting_input(
        message,
        state,
        parse_value=_parse,
        save_value=_save_rules_setting
    )


@router.callback_query(F.data == "list_chats")
async def list_chats(callback: CallbackQuery):
    """Показать список всех чатов"""
    chats = await db.get_all_chats()
    
    if not chats:
        await callback.message.edit_text(
            "📋 <b>Список чатов</b>\n\n"
            "Нет добавленных чатов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")],
                [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    buttons = []
    for chat in chats:
        status = "🟢" if chat['protection_active'] else "⚪️"
        name = chat['username'] if chat['username'] else chat['title'][:20]
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {name}",
                callback_data=f"chat_{chat['chat_id']}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")])
    
    await callback.message.edit_text(
        "📋 <b>Список чатов</b>\n\n"
        "🟢 - режим защиты активен\n"
        "⚪️ - обычный режим\n\n"
        "Выберите чат для настройки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


async def _show_chat_settings_message(callback: CallbackQuery, chat_id: int):
    """Внутренняя функция для отображения настроек чата"""
    from bot.utils.telegram_helper import get_linked_chat_id
    
    chat_data = await db.get_chat(chat_id)
    
    if not chat_data:
        await callback.answer("❌ Чат не найден", show_alert=True)
        return
    
    # Определяем тип чата
    is_group = await _is_group_chat(callback.bot, chat_id)
    
    # Проверяем есть ли linked chat
    linked_chat_id = await get_linked_chat_id(callback.bot, chat_id)
    has_linked_chat = linked_chat_id is not None
    
    status = "🟢 АКТИВЕН" if chat_data['protection_active'] else "⚪️ ВЫКЛЮЧЕН"
    kick_all = "🚷 ВКЛЮЧЕН" if chat_data.get('kick_all_active', False) else "⚪️ ВЫКЛЮЧЕН"
    premium = "✅ Да" if chat_data['protect_premium'] else "❌ Нет"
    captcha = "✅ Да" if chat_data.get('captcha_enabled', False) else "❌ Нет"
    
    # Формируем текст
    scoring_enabled = chat_data.get('scoring_enabled', False)
    scoring_threshold = chat_data.get('scoring_threshold', 50)
    scoring = f"✅ Да, порог {scoring_threshold}" if scoring_enabled else "❌ Нет"
    
    # Информация о связанном чате (для каналов)
    if not is_group and has_linked_chat:
        use_linked = chat_data.get('use_linked_chat_scoring', False)
        if use_linked:
            scoring += f"\n   🔗 Использует скоринг чата (ID: {linked_chat_id})"
    
    text = (
        f"⚙️ <b>Настройки чата</b>\n\n"
        f"📝 Название: {chat_data['title']}\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"👤 Username: @{chat_data['username'] or 'нет'}\n\n"
        f"🛡 Режим защиты: {status}\n"
        f"🚷 Kick all: {kick_all}\n"
        f"📊 Порог: {chat_data['threshold']} юзеров/{chat_data['time_window']} секунд\n"
        f"👑 Защита Premium: {premium}\n"
        f"🎯 Скоринг: {scoring}"
    )
    
    # Добавляем настройки только для групп (капча, приветствия и т.д.)
    if is_group:
        welcome_status = "✅ Настроено" if chat_data.get('welcome_message') else "⚪️ Нет"
        rules_status = "✅ Настроены" if chat_data.get('rules_message') else "⚪️ Нет"
        stop_words = await db.get_stop_words(chat_id)
        stop_words_status = f"{len(stop_words)} шт." if stop_words else "⚪️ Нет"
        channel_posts_status = "✅ Разрешены" if chat_data.get('allow_channel_posts', True) else "🚫 Запрещены"
        text += (
            f"\n🤖 Капча: {captcha}"
            f"\n👋 Приветствие: {welcome_status}"
            f"\n📜 Правила /rules: {rules_status}"
            f"\n🚫 Стоп-слова: {stop_words_status}"
            f"\n📣 Сообщения от каналов: {channel_posts_status}"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_chat_settings_keyboard(chat_id, is_group, has_linked_chat),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chat_"))
async def show_chat_settings(callback: CallbackQuery):
    """Показать настройки чата"""
    chat_id = int(callback.data.split("_")[1])
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("toggle_premium_"))
async def toggle_premium_protection(callback: CallbackQuery):
    """Переключить защиту Premium пользователей"""
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)
    
    new_value = not chat_data['protect_premium']
    await db.update_chat_settings(chat_id, protect_premium=new_value)
    
    await callback.answer(
        f"✅ Premium защита: {'Включена' if new_value else 'Выключена'}",
        show_alert=True
    )
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("toggle_kickall_"))
async def toggle_kick_all(callback: CallbackQuery):
    """Переключить режим 'kick all' (банить всех новых вступающих)"""
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)

    if not chat_data:
        await callback.answer("❌ Чат не найден", show_alert=True)
        return

    new_value = not bool(chat_data.get("kick_all_active", False))
    await db.update_chat_settings(chat_id, kick_all_active=new_value)

    await callback.answer(
        f"✅ Kick all: {'Включен' if new_value else 'Выключен'}",
        show_alert=True
    )
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("toggle_linked_scoring_"))
async def toggle_linked_scoring(callback: CallbackQuery):
    """Переключить использование скоринга связанного чата"""
    from bot.utils.telegram_helper import get_linked_chat_id
    
    chat_id = int(callback.data.split("_")[3])
    
    # Получаем linked_chat_id через API
    linked_chat_id = await get_linked_chat_id(callback.bot, chat_id)
    
    if not linked_chat_id:
        await callback.answer("❌ Связанный чат не найден", show_alert=True)
        return
    
    # Получаем текущее состояние
    linked_info = await db.get_linked_chat_info(chat_id)
    current_value = linked_info.get('use_linked_chat_scoring', False) if linked_info else False
    
    new_value = not current_value
    
    # Обновляем настройки
    await db.set_linked_chat_scoring(chat_id, new_value, linked_chat_id if new_value else None)
    
    if new_value:
        await callback.answer(
            f"✅ Канал теперь использует скоринг чата (ID: {linked_chat_id})",
            show_alert=True
        )
    else:
        await callback.answer(
            "✅ Канал использует собственный скоринг",
            show_alert=True
        )
    
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("toggle_scoring_"))
async def toggle_scoring(callback: CallbackQuery):
    """Открыть меню настроек скоринга"""
    from bot.utils.telegram_helper import get_linked_chat_id
    
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)
    
    if not chat_data:
        await callback.answer("❌ Чат не найден", show_alert=True)
        return
    
    # Определяем тип чата и linked chat
    is_group = await _is_group_chat(callback.bot, chat_id)
    linked_chat_id = await get_linked_chat_id(callback.bot, chat_id)
    has_linked_chat = linked_chat_id is not None
    
    scoring_enabled = chat_data.get('scoring_enabled', False)
    scoring_threshold = chat_data.get('scoring_threshold', 50)
    
    # Формируем текст
    text = f"🎯 <b>Настройки скоринга</b>\n\n"
    text += f"📝 Чат: {chat_data['title']}\n\n"
    
    if scoring_enabled:
        text += f"✅ Скоринг <b>включен</b>\n"
        text += f"📊 Порог: <b>{scoring_threshold}</b>\n\n"
        
        # Информация о linked chat
        if not is_group and has_linked_chat:
            use_linked = chat_data.get('use_linked_chat_scoring', False)
            if use_linked:
                text += f"🔗 Использует скоринг связанного чата (ID: {linked_chat_id})\n\n"
            else:
                text += f"📌 Собственный скоринг канала\n\n"
        
        text += "Юзеры со скором выше порога будут кикнуты."
    else:
        text += "❌ Скоринг <b>выключен</b>\n\n"
        text += "Включите скоринг для автоматической фильтрации ботов."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_scoring_menu_keyboard(chat_id, is_group, has_linked_chat, scoring_enabled),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scoring_enable_"))
async def scoring_enable(callback: CallbackQuery, state: FSMContext):
    """Включить скоринг - запросить порог"""
    chat_id = int(callback.data.split("_")[2])
    
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        "🎯 <b>Включение скоринга</b>\n\n"
        "Отправьте порог скоринга (0-100):\n"
        "Юзеры со score > порога будут кикнуты.\n\n"
        "Например: 50 (рекомендуется)",
        parse_mode="HTML"
    )
    await state.set_state(ChangeSettingsStates.waiting_for_scoring_threshold)
    await callback.answer()


@router.callback_query(F.data.startswith("scoring_disable_"))
async def scoring_disable(callback: CallbackQuery):
    """Выключить скоринг"""
    from bot.utils.telegram_helper import get_linked_chat_id
    
    chat_id = int(callback.data.split("_")[2])
    
    await db.update_chat_settings(chat_id, scoring_enabled=False)
    await callback.answer("✅ Скоринг выключен", show_alert=True)
    
    # Возвращаемся в меню скоринга
    chat_data = await db.get_chat(chat_id)
    is_group = await _is_group_chat(callback.bot, chat_id)
    linked_chat_id = await get_linked_chat_id(callback.bot, chat_id)
    has_linked_chat = linked_chat_id is not None
    
    text = f"🎯 <b>Настройки скоринга</b>\n\n"
    text += f"📝 Чат: {chat_data['title']}\n\n"
    text += "❌ Скоринг <b>выключен</b>\n\n"
    text += "Включите скоринг для автоматической фильтрации ботов."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_scoring_menu_keyboard(chat_id, is_group, has_linked_chat, False),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("scoring_set_threshold_"))
async def scoring_set_threshold(callback: CallbackQuery, state: FSMContext):
    """Изменить порог скоринга"""
    chat_id = int(callback.data.split("_")[3])
    
    await state.update_data(chat_id=chat_id)
    await callback.message.edit_text(
        "🎯 <b>Изменение порога скоринга</b>\n\n"
        "Отправьте новый порог скоринга (0-100):\n"
        "Юзеры со score > порога будут кикнуты.\n\n"
        "Например: 50 (рекомендуется)",
        parse_mode="HTML"
    )
    await state.set_state(ChangeSettingsStates.waiting_for_scoring_threshold)
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_captcha_"))
async def toggle_captcha(callback: CallbackQuery):
    """Переключить капчу для вступающих"""
    chat_id = int(callback.data.split("_")[2])
    chat_data = await db.get_chat(chat_id)
    
    new_value = not chat_data.get('captcha_enabled', False)
    await db.update_chat_settings(chat_id, captcha_enabled=new_value)
    
    await callback.answer(
        f"✅ Капча: {'Включена' if new_value else 'Выключена'}",
        show_alert=True
    )
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("toggle_channel_posts_"))
async def toggle_channel_posts(callback: CallbackQuery):
    """Переключить возможность сообщений от каналов"""
    chat_id = int(callback.data.split("_")[3])
    chat_data = await db.get_chat(chat_id)
    
    new_value = not chat_data.get('allow_channel_posts', True)
    await db.update_chat_settings(chat_id, allow_channel_posts=new_value)
    
    await callback.answer(
        f"📣 Сообщения от каналов: {'Разрешены' if new_value else 'Запрещены'}",
        show_alert=True
    )
    await _show_chat_settings_message(callback, chat_id)


@router.callback_query(F.data.startswith("remove_chat_"))
async def remove_chat(callback: CallbackQuery):
    """Удалить чат из защиты"""
    chat_id = int(callback.data.split("_")[2])
    await db.remove_chat(chat_id)
    
    await callback.answer("✅ Чат удалён из защиты", show_alert=True)
    await list_chats(callback)


# Изменение порога и окна через FSM
class ChangeSettingsStates(StatesGroup):
    waiting_for_threshold = State()
    waiting_for_window = State()
    waiting_for_scoring_threshold = State()


@router.callback_query(F.data.startswith("set_threshold_"))
async def start_set_threshold(callback: CallbackQuery, state: FSMContext):
    """Начать изменение порога"""
    chat_id = int(callback.data.split("_")[2])
    await state.update_data(chat_id=chat_id)
    
    await callback.message.edit_text(
        "📊 <b>Изменение порога</b>\n\n"
        "Отправьте новое значение порога (количество вступлений):\n"
        "Например: 10",
        parse_mode="HTML"
    )
    await state.set_state(ChangeSettingsStates.waiting_for_threshold)
    await callback.answer()


@router.message(ChangeSettingsStates.waiting_for_threshold)
async def process_threshold(message: Message, state: FSMContext):
    """Обработать новый порог"""
    if not is_admin(message.from_user.id):
        return
    
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    
    threshold = int(message.text)
    if threshold < 1 or threshold > 1000:
        await message.answer("❌ Порог должен быть от 1 до 1000")
        return
    
    data = await state.get_data()
    chat_id = data['chat_id']
    
    await db.update_chat_settings(chat_id, threshold=threshold)
    await message.answer(
        f"✅ Порог обновлён: {threshold} вступлений",
        reply_markup=get_chat_settings_keyboard(chat_id)
    )
    
    await state.clear()


@router.callback_query(F.data.startswith("set_window_"))
async def start_set_window(callback: CallbackQuery, state: FSMContext):
    """Начать изменение временного окна"""
    chat_id = int(callback.data.split("_")[2])
    await state.update_data(chat_id=chat_id)
    
    await callback.message.edit_text(
        "⏱ <b>Изменение временного окна</b>\n\n"
        "Отправьте новое значение в секундах:\n"
        "Например: 60 (1 минута)",
        parse_mode="HTML"
    )
    await state.set_state(ChangeSettingsStates.waiting_for_window)
    await callback.answer()


@router.message(ChangeSettingsStates.waiting_for_window)
async def process_window(message: Message, state: FSMContext):
    """Обработать новое окно"""
    if not is_admin(message.from_user.id):
        return
    
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    
    window = int(message.text)
    if window < 10 or window > 600:
        await message.answer("❌ Окно должно быть от 10 до 600 секунд")
        return
    
    data = await state.get_data()
    chat_id = data['chat_id']
    
    await db.update_chat_settings(chat_id, time_window=window)
    await message.answer(
        f"✅ Временное окно обновлено: {window} секунд",
        reply_markup=get_chat_settings_keyboard(chat_id)
    )
    
    await state.clear()


@router.message(ChangeSettingsStates.waiting_for_scoring_threshold)
async def process_scoring_threshold(message: Message, state: FSMContext, bot: Bot):
    """Обработать новый порог скоринга"""
    from bot.utils.telegram_helper import get_linked_chat_id
    
    if not is_admin(message.from_user.id):
        return
    
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    
    threshold = int(message.text)
    if threshold < 0 or threshold > 100:
        await message.answer("❌ Порог должен быть от 0 до 100")
        return
    
    data = await state.get_data()
    chat_id = data['chat_id']
    
    # Обновляем порог и включаем скоринг
    await db.update_chat_settings(chat_id, scoring_threshold=threshold, scoring_enabled=True)
    
    # Получаем данные для правильного отображения меню
    chat_data = await db.get_chat(chat_id)
    is_group = await _is_group_chat(bot, chat_id)
    linked_chat_id = await get_linked_chat_id(bot, chat_id)
    has_linked_chat = linked_chat_id is not None
    
    # Формируем текст меню скоринга
    text = f"🎯 <b>Настройки скоринга</b>\n\n"
    text += f"📝 Чат: {chat_data['title']}\n\n"
    text += f"✅ Скоринг <b>включен</b>\n"
    text += f"📊 Порог: <b>{threshold}</b>\n\n"
    
    if not is_group and has_linked_chat:
        text += f"📌 Собственный скоринг канала\n\n"
    
    text += "Юзеры со скором выше порога будут кикнуты."
    
    await message.answer(
        text,
        reply_markup=get_scoring_menu_keyboard(chat_id, is_group, has_linked_chat, True),
        parse_mode="HTML"
    )
    
    await state.clear()
