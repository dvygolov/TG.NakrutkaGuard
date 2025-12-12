"""Вспомогательные функции для работы с Telegram API"""
from typing import Optional
from aiogram import Bot
import logging

logger = logging.getLogger(__name__)


async def get_linked_chat_id(bot: Bot, chat_id: int) -> Optional[int]:
    """
    Получить ID связанного чата для канала (или наоборот).
    
    Для канала вернёт ID дискуссионной группы.
    Для группы вернёт ID связанного канала.
    
    Returns:
        linked_chat_id или None если нет связанного чата
    """
    try:
        chat = await bot.get_chat(chat_id)
        return chat.linked_chat_id if hasattr(chat, 'linked_chat_id') else None
    except Exception as e:
        logger.error(f"Ошибка получения linked_chat_id для {chat_id}: {e}")
        return None
