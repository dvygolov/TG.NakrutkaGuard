from typing import Optional, List, Callable, Awaitable, Any
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.database import db
from bot.config import ADMIN_IDS, DEFAULT_THRESHOLD, DEFAULT_TIME_WINDOW, DEFAULT_PROTECT_PREMIUM
import html

router = Router()

OFF_KEYWORDS = {"off", "disable", "none", "0"}


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
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")],
        [InlineKeyboardButton(text="📋 Список чатов", callback_data="list_chats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chat_settings_keyboard(chat_id: int, is_group: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура настроек конкретного чата"""
    buttons = [
        [InlineKeyboardButton(text="⚙️ Изменить порог", callback_data=f"set_threshold_{chat_id}")],
        [InlineKeyboardButton(text="⏱ Изменить окно", callback_data=f"set_window_{chat_id}")],
        [InlineKeyboardButton(text="👑 Premium защита", callback_data=f"toggle_premium_{chat_id}")],
    ]
    
    # Капча только для групп (не для каналов)
    if is_group:
        buttons.append([InlineKeyboardButton(text="🤖 Капча для вступающих", callback_data=f"toggle_captcha_{chat_id}")])
        buttons.append([
            InlineKeyboardButton(text="👋 Приветствие", callback_data=f"set_welcome_{chat_id}"),
            InlineKeyboardButton(text="📜 Правила /rules", callback_data=f"set_rules_{chat_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="🚫 Стоп-слова", callback_data=f"set_stopwords_{chat_id}")
        ])
    
    buttons.extend([
        [InlineKeyboardButton(text="🗑 Удалить чат", callback_data=f"remove_chat_{chat_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="list_chats")],
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_admin(user_id: int) -> bool:
    """Проверка является ли пользователь админом"""
    return user_id in ADMIN_IDS


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет доступа к этому боту.")
        return
    
    await message.answer(
        "🛡 <b>Nakrutka Guard Bot</b>\n\n"
        "Бот для защиты телеграм-групп и каналов от накрутки.\n\n"
        "Используйте меню ниже для управления:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    """Показать главное меню"""
    await callback.message.edit_text(
        "🛡 <b>Nakrutka Guard Bot</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )
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
        reply_markup=get_main_menu_keyboard()
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
    chat_data = await db.get_chat(chat_id)
    
    if not chat_data:
        await callback.answer("❌ Чат не найден", show_alert=True)
        return
    
    # Определяем тип чата
    is_group = await _is_group_chat(callback.bot, chat_id)
    
    status = "🟢 АКТИВЕН" if chat_data['protection_active'] else "⚪️ ВЫКЛЮЧЕН"
    premium = "✅ Да" if chat_data['protect_premium'] else "❌ Нет"
    captcha = "✅ Да" if chat_data.get('captcha_enabled', False) else "❌ Нет"
    
    # Формируем текст
    text = (
        f"⚙️ <b>Настройки чата</b>\n\n"
        f"📝 Название: {chat_data['title']}\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"👤 Username: @{chat_data['username'] or 'нет'}\n\n"
        f"🛡 Режим защиты: {status}\n"
        f"📊 Порог: {chat_data['threshold']} вступлений\n"
        f"⏱ Временное окно: {chat_data['time_window']} секунд\n"
        f"👑 Защита Premium: {premium}"
    )
    
    # Добавляем капчу только для групп
    if is_group:
        welcome_status = "✅ Настроено" if chat_data.get('welcome_message') else "⚪️ Нет"
        rules_status = "✅ Настроены" if chat_data.get('rules_message') else "⚪️ Нет"
        stop_words = await db.get_stop_words(chat_id)
        stop_words_status = f"{len(stop_words)} шт." if stop_words else "⚪️ Нет"
        text += (
            f"\n🤖 Капча: {captcha}"
            f"\n👋 Приветствие: {welcome_status}"
            f"\n📜 Правила /rules: {rules_status}"
            f"\n🚫 Стоп-слова: {stop_words_status}"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_chat_settings_keyboard(chat_id, is_group),
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
