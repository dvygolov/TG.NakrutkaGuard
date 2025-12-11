"""
Миграция БД для добавления функциональности скоринга.
Добавляет в таблицу chats новые поля для скоринга и создаёт таблицу good_users.

Запуск: python migrate_scoring.py
"""
import asyncio
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'bot.db'


async def migrate():
    print(f"Подключение к БД: {DB_PATH}")
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    
    try:
        # Проверяем существование полей скоринга
        async with conn.execute("PRAGMA table_info(chats)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col['name'] for col in columns]
        
        # Добавляем новые поля если их нет
        if 'scoring_enabled' not in column_names:
            print("Добавление поля scoring_enabled...")
            await conn.execute(
                "ALTER TABLE chats ADD COLUMN scoring_enabled BOOLEAN DEFAULT 0"
            )
            await conn.commit()
            print("✓ scoring_enabled добавлено")
        else:
            print("✓ scoring_enabled уже существует")
        
        if 'scoring_threshold' not in column_names:
            print("Добавление поля scoring_threshold...")
            await conn.execute(
                "ALTER TABLE chats ADD COLUMN scoring_threshold INTEGER DEFAULT 50"
            )
            await conn.commit()
            print("✓ scoring_threshold добавлено")
        else:
            print("✓ scoring_threshold уже существует")
        
        if 'scoring_lang_distribution' not in column_names:
            print("Добавление поля scoring_lang_distribution...")
            await conn.execute(
                'ALTER TABLE chats ADD COLUMN scoring_lang_distribution TEXT DEFAULT \'{"ru": 0.8, "en": 0.2}\''
            )
            await conn.commit()
            print("✓ scoring_lang_distribution добавлено")
        else:
            print("✓ scoring_lang_distribution уже существует")
        
        # Создаём таблицу good_users если её нет
        print("\nСоздание таблицы good_users...")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS good_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                language_code TEXT,
                is_premium BOOLEAN DEFAULT 0,
                verified_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await conn.commit()
        print("✓ Таблица good_users создана (или уже существует)")
        
        # Создаём индексы если их нет
        print("\nСоздание индексов...")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_good_users_chat ON good_users(chat_id, verified_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_good_users_lookup ON good_users(chat_id, user_id)"
        )
        await conn.commit()
        print("✓ Индексы созданы")
        
        print("\n✅ Миграция успешно завершена!")
        
    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
