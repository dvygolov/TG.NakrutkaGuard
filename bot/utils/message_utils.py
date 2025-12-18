import asyncio
import logging
from bot.utils.logger import chat_logger

logger = logging.getLogger(__name__)


async def delete_message_later(bot, chat_id: int, message_id: int, delay: int = 180, chat_username: str = None):
    """Удалить сообщение через delay секунд"""
    chat_name = chat_logger.get_chat_display_name(chat_id, chat_username)
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id, message_id)
        logger.info(f"AUTO-DELETE | Chat: {chat_name} | Message: {message_id}")
    except asyncio.CancelledError:
        logger.debug(f"AUTO-DELETE CANCELLED | Chat: {chat_name} | Message: {message_id}")
        raise
    except Exception as e:
        logger.warning(f"AUTO-DELETE FAILED | Chat: {chat_name} | Message: {message_id} | Error: {e}")
