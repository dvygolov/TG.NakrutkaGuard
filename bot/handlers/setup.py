from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.database import db
from bot.config import ADMIN_IDS, DEFAULT_THRESHOLD, DEFAULT_TIME_WINDOW, DEFAULT_PROTECT_PREMIUM

router = Router()


class AddChatStates(StatesGroup):
    waiting_for_chat_id = State()


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
    try:
        chat_info = await callback.bot.get_chat(chat_id)
        is_group = chat_info.type in ["group", "supergroup"]
    except:
        is_group = True  # По умолчанию считаем группой
    
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
        text += f"\n🤖 Капча: {captcha}"
    
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
