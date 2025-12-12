"""
Миграция БД для всех функций бота

Добавляет:
- Поля для капчи (captcha_enabled, welcome_message, rules_message, allow_channel_posts)
- Таблицу pending_captcha
- Поля для скоринга (scoring_enabled, scoring_threshold, scoring_lang_distribution)
- Таблицу good_users

Удаляет:
- Таблицу join_events (устарела, заменена на in-memory счётчик)

Запуск: python migrate_db.py
"""
import asyncio
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'bot.db'


async def migrate():
    print(f"🔄 Миграция БД: {DB_PATH}")
    
    if not DB_PATH.exists():
        print("❌ БД не найдена!")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Получаем список существующих полей в таблице chats
        cursor = await db.execute("PRAGMA table_info(chats)")
        columns = await cursor.fetchall()
        column_names = [col['name'] for col in columns]
        
        print("\n📋 Проверка и добавление полей в таблицу chats...")
        
        # === КАПЧА ===
        if 'captcha_enabled' not in column_names:
            print("➕ Добавляем captcha_enabled...")
            await db.execute('ALTER TABLE chats ADD COLUMN captcha_enabled BOOLEAN DEFAULT 0')
            print("✅ captcha_enabled добавлен")
        else:
            print("✓ captcha_enabled уже есть")
        
        if 'welcome_message' not in column_names:
            print("➕ Добавляем welcome_message...")
            await db.execute('ALTER TABLE chats ADD COLUMN welcome_message TEXT')
            print("✅ welcome_message добавлен")
        else:
            print("✓ welcome_message уже есть")

        if 'rules_message' not in column_names:
            print("➕ Добавляем rules_message...")
            await db.execute('ALTER TABLE chats ADD COLUMN rules_message TEXT')
            print("✅ rules_message добавлен")
        else:
            print("✓ rules_message уже есть")

        if 'allow_channel_posts' not in column_names:
            print("➕ Добавляем allow_channel_posts...")
            await db.execute('ALTER TABLE chats ADD COLUMN allow_channel_posts BOOLEAN DEFAULT 1')
            print("✅ allow_channel_posts добавлен")
        else:
            print("✓ allow_channel_posts уже есть")

        # === СКОРИНГ ===
        if 'scoring_enabled' not in column_names:
            print("➕ Добавляем scoring_enabled...")
            await db.execute('ALTER TABLE chats ADD COLUMN scoring_enabled BOOLEAN DEFAULT 0')
            print("✅ scoring_enabled добавлен")
        else:
            print("✓ scoring_enabled уже есть")
        
        if 'scoring_threshold' not in column_names:
            print("➕ Добавляем scoring_threshold...")
            await db.execute('ALTER TABLE chats ADD COLUMN scoring_threshold INTEGER DEFAULT 50')
            print("✅ scoring_threshold добавлен")
        else:
            print("✓ scoring_threshold уже есть")
        
        if 'scoring_lang_distribution' not in column_names:
            print("➕ Добавляем scoring_lang_distribution...")
            await db.execute('ALTER TABLE chats ADD COLUMN scoring_lang_distribution TEXT DEFAULT \'{"ru": 0.8, "en": 0.2}\'')
            print("✅ scoring_lang_distribution добавлен")
        else:
            print("✓ scoring_lang_distribution уже есть")
        
        # === ВЕСА СКОРИНГА (для автообучения) - JSON формат ===
        if 'scoring_weights' not in column_names:
            print("➕ Добавляем scoring_weights (JSON)...")
            await db.execute('''ALTER TABLE chats ADD COLUMN scoring_weights TEXT 
                DEFAULT '{"max_lang_risk": 25, "no_lang_risk": 15, "max_id_risk": 20, "premium_bonus": -20, "no_avatar_risk": 15, "one_avatar_risk": 5, "no_username_risk": 5, "weird_name_risk": 10, "arabic_cjk_risk": 25}' ''')
            print("✅ scoring_weights добавлен")
        else:
            print("✓ scoring_weights уже есть")
        
        if 'scoring_auto_adjust' not in column_names:
            print("➕ Добавляем scoring_auto_adjust...")
            await db.execute('ALTER TABLE chats ADD COLUMN scoring_auto_adjust BOOLEAN DEFAULT 1')
            print("✅ scoring_auto_adjust добавлен")
        else:
            print("✓ scoring_auto_adjust уже есть")
        
        # === СВЯЗАННЫЙ ЧАТ (для каналов) ===
        if 'use_linked_chat_scoring' not in column_names:
            print("➕ Добавляем use_linked_chat_scoring...")
            await db.execute('ALTER TABLE chats ADD COLUMN use_linked_chat_scoring BOOLEAN DEFAULT 0')
            print("✅ use_linked_chat_scoring добавлен")
        else:
            print("✓ use_linked_chat_scoring уже есть")
        
        if 'linked_chat_id' not in column_names:
            print("➕ Добавляем linked_chat_id...")
            await db.execute('ALTER TABLE chats ADD COLUMN linked_chat_id INTEGER')
            print("✅ linked_chat_id добавлен")
        else:
            print("✓ linked_chat_id уже есть")

        # === ТАБЛИЦЫ ===
        print("\n📋 Проверка и создание таблиц...")
        
        # Таблица pending_captcha
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_captcha'"
        )
        if not await cursor.fetchone():
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
                'CREATE INDEX IF NOT EXISTS idx_captcha_expires ON pending_captcha(expires_at)'
            )
            print("✅ Таблица pending_captcha создана")
        else:
            print("✓ Таблица pending_captcha уже есть")
        
        # Таблица good_users
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='good_users'"
        )
        if not await cursor.fetchone():
            print("➕ Создаём таблицу good_users...")
            await db.execute('''
                CREATE TABLE good_users (
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
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_good_users_chat ON good_users(chat_id, verified_at)'
            )
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_good_users_lookup ON good_users(chat_id, user_id)'
            )
            print("✅ Таблица good_users создана")
        else:
            print("✓ Таблица good_users уже есть")
        
        # Таблица failed_captcha_features (для автообучения скоринга)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_captcha_features'"
        )
        if not await cursor.fetchone():
            print("➕ Создаём таблицу failed_captcha_features...")
            await db.execute('''
                CREATE TABLE failed_captcha_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    language_code TEXT,
                    has_username BOOLEAN,
                    photo_count INTEGER,
                    name_has_latin_cyrillic BOOLEAN,
                    name_has_arabic_cjk BOOLEAN,
                    is_premium BOOLEAN,
                    scoring_score INTEGER,
                    failed_at INTEGER NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                )
            ''')
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_failed_captcha_chat ON failed_captcha_features(chat_id, failed_at)'
            )
            print("✅ Таблица failed_captcha_features создана")
        else:
            print("✓ Таблица failed_captcha_features уже есть")
        
        # === ОЧИСТКА УСТАРЕВШИХ ТАБЛИЦ ===
        print("\n🗑 Проверка устаревших таблиц...")
        
        # Удаляем join_events - больше не используется (заменён на in-memory счётчик)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='join_events'"
        )
        if await cursor.fetchone():
            print("➖ Удаляем устаревшую таблицу join_events...")
            await db.execute('DROP TABLE join_events')
            print("✅ Таблица join_events удалена")
        else:
            print("✓ Устаревших таблиц нет")
        
        await db.commit()
        
        # Вакуум для освобождения места
        print("\n🧹 Оптимизация БД...")
        await db.execute('VACUUM')
        print("✅ БД оптимизирована")
        
        print("\n✅ Миграция успешно завершена!")


if __name__ == '__main__':
    asyncio.run(migrate())
