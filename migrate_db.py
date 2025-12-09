"""
Миграция БД для добавления капчи
Добавляет:
- captcha_enabled в таблицу chats
- таблицу pending_captcha
"""
import asyncio
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'bot.db'


async def migrate():
    print(f"Миграция БД: {DB_PATH}")
    
    if not DB_PATH.exists():
        print("❌ БД не найдена!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Проверяем есть ли captcha_enabled
        cursor = await db.execute("PRAGMA table_info(chats)")
        columns = await cursor.fetchall()
        column_names = [col['name'] for col in columns]
        
        if 'captcha_enabled' not in column_names:
            print("➕ Добавляем captcha_enabled в chats...")
            await db.execute('ALTER TABLE chats ADD COLUMN captcha_enabled BOOLEAN DEFAULT 0')
            print("✅ captcha_enabled добавлен")
        else:
            print("✓ captcha_enabled уже есть")
        
        # 2. Проверяем есть ли таблица pending_captcha
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_captcha'"
        )
        table_exists = await cursor.fetchone()
        
        if not table_exists:
            print("➕ Создаём таблицу pending_captcha...")
            await db.execute('''
                CREATE TABLE pending_captcha (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    correct_answer TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, user_id),
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                )
            ''')
            await db.execute(
                'CREATE INDEX idx_captcha_expires ON pending_captcha(expires_at)'
            )
            print("✅ Таблица pending_captcha создана")
        else:
            print("✓ Таблица pending_captcha уже есть")
        
        await db.commit()
        print("\n✅ Миграция завершена!")


if __name__ == '__main__':
    asyncio.run(migrate())
