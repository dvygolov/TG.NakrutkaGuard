import asyncio


def _log(msg: str):
    print(f"[AUTO-DELETE] {msg}")


async def delete_message_later(bot, chat_id: int, message_id: int, delay: int = 180):
    """Удалить сообщение через delay секунд"""
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id, message_id)
        _log(f"Удалено сообщение {message_id} в чате {chat_id}")
    except asyncio.CancelledError:
        _log(f"Отмена удаления сообщения {message_id} в чате {chat_id}")
        raise
    except Exception as e:
        _log(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")
