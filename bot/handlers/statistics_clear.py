"""Handlers для очистки профиля успешных пользователей"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import db

router = Router()


@router.callback_query(F.data.startswith("clear_good_confirm_"))
async def confirm_clear_good_users(callback: CallbackQuery):
    """Подтверждение очистки профиля успешных"""
    chat_id = int(callback.data.split("_")[3])
    
    chat_data = await db.get_chat(chat_id)
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"⚠️ <b>Очистка профиля успешных: {chat_name}</b>\n\n"
    text += "Вы уверены, что хотите удалить все данные о прошедших верификацию пользователях?\n\n"
    text += "Это действие:\n"
    text += "• Удалит всю статистику успешных юзеров\n"
    text += "• Сбросит защиту от false positives\n"
    text += "• Начнёт собирать данные заново\n\n"
    text += "<b>Данное действие необратимо!</b>"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, очистить", callback_data=f"clear_good_execute_{chat_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"stats_success_{chat_id}")
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clear_good_execute_"))
async def execute_clear_good_users(callback: CallbackQuery):
    """Выполнить очистку профиля успешных"""
    chat_id = int(callback.data.split("_")[3])
    
    # Выполняем очистку
    deleted_count = await db.clear_good_users(chat_id)
    
    chat_data = await db.get_chat(chat_id)
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"✅ <b>Профиль очищен: {chat_name}</b>\n\n"
    text += f"Удалено записей: <b>{deleted_count}</b>\n\n"
    text += "Система начнёт собирать новые данные об успешных пользователях.\n"
    text += "Защита от false positives временно отключена до накопления минимум 30 записей."
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("Профиль успешно очищен!")
