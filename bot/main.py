import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.database import db
from bot.handlers import setup, moderation, captcha, members, statistics

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Отключаем шумные логи aiogram о необработанных обновлениях
logging.getLogger('aiogram.event').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота"""
    
    # Проверка токена
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in .env file!")
        return
    
    # Инициализация бота
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Инициализация диспетчера с хранилищем состояний
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключение к БД
    logger.info("Connecting to database...")
    await db.connect()
    logger.info("Database connected!")
    
    # Регистрация роутеров
    dp.include_router(setup.router)
    dp.include_router(statistics.router)  # Статистика
    dp.include_router(moderation.router)  # Групповая модерация должна обрабатываться до капчи/участников
    dp.include_router(captcha.router)  # Капча должна быть ДО members (фильтр сообщений)
    dp.include_router(members.router)
    
    # Запуск polling
    logger.info("Starting bot...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True  # Пропускаем старые обновления при старте
        )
    finally:
        # Закрытие соединений при остановке
        await db.close()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
