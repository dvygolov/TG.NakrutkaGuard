from typing import Sequence
from aiogram import Router, F, Bot
from aiogram.types import Message
from bot.database import db
from bot.utils.message_utils import delete_message_later
import asyncio

router = Router()


def _is_not_command(message: Message) -> bool:
    """True если сообщение не начинается с команды."""
    text = message.text or message.caption or ""
    return not text.startswith("/")


def _contains_stop_word(text: str, words: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


@router.message(_is_not_command, F.chat.type.in_({"group", "supergroup"}))
async def handle_group_messages(message: Message, bot: Bot):
    """Обработка сообщений в группах: чистим системные, pending-пользователей и стоп-слова."""
    chat_id = message.chat.id
    chat_data = await db.get_chat(chat_id)
    if not chat_data:
        return

    # 1. Системные сообщения (join/left)
    if message.new_chat_members or message.left_chat_member:
        try:
            await bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            print(f"[SYSTEM] Не удалось удалить системное сообщение: {e}")
        return

    # 1.5. Проверка сообщений от каналов (если запрещено)
    allow_channel_posts = chat_data.get('allow_channel_posts', True)
    if not allow_channel_posts and message.sender_chat and not message.from_user:
        try:
            await bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            print(f"[CHANNEL] Не удалось удалить канал-сообщение: {e}")
        try:
            warning = await bot.send_message(chat_id, "Запрещено писать в чат от имени каналов!")
            asyncio.create_task(delete_message_later(bot, chat_id, warning.message_id, delay=60))
        except Exception as e:
            print(f"[CHANNEL] Не удалось отправить предупреждение: {e}")
        return

    # 2. Pending капча
    if message.from_user:
        user_id = message.from_user.id
        pending = await db.get_pending_captcha(chat_id, user_id)
        if pending:
            try:
                await bot.delete_message(chat_id, message.message_id)
            except Exception as e:
                print(f"[CAPTCHA] Ошибка удаления сообщения pending user {user_id}: {e}")
            return

    # 3. Стоп-слова
    stop_words = await db.get_stop_words(chat_id)
    if not stop_words:
        return

    content_parts = [message.text, message.caption]
    text_content = " ".join(filter(None, content_parts))
    if not text_content:
        return

    if _contains_stop_word(text_content, stop_words):
        try:
            await bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            print(f"[STOP_WORD] Не удалось удалить message_id={message.message_id}: {e}")
