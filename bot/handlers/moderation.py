from typing import Sequence
import unicodedata
from aiogram import Router, F, Bot
from aiogram.types import Message
from bot.database import db
from bot.utils.message_utils import delete_message_later
import asyncio

router = Router()

_LATIN_TO_CYRILLIC = str.maketrans({
    "a": "а",
    "b": "в",
    "c": "с",
    "e": "е",
    "h": "н",
    "k": "к",
    "m": "м",
    "o": "о",
    "p": "р",
    "t": "т",
    "x": "х",
    "y": "у",
})


def _is_not_command(message: Message) -> bool:
    """True если сообщение не начинается с команды."""
    text = message.text or message.caption or ""
    return not text.startswith("/")


def _normalize_stop_word_text(text: str) -> str:
    """
    Нормализовать текст для проверки стоп-слов.
    Схлопывает часто используемые латинские омоглифы в кириллицу.
    """
    return text.lower().translate(_LATIN_TO_CYRILLIC)


def _strip_invisible_and_spaces(text: str) -> str:
    """
    Удалить невидимые символы форматирования, управляющие символы и пробелы.
    """
    result = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf":
            continue
        if category.startswith("C"):
            continue
        if ch.isspace():
            continue
        result.append(ch)
    return "".join(result)


def _contains_stop_word(text: str, words: Sequence[str]) -> bool:
    lowered = text.lower()
    normalized = _normalize_stop_word_text(text)
    compact_normalized = _strip_invisible_and_spaces(normalized)
    for word in words:
        if word in lowered:
            return True
        normalized_word = _normalize_stop_word_text(word)
        if normalized_word in normalized:
            return True
        if _strip_invisible_and_spaces(normalized_word) in compact_normalized:
            return True
    return False


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
    linked_channel_id = getattr(message.chat, "linked_chat_id", None)
    if linked_channel_id is None:
        try:
            chat_info = await bot.get_chat(chat_id)
            linked_channel_id = getattr(chat_info, "linked_chat_id", None)
        except Exception as e:
            print(f"[CHANNEL] Не удалось получить linked_chat_id для chat={chat_id}: {e}")
    sender_chat = message.sender_chat
    is_channel_post = sender_chat and sender_chat.type == "channel"

    if is_channel_post:
        # Если это сообщение от привязанного канала — не модерируем
        if linked_channel_id and sender_chat.id == linked_channel_id:
            return

        # Если запрещено писать от имени каналов
        if not allow_channel_posts:
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
