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

        # === KICK ALL MODE ===
        if 'kick_all_active' not in column_names:
            print("➕ Добавляем kick_all_active...")
            await db.execute('ALTER TABLE chats ADD COLUMN kick_all_active BOOLEAN DEFAULT 0')
            print("✅ kick_all_active добавлен")
        else:
            print("✓ kick_all_active уже есть")

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
                DEFAULT '{"max_lang_risk": 25, "no_lang_risk": 15, "max_id_risk": 20, "premium_bonus": -20, "no_avatar_risk": 15, "one_avatar_risk": 5, "no_username_risk": 15, "weird_name_risk": 10, "exotic_script_risk": 25, "special_chars_risk": 15, "repeating_chars_risk": 5, "random_username_risk": 15}' ''')
            print("✅ scoring_weights добавлен")
        else:
            print("✓ scoring_weights уже есть")
            # Обновляем существующие веса: мигрируем arabic_cjk_risk -> exotic_script_risk и добавляем новые поля
            cursor = await db.execute('SELECT chat_id, scoring_weights FROM chats')
            rows = await cursor.fetchall()
            import json
            updated_count = 0
            for row in rows:
                if row['scoring_weights']:
                    weights = json.loads(row['scoring_weights'])
                    changed = False
                    
                    # Миграция arabic_cjk_risk -> exotic_script_risk
                    if 'arabic_cjk_risk' in weights and 'exotic_script_risk' not in weights:
                        weights['exotic_script_risk'] = weights.pop('arabic_cjk_risk')
                        changed = True
                    
                    # Добавление новых полей если их нет
                    if 'random_username_risk' not in weights:
                        weights['random_username_risk'] = 15
                        changed = True
                    if 'no_username_risk' in weights and weights['no_username_risk'] == 5:
                        weights['no_username_risk'] = 15
                        changed = True
                    if 'special_chars_risk' not in weights:
                        weights['special_chars_risk'] = 15
                        changed = True
                    if 'repeating_chars_risk' not in weights:
                        weights['repeating_chars_risk'] = 5
                        changed = True
                    
                    if changed:
                        await db.execute(
                            'UPDATE chats SET scoring_weights = ? WHERE chat_id = ?',
                            (json.dumps(weights), row['chat_id'])
                        )
                        updated_count += 1
            if updated_count > 0:
                print(f"✅ Мигрировано {updated_count} конфигураций: arabic_cjk_risk -> exotic_script_risk + новые поля")
        
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

        # === ONE-TIME SCORING EXEMPT ===
        print("\n🔎 Проверка scoring_exempt...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS scoring_exempt (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_scoring_exempt_chat ON scoring_exempt(chat_id, created_at)'
        )
        print("✅ scoring_exempt готов")

        # === ALLOWLIST USERS ===
        print("\n📋 Проверка allowlist_users...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS allowlist_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_allowlist_users_chat ON allowlist_users(chat_id, created_at)'
        )
        print("✅ allowlist_users готов")

        # === SCORING KICKS ===
        print("\n📈 Проверка scoring_kicks...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS scoring_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kicked_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_scoring_kicks_chat ON scoring_kicks(chat_id, kicked_at)'
        )
        print("✅ scoring_kicks готов")

        # === ATTACK KICKS ===
        print("\n⚔️ Проверка attack_kicks...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS attack_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kicked_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_attack_kicks_chat ON attack_kicks(chat_id, kicked_at)'
        )
        print("✅ attack_kicks готов")

        # === ALLOWLIST USERS ===
        print("\n📋 Проверка allowlist_users...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS allowlist_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_allowlist_users_chat ON allowlist_users(chat_id, created_at)'
        )
        print("✅ allowlist_users готов")

        # === SCORING KICKS ===
        print("\n📈 Проверка scoring_kicks...")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS scoring_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kicked_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_scoring_kicks_chat ON scoring_kicks(chat_id, kicked_at)'
        )
        print("✅ scoring_kicks готов")
        
        # === СКОР ДЛЯ УСПЕШНЫХ ПОЛЬЗОВАТЕЛЕЙ ===
        print("\n📊 Проверка good_users...")
        cursor = await db.execute("PRAGMA table_info(good_users)")
        good_users_columns = await cursor.fetchall()
        good_users_column_names = [col[1] for col in good_users_columns]
        
        need_recalc = False
        
        # Добавляем first_name
        if 'first_name' not in good_users_column_names:
            print("➕ Добавляем first_name в good_users...")
            await db.execute('ALTER TABLE good_users ADD COLUMN first_name TEXT')
            print("✅ first_name добавлен")
            need_recalc = True
        else:
            print("✓ first_name уже есть")
        
        # Добавляем last_name
        if 'last_name' not in good_users_column_names:
            print("➕ Добавляем last_name в good_users...")
            await db.execute('ALTER TABLE good_users ADD COLUMN last_name TEXT')
            print("✅ last_name добавлен")
            need_recalc = True
        else:
            print("✓ last_name уже есть")
        
        # Добавляем photo_count
        if 'photo_count' not in good_users_column_names:
            print("➕ Добавляем photo_count в good_users...")
            await db.execute('ALTER TABLE good_users ADD COLUMN photo_count INTEGER DEFAULT 0')
            print("✅ photo_count добавлен")
            need_recalc = True
        else:
            print("✓ photo_count уже есть")
        
        # Добавляем scoring_score
        if 'scoring_score' not in good_users_column_names:
            print("➕ Добавляем scoring_score в good_users...")
            await db.execute('ALTER TABLE good_users ADD COLUMN scoring_score INTEGER DEFAULT 0')
            print("✅ scoring_score добавлен")
            need_recalc = True
        else:
            print("✓ scoring_score уже есть")
        
        # Пересчитываем скоры для существующих пользователей
        if need_recalc:
            print("\n🔄 Пересчитываем скоры для существующих good_users...")
            from aiogram import Bot
            from bot.config import BOT_TOKEN
            from bot.utils.scoring import score_user, ScoringConfig, ScoringStats
            from bot.database import Database
            
            try:
                bot_instance = Bot(token=BOT_TOKEN)
                db_instance = Database()
                await db_instance.connect()
                
                # Получаем всех пользователей с неполными данными
                cursor = await db.execute('''
                    SELECT id, chat_id, user_id 
                    FROM good_users 
                    WHERE scoring_score = 0 OR scoring_score IS NULL 
                       OR first_name IS NULL OR photo_count = 0
                ''')
                users_to_update = await cursor.fetchall()
                
                total = len(users_to_update)
                print(f"Найдено {total} пользователей для обновления...")
                
                updated = 0
                skipped = 0
                
                for idx, row in enumerate(users_to_update, 1):
                    record_id = row[0]
                    chat_id = row[1]
                    user_id = row[2]
                    
                    if idx % 10 == 0:
                        print(f"  Обработано {idx}/{total}...")
                    
                    try:
                        # Получаем конфиг скоринга для чата
                        scoring_config_data = await db_instance.get_scoring_config(chat_id)
                        if not scoring_config_data:
                            skipped += 1
                            continue
                        
                        # Получаем реальные данные пользователя через API
                        try:
                            member = await bot_instance.get_chat_member(chat_id, user_id)
                            user_obj = member.user
                        except Exception:
                            # Пользователь не найден в чате
                            skipped += 1
                            continue
                        
                        # Получаем photo_count
                        photo_count = 0
                        try:
                            photos = await bot_instance.get_user_profile_photos(user_id, limit=100)
                            photo_count = photos.total_count
                        except Exception:
                            pass
                        
                        # Извлекаем данные из user_obj
                        first_name = user_obj.first_name
                        last_name = user_obj.last_name
                        username = user_obj.username
                        language_code = user_obj.language_code
                        is_premium = user_obj.is_premium or False
                        
                        # Получаем статистику для скоринга
                        stats_data = await db_instance.get_scoring_stats(chat_id, days=7)
                        
                        # Вычисляем скор
                        scoring_score = score_user(
                            user_obj,
                            photo_count=photo_count,
                            cfg=ScoringConfig(**scoring_config_data),
                            stats=ScoringStats(
                                lang_counts=stats_data['lang_counts'],
                                total_good_joins=stats_data['total_good_joins'],
                                p95_id=stats_data['p95_id'],
                                p99_id=stats_data['p99_id']
                            )
                        )
                        
                        # Обновляем ВСЕ поля
                        await db.execute('''
                            UPDATE good_users 
                            SET first_name = ?, last_name = ?, username = ?, 
                                language_code = ?, is_premium = ?, photo_count = ?,
                                scoring_score = ?
                            WHERE id = ?
                        ''', (first_name, last_name, username, language_code, is_premium,
                              photo_count, scoring_score, record_id))
                        updated += 1
                        
                    except Exception as e:
                        skipped += 1
                        if idx <= 5:  # Показываем только первые ошибки
                            print(f"    ⚠️ Ошибка для user {user_id}: {e}")
                
                await db.commit()
                await db_instance.close()
                await bot_instance.session.close()
                
                print(f"✅ Обновление завершено: обновлено {updated}, пропущено {skipped}")
                
            except Exception as e:
                print(f"⚠️ Не удалось обновить данные: {e}")
                print("  Данные будут собраны для новых пользователей автоматически")

        # === МИГРАЦИЯ failed_captcha_features -> failed_users ===
        print("\n🔄 Миграция failed_captcha_features -> failed_users...")
        
        # Проверяем существует ли старая таблица
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_captcha_features'"
        )
        has_old_table = await cursor.fetchone()
        
        # Проверяем существует ли новая таблица
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_users'"
        )
        has_new_table = await cursor.fetchone()
        
        if has_old_table and not has_new_table:
            print("➕ Переименовываем failed_captcha_features -> failed_users...")
            
            # Создаем новую таблицу с правильной структурой
            await db.execute('''
                CREATE TABLE failed_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    language_code TEXT,
                    is_premium BOOLEAN DEFAULT 0,
                    photo_count INTEGER DEFAULT 0,
                    scoring_score INTEGER DEFAULT 0,
                    failed_at INTEGER NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                )
            ''')
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_failed_users_chat ON failed_users(chat_id, failed_at)'
            )
            
            # Копируем данные из старой таблицы (только те поля, что есть в обеих)
            print("  Копируем данные...")
            await db.execute('''
                INSERT INTO failed_users (
                    id, chat_id, user_id, language_code, is_premium, 
                    photo_count, scoring_score, failed_at
                )
                SELECT 
                    id, chat_id, user_id, language_code, is_premium,
                    photo_count, scoring_score, failed_at
                FROM failed_captcha_features
            ''')
            
            # Удаляем старую таблицу
            await db.execute('DROP TABLE failed_captcha_features')
            print("✅ Миграция завершена, данные сохранены")
        elif has_old_table and has_new_table:
            print("⚠️ Обе таблицы существуют, удаляем старую...")
            await db.execute('DROP TABLE failed_captcha_features')
            print("✅ Старая таблица удалена")
        elif has_new_table:
            print("✓ Таблица failed_users уже существует")
        else:
            print("ℹ️ Обе таблицы отсутствуют, будет создана новая")

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
        
        # Добавляем поле scoring_score если его нет
        cursor = await db.execute("PRAGMA table_info(pending_captcha)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'scoring_score' not in columns:
            print("➕ Добавляем поле scoring_score в pending_captcha...")
            await db.execute('ALTER TABLE pending_captcha ADD COLUMN scoring_score INTEGER DEFAULT 0')
            print("✅ Поле scoring_score добавлено")
        
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
        
        # Таблица failed_users (для автообучения скоринга и экспериментов)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failed_users'"
        )
        if not await cursor.fetchone():
            print("➕ Создаём таблицу failed_users...")
            await db.execute('''
                CREATE TABLE failed_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    language_code TEXT,
                    is_premium BOOLEAN DEFAULT 0,
                    photo_count INTEGER DEFAULT 0,
                    scoring_score INTEGER DEFAULT 0,
                    failed_at INTEGER NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                )
            ''')
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_failed_users_chat ON failed_users(chat_id, failed_at)'
            )
            print("✅ Таблица failed_users создана")
        else:
            print("✓ Таблица failed_users уже есть")
        
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
