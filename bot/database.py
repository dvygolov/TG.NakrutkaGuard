import aiosqlite
import time
import json
import logging
from typing import Optional, List, Dict, Any
from bot.config import DB_PATH
from bot.utils.username_analysis import username_randomness
from bot.utils.name_checks import has_latin_or_cyrillic, has_exotic_script

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Подключение к БД и создание таблиц"""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._init_tables()

    async def close(self):
        """Закрытие соединения"""
        if self._connection:
            await self._connection.close()

    async def _init_tables(self):
        """Создание таблиц если не существуют"""
        await self._connection.executescript('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                username TEXT,
                threshold INTEGER DEFAULT 10,
                time_window INTEGER DEFAULT 60,
                protection_active BOOLEAN DEFAULT 0,
                kick_all_active BOOLEAN DEFAULT 0,
                protect_premium BOOLEAN DEFAULT 1,
                allow_channel_posts BOOLEAN DEFAULT 1,
                captcha_enabled BOOLEAN DEFAULT 0,
                welcome_message TEXT,
                rules_message TEXT,
                added_at INTEGER NOT NULL,
                scoring_enabled BOOLEAN DEFAULT 0,
                scoring_threshold INTEGER DEFAULT 50,
                scoring_lang_distribution TEXT DEFAULT '{"ru": 0.8, "en": 0.2}',
                scoring_weights TEXT DEFAULT '{"max_lang_risk": 25, "no_lang_risk": 15, "max_id_risk": 20, "premium_bonus": -20, "no_avatar_risk": 15, "one_avatar_risk": 5, "no_username_risk": 15, "weird_name_risk": 10, "exotic_script_risk": 25, "special_chars_risk": 15, "repeating_chars_risk": 5, "random_username_risk": 15}',
                scoring_auto_adjust BOOLEAN DEFAULT 1,
                use_linked_chat_scoring BOOLEAN DEFAULT 0,
                linked_chat_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS attack_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER,
                total_kicked INTEGER DEFAULT 0,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE TABLE IF NOT EXISTS pending_captcha (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                correct_answer TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_captcha_expires ON pending_captcha(expires_at);

            CREATE TABLE IF NOT EXISTS stop_words (
                chat_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                PRIMARY KEY (chat_id, word),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE TABLE IF NOT EXISTS good_users (
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
                verified_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_good_users_chat ON good_users(chat_id, verified_at);
            CREATE INDEX IF NOT EXISTS idx_good_users_lookup ON good_users(chat_id, user_id);

            CREATE TABLE IF NOT EXISTS failed_users (
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
            );

            CREATE INDEX IF NOT EXISTS idx_failed_users_chat ON failed_users(chat_id, failed_at);

            CREATE TABLE IF NOT EXISTS scoring_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kicked_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_scoring_kicks_chat ON scoring_kicks(chat_id, kicked_at);

            CREATE TABLE IF NOT EXISTS attack_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kicked_at INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_attack_kicks_chat ON attack_kicks(chat_id, kicked_at);

            CREATE TABLE IF NOT EXISTS scoring_exempt (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_scoring_exempt_chat ON scoring_exempt(chat_id, created_at);

            CREATE TABLE IF NOT EXISTS allowlist_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_allowlist_users_chat ON allowlist_users(chat_id, created_at);

            CREATE TABLE IF NOT EXISTS scoring_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                trigger_samples INTEGER NOT NULL,
                old_threshold INTEGER,
                new_threshold INTEGER,
                old_weights_json TEXT,
                new_weights_json TEXT,
                changes_text TEXT NOT NULL,
                reason_json TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_scoring_adjustments_chat
                ON scoring_adjustments(chat_id, created_at);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
        ''')
        await self._connection.commit()

        # Мягкая миграция: CREATE TABLE IF NOT EXISTS не добавляет новые колонки
        async with self._connection.execute("PRAGMA table_info(chats)") as cursor:
            columns = await cursor.fetchall()
        existing_columns = {row["name"] for row in columns}
        required_chat_columns = {
            "kick_all_active": "BOOLEAN DEFAULT 0",
            "captcha_enabled": "BOOLEAN DEFAULT 0",
            "welcome_message": "TEXT",
            "rules_message": "TEXT",
            "allow_channel_posts": "BOOLEAN DEFAULT 1",
            "scoring_enabled": "BOOLEAN DEFAULT 0",
            "scoring_threshold": "INTEGER DEFAULT 50",
            "scoring_lang_distribution": "TEXT DEFAULT '{\"ru\": 0.8, \"en\": 0.2}'",
            "scoring_weights": (
                "TEXT DEFAULT "
                "'{\"max_lang_risk\": 25, \"no_lang_risk\": 15, \"max_id_risk\": 20, "
                "\"premium_bonus\": -20, \"no_avatar_risk\": 15, \"one_avatar_risk\": 5, "
                "\"no_username_risk\": 15, \"weird_name_risk\": 10, \"exotic_script_risk\": 25, "
                "\"special_chars_risk\": 15, \"repeating_chars_risk\": 5, "
                "\"random_username_risk\": 15}'"
            ),
            "scoring_auto_adjust": "BOOLEAN DEFAULT 1",
            "use_linked_chat_scoring": "BOOLEAN DEFAULT 0",
            "linked_chat_id": "INTEGER",
        }
        added_columns = []
        for column_name, column_def in required_chat_columns.items():
            if column_name in existing_columns:
                continue
            await self._connection.execute(
                f"ALTER TABLE chats ADD COLUMN {column_name} {column_def}"
            )
            added_columns.append(column_name)

        if added_columns:
            await self._connection.commit()
            logger.warning(
                "Applied startup DB migration for chats: added missing columns %s",
                ", ".join(added_columns),
            )

    # === CHATS ===

    async def add_chat(self, chat_id: int, title: str, username: Optional[str] = None,
                      threshold: int = 10, time_window: int = 60, protect_premium: bool = True):
        """Добавить чат под защиту"""
        await self._connection.execute('''
            INSERT OR REPLACE INTO chats (chat_id, title, username, threshold, time_window, 
                                         protection_active, protect_premium, allow_channel_posts,
                                         captcha_enabled, welcome_message, rules_message, added_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, 1, 0, NULL, NULL, ?)
        ''', (chat_id, title, username, threshold, time_window, protect_premium, int(time.time())))
        await self._connection.commit()

    async def get_chat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить настройки чата"""
        async with self._connection.execute(
            'SELECT * FROM chats WHERE chat_id = ?', (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_chat_settings(self, chat_id: int, **kwargs):
        """Обновить настройки чата"""
        fields = ', '.join(f'{k} = ?' for k in kwargs.keys())
        values = list(kwargs.values()) + [chat_id]
        await self._connection.execute(
            f'UPDATE chats SET {fields} WHERE chat_id = ?', values
        )
        await self._connection.commit()

    async def set_protection_active(self, chat_id: int, active: bool) -> bool:
        """Включить/выключить режим защиты. Возвращает True если состояние изменилось."""
        if active:
            query = '''
                UPDATE chats
                SET protection_active = 1
                WHERE chat_id = ? AND protection_active = 0
            '''
        else:
            query = '''
                UPDATE chats
                SET protection_active = 0
                WHERE chat_id = ? AND protection_active = 1
            '''
        cursor = await self._connection.execute(query, (chat_id,))
        await self._connection.commit()
        return cursor.rowcount > 0

    async def is_protection_active(self, chat_id: int) -> bool:
        """Проверить активен ли режим защиты"""
        async with self._connection.execute(
            'SELECT protection_active FROM chats WHERE chat_id = ?', (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row['protection_active']) if row else False

    async def get_all_chats(self) -> List[Dict[str, Any]]:
        """Получить все чаты"""
        async with self._connection.execute('SELECT * FROM chats') as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def find_user_id_by_username(self, chat_id: int, username: str) -> Optional[int]:
        """Найти user_id по username в пределах чата."""
        normalized = username.lstrip("@").lower()
        query = (
            "SELECT user_id, failed_at AS ts FROM failed_users "
            "WHERE chat_id = ? AND lower(username) = ? "
            "UNION ALL "
            "SELECT user_id, verified_at AS ts FROM good_users "
            "WHERE chat_id = ? AND lower(username) = ? "
            "ORDER BY ts DESC LIMIT 1"
        )
        async with self._connection.execute(
            query, (chat_id, normalized, chat_id, normalized)
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["user_id"]) if row else None

    async def find_user_id_global_by_username(self, username: str) -> Optional[int]:
        """Найти user_id по username во всех чатах."""
        normalized = username.lstrip("@").lower()
        query = (
            "SELECT user_id, failed_at AS ts FROM failed_users "
            "WHERE lower(username) = ? "
            "UNION ALL "
            "SELECT user_id, verified_at AS ts FROM good_users "
            "WHERE lower(username) = ? "
            "ORDER BY ts DESC LIMIT 1"
        )
        async with self._connection.execute(
            query, (normalized, normalized)
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["user_id"]) if row else None

    async def remove_chat(self, chat_id: int):
        """Удалить чат из защиты"""
        await self._connection.execute('DELETE FROM chats WHERE chat_id = ?', (chat_id,))
        await self._connection.commit()

    # === APP SETTINGS ===

    async def set_app_setting(self, key: str, value: str):
        """Сохранить глобальную настройку приложения."""
        await self._connection.execute(
            '''
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            ''',
            (key, value, int(time.time()))
        )
        await self._connection.commit()

    async def get_app_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Получить глобальную настройку приложения."""
        async with self._connection.execute(
            'SELECT value FROM app_settings WHERE key = ?',
            (key,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return default
            return row['value']

    async def get_daily_digest_settings(self) -> Dict[str, Any]:
        """Получить глобальные настройки ежедневного дайджеста."""
        enabled_raw = await self.get_app_setting("daily_digest_enabled", "0")
        hour_raw = await self.get_app_setting("daily_digest_hour", "9")
        minute_raw = await self.get_app_setting("daily_digest_minute", "0")

        try:
            hour = int(hour_raw)
        except (TypeError, ValueError):
            hour = 9
        try:
            minute = int(minute_raw)
        except (TypeError, ValueError):
            minute = 0

        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        enabled = str(enabled_raw).strip().lower() in {"1", "true", "yes", "on"}

        return {
            "enabled": enabled,
            "hour": hour,
            "minute": minute,
        }

    async def set_daily_digest_settings(
        self,
        *,
        enabled: Optional[bool] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None
    ):
        """Обновить глобальные настройки ежедневного дайджеста."""
        if enabled is not None:
            await self.set_app_setting("daily_digest_enabled", "1" if enabled else "0")
        if hour is not None:
            await self.set_app_setting("daily_digest_hour", str(hour))
        if minute is not None:
            await self.set_app_setting("daily_digest_minute", str(minute))

    async def add_scoring_exempt(self, chat_id: int, user_id: int):
        """Добавить пользователя в список одноразового пропуска скоринга."""
        await self._connection.execute(
            'INSERT OR REPLACE INTO scoring_exempt (chat_id, user_id, created_at) VALUES (?, ?, ?)',
            (chat_id, user_id, int(time.time()))
        )
        await self._connection.commit()

    async def pop_scoring_exempt(self, chat_id: int, user_id: int) -> bool:
        """Снять одноразовый пропуск скоринга. Возвращает True если был пропуск."""
        cursor = await self._connection.execute(
            'DELETE FROM scoring_exempt WHERE chat_id = ? AND user_id = ?',
            (chat_id, user_id)
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def add_allowlisted_user(self, chat_id: int, user_id: int):
        """Добавить пользователя в allowlist чата."""
        await self._connection.execute(
            'INSERT OR REPLACE INTO allowlist_users (chat_id, user_id, created_at) VALUES (?, ?, ?)',
            (chat_id, user_id, int(time.time()))
        )
        await self._connection.commit()

    async def is_allowlisted_user(self, chat_id: int, user_id: int) -> bool:
        """Проверить, что пользователь в allowlist."""
        async with self._connection.execute(
            'SELECT 1 FROM allowlist_users WHERE chat_id = ? AND user_id = ? LIMIT 1',
            (chat_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row)

    # === JOIN EVENTS - DEPRECATED ===
    # Все методы удалены, т.к. подсчёт вступлений перенесён в in-memory счётчик
    # См. bot/utils/join_counter.py

    # === ATTACK SESSIONS ===

    async def start_attack_session(self, chat_id: int, start_time: Optional[int] = None) -> int:
        """Начать новую сессию атаки"""
        start_time = start_time or int(time.time())
        cursor = await self._connection.execute('''
            INSERT INTO attack_sessions (chat_id, start_time)
            VALUES (?, ?)
        ''', (chat_id, start_time))
        await self._connection.commit()
        return cursor.lastrowid

    async def end_attack_session(self, chat_id: int):
        """Завершить текущую сессию атаки"""
        await self._connection.execute('''
            UPDATE attack_sessions SET end_time = ?
            WHERE chat_id = ? AND end_time IS NULL
        ''', (int(time.time()), chat_id))
        await self._connection.commit()

    async def increment_kicked(self, chat_id: int):
        """Увеличить счётчик кикнутых в текущей атаке"""
        await self._connection.execute('''
            UPDATE attack_sessions SET total_kicked = total_kicked + 1
            WHERE chat_id = ? AND end_time IS NULL
        ''', (chat_id,))
        await self._connection.commit()

    async def get_current_attack_stats(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить статистику текущей атаки"""
        async with self._connection.execute('''
            SELECT * FROM attack_sessions 
            WHERE chat_id = ? AND end_time IS NULL
            ORDER BY start_time DESC LIMIT 1
        ''', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_last_attack_stats(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить статистику последней завершённой атаки"""
        async with self._connection.execute('''
            SELECT * FROM attack_sessions 
            WHERE chat_id = ? AND end_time IS NOT NULL
            ORDER BY end_time DESC LIMIT 1
        ''', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # === CAPTCHA ===

    async def add_pending_captcha(self, chat_id: int, user_id: int, message_id: int, 
                                  correct_answer: str, expires_at: int, scoring_score: int = 0):
        """Добавить юзера в ожидание прохождения капчи"""
        await self._connection.execute('''
            INSERT OR REPLACE INTO pending_captcha 
            (chat_id, user_id, message_id, correct_answer, created_at, expires_at, scoring_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, message_id, correct_answer, int(time.time()), expires_at, scoring_score))
        await self._connection.commit()

    async def get_pending_captcha(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить данные капчи для юзера"""
        async with self._connection.execute('''
            SELECT * FROM pending_captcha WHERE chat_id = ? AND user_id = ?
        ''', (chat_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def remove_pending_captcha(self, chat_id: int, user_id: int):
        """Удалить капчу из pending (юзер прошёл или забанен)"""
        await self._connection.execute('''
            DELETE FROM pending_captcha WHERE chat_id = ? AND user_id = ?
        ''', (chat_id, user_id))
        await self._connection.commit()

    async def get_expired_captchas(self) -> List[Dict[str, Any]]:
        """Получить все просроченные капчи"""
        current_time = int(time.time())
        async with self._connection.execute('''
            SELECT * FROM pending_captcha WHERE expires_at <= ?
        ''', (current_time,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def is_captcha_enabled(self, chat_id: int) -> bool:
        """Проверить включена ли капча для чата"""
        async with self._connection.execute(
            'SELECT captcha_enabled FROM chats WHERE chat_id = ?', (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row['captcha_enabled']) if row else False

    # === STOP WORDS ===

    async def get_stop_words(self, chat_id: int) -> List[str]:
        """Получить список стоп-слов для чата"""
        async with self._connection.execute(
            'SELECT word FROM stop_words WHERE chat_id = ? ORDER BY word',
            (chat_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row['word'] for row in rows]

    async def set_stop_words(self, chat_id: int, words: List[str]):
        """Заменить список стоп-слов для чата"""
        await self._connection.execute(
            'DELETE FROM stop_words WHERE chat_id = ?',
            (chat_id,)
        )

        normalized = [word.lower() for word in words if word.strip()]
        unique_words = sorted(set(normalized))

        if unique_words:
            await self._connection.executemany(
                'INSERT INTO stop_words (chat_id, word) VALUES (?, ?)',
                [(chat_id, word) for word in unique_words]
            )
        await self._connection.commit()

    # === SCORING ===

    async def is_scoring_enabled(self, chat_id: int) -> bool:
        """Проверить включен ли скоринг для чата"""
        async with self._connection.execute(
            'SELECT scoring_enabled FROM chats WHERE chat_id = ?', (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row['scoring_enabled']) if row else False
    
    async def set_linked_chat_scoring(self, chat_id: int, enabled: bool, linked_chat_id: Optional[int] = None):
        """Включить/выключить использование скоринга связанного чата"""
        await self._connection.execute('''
            UPDATE chats SET use_linked_chat_scoring = ?, linked_chat_id = ?
            WHERE chat_id = ?
        ''', (enabled, linked_chat_id, chat_id))
        await self._connection.commit()
    
    async def get_linked_chat_info(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить информацию о связанном чате"""
        async with self._connection.execute('''
            SELECT use_linked_chat_scoring, linked_chat_id FROM chats WHERE chat_id = ?
        ''', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                'use_linked_chat_scoring': bool(row['use_linked_chat_scoring']),
                'linked_chat_id': row['linked_chat_id']
            }

    async def get_scoring_config(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить конфиг скоринга для чата/канала"""
        async with self._connection.execute('''
            SELECT scoring_threshold, scoring_lang_distribution, scoring_weights, scoring_auto_adjust,
                   use_linked_chat_scoring, linked_chat_id
            FROM chats WHERE chat_id = ?
        ''', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            
            # Если канал использует скоринг связанного чата
            if row['use_linked_chat_scoring'] and row['linked_chat_id']:
                logger.debug(f"Chat {chat_id}: использует скоринг из связанного чата {row['linked_chat_id']}")
                # Рекурсивно получаем конфиг из связанного чата
                return await self.get_scoring_config(row['linked_chat_id'])
            
            # Парсим веса из JSON
            weights = json.loads(row['scoring_weights']) if row['scoring_weights'] else {}
            
            return {
                'threshold': row['scoring_threshold'],
                'lang_distribution': json.loads(row['scoring_lang_distribution']),
                'max_lang_risk': weights.get('max_lang_risk', 25),
                'no_lang_risk': weights.get('no_lang_risk', 15),
                'max_id_risk': weights.get('max_id_risk', 20),
                'premium_bonus': weights.get('premium_bonus', -20),
                'no_avatar_risk': weights.get('no_avatar_risk', 15),
                'one_avatar_risk': weights.get('one_avatar_risk', 5),
                'no_username_risk': weights.get('no_username_risk', 15),
                'weird_name_risk': weights.get('weird_name_risk', 10),
                'exotic_script_risk': weights.get('exotic_script_risk', weights.get('arabic_cjk_risk', 25)),
                'special_chars_risk': weights.get('special_chars_risk', 15),
                'repeating_chars_risk': weights.get('repeating_chars_risk', 5),
                'random_username_risk': weights.get('random_username_risk', 15),
                'auto_adjust': bool(row['scoring_auto_adjust'])
            }

    async def add_good_user(self, chat_id: int, user_id: int, 
                           first_name: Optional[str], last_name: Optional[str],
                           username: Optional[str], language_code: Optional[str], 
                           is_premium: bool, photo_count: int,
                           scoring_score: int = 0):
        """Добавить пользователя в список прошедших верификацию (для статистики)"""
        await self._connection.execute('''
            INSERT INTO good_users (
                chat_id, user_id, first_name, last_name, username, language_code, 
                is_premium, photo_count, scoring_score, verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, first_name, last_name, username, language_code, 
              is_premium, photo_count, scoring_score, int(time.time())))
        await self._connection.commit()

    async def add_failed_user(self, chat_id: int, user_id: int,
                             first_name: Optional[str], last_name: Optional[str],
                             username: Optional[str], language_code: Optional[str],
                             is_premium: bool, photo_count: int,
                             scoring_score: int = 0):
        """Добавить пользователя, не прошедшего капчу (для статистики и экспериментов)"""
        await self._connection.execute('''
            INSERT INTO failed_users (
                chat_id, user_id, first_name, last_name, username, language_code,
                is_premium, photo_count, scoring_score, failed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, first_name, last_name, username, language_code,
              is_premium, photo_count, scoring_score, int(time.time())))
        await self._connection.commit()

    async def add_scoring_kick(self, chat_id: int, user_id: int):
        """Добавить запись о кике пользователя скорингом (для статистики)."""
        await self._connection.execute('''
            INSERT INTO scoring_kicks (chat_id, user_id, kicked_at)
            VALUES (?, ?, ?)
        ''', (chat_id, user_id, int(time.time())))
        await self._connection.commit()

    async def add_attack_kick(self, chat_id: int, user_id: int):
        """Добавить запись о кике пользователя во время атаки."""
        await self._connection.execute('''
            INSERT INTO attack_kicks (chat_id, user_id, kicked_at)
            VALUES (?, ?, ?)
        ''', (chat_id, user_id, int(time.time())))
        await self._connection.commit()
    
    async def get_failed_captcha_stats(self, chat_id: int, days: int = 7, 
                                       min_samples: int = 30) -> Optional[Dict[str, Any]]:
        """Получить статистику неудачных пользователей для автокорректировки"""
        cutoff_time = int(time.time()) - (days * 24 * 60 * 60)
        
        # Проверяем достаточно ли данных
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            total = row['count'] if row else 0
            
            if total < min_samples:
                return None  # Недостаточно данных для корректировки
        
        # Собираем статистику по признакам
        stats = {'total_failed': total}
        
        # Процент без username
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ? AND (username IS NULL OR username = '')
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['no_username_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Процент рандомных username (пересчитываем на лету)
        from bot.utils.username_analysis import username_randomness
        async with self._connection.execute('''
            SELECT username FROM failed_users
            WHERE chat_id = ? AND failed_at >= ? AND username IS NOT NULL AND username != ''
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            random_username_count = 0
            for row in rows:
                result = username_randomness(row['username'], threshold=0.70)
                if result.is_randomish:
                    random_username_count += 1
            stats['random_username_rate'] = (random_username_count / total) if total > 0 else 0
        
        # Вычисляем характеристики имени используя общие функции
        async with self._connection.execute('''
            SELECT first_name, last_name FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            arabic_cjk_count = 0
            weird_name_count = 0
            for row in rows:
                full_name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
                if has_exotic_script(full_name):
                    arabic_cjk_count += 1
                if not has_latin_or_cyrillic(full_name):
                    weird_name_count += 1
            
            stats['arabic_cjk_rate'] = (arabic_cjk_count / total) if total > 0 else 0
            stats['weird_name_rate'] = (weird_name_count / total) if total > 0 else 0
        
        # Распределение по photo_count
        async with self._connection.execute('''
            SELECT photo_count, COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
            GROUP BY photo_count
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            photo_dist = {row['photo_count']: row['count'] / total for row in rows}
            stats['no_avatar_rate'] = photo_dist.get(0, 0)
            stats['one_avatar_rate'] = photo_dist.get(1, 0)
        
        # Топ языков неудачников
        async with self._connection.execute('''
            SELECT language_code, COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ? AND language_code IS NOT NULL
            GROUP BY language_code
            ORDER BY count DESC
            LIMIT 5
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            stats['top_failed_langs'] = {row['language_code']: row['count'] / total for row in rows}
        
        # Средний scoring_score среди неудачников
        async with self._connection.execute('''
            SELECT AVG(scoring_score) as avg_score FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['avg_failed_score'] = int(row['avg_score']) if row['avg_score'] else 0
        
        # Процент без языка
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ? AND (language_code IS NULL OR language_code = '')
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['no_language_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Процент новых ID (юзер ID > 8 млрд = зарегистрирован недавно, примерно)
        # Для более точного анализа нужно сравнивать с p95 из good_users
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ? AND user_id > 8000000000
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['new_id_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Получаем p95 и p99 из good_users для сравнения
        scoring_stats = await self.get_scoring_stats(chat_id, days=days)
        p95 = scoring_stats.get('p95_id')
        p99 = scoring_stats.get('p99_id')
        
        if p95:
            # Процент ботов с ID > p95
            async with self._connection.execute('''
                SELECT COUNT(*) as count FROM failed_users
                WHERE chat_id = ? AND failed_at >= ? AND user_id > ?
            ''', (chat_id, cutoff_time, p95)) as cursor:
                row = await cursor.fetchone()
                stats['id_above_p95_rate'] = (row['count'] / total) if total > 0 else 0
        else:
            stats['id_above_p95_rate'] = 0
        
        if p99:
            # Процент ботов с ID > p99
            async with self._connection.execute('''
                SELECT COUNT(*) as count FROM failed_users
                WHERE chat_id = ? AND failed_at >= ? AND user_id > ?
            ''', (chat_id, cutoff_time, p99)) as cursor:
                row = await cursor.fetchone()
                stats['id_above_p99_rate'] = (row['count'] / total) if total > 0 else 0
        else:
            stats['id_above_p99_rate'] = 0
        
        return stats

    async def clear_good_users(self, chat_id: int) -> int:
        """
        Очистить профиль успешных пользователей для чата.
        Возвращает количество удалённых записей.
        """
        async with self._connection.execute('''
            DELETE FROM good_users WHERE chat_id = ?
        ''', (chat_id,)) as cursor:
            deleted_count = cursor.rowcount
        await self._connection.commit()
        return deleted_count

    async def get_good_users_stats(self, chat_id: int, days: int = 7, min_samples: int = 30) -> Optional[Dict[str, Any]]:
        """
        Получить характеристики успешных пользователей (прошедших верификацию).
        Используется для защиты от false positives при автокорректировке.
        """
        cutoff_time = int(time.time()) - (days * 24 * 60 * 60)
        
        # Общее количество успешных за период
        async with self._connection.execute('''
            SELECT COUNT(*) as total FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            total = row['total'] if row else 0
        
        if total < min_samples:
            return None
        
        stats = {'total_good': total}
        
        # Процент без username
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND (username IS NULL OR username = '')
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['no_username_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Процент рандомных username (пересчитываем на лету)
        from bot.utils.username_analysis import username_randomness
        async with self._connection.execute('''
            SELECT username FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND username IS NOT NULL AND username != ''
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            random_username_count = 0
            for row in rows:
                result = username_randomness(row['username'], threshold=0.70)
                if result.is_randomish:
                    random_username_count += 1
            stats['random_username_rate'] = (random_username_count / total) if total > 0 else 0
        
        # Процент без языка
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND (language_code IS NULL OR language_code = '')
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['no_language_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Процент премиум пользователей
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND is_premium = 1
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['premium_rate'] = (row['count'] / total) if total > 0 else 0
        
        # Топ-5 языков успешных юзеров
        async with self._connection.execute('''
            SELECT language_code, COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND language_code IS NOT NULL AND language_code != ''
            GROUP BY language_code
            ORDER BY count DESC
            LIMIT 5
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            stats['top_langs'] = {row['language_code']: row['count'] / total for row in rows}
        
        # Средний ID успешных (для сравнения с ботами)
        async with self._connection.execute('''
            SELECT AVG(user_id) as avg_id FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['avg_user_id'] = int(row['avg_id']) if row['avg_id'] else 0
        
        # Средний scoring score успешных
        async with self._connection.execute('''
            SELECT AVG(scoring_score) as avg_score FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['avg_score'] = int(row['avg_score']) if row['avg_score'] else 0
        
        return stats

    async def get_protection_effectiveness(self, chat_id: int, days: int = 7) -> Dict[str, Any]:
        """Получить статистику эффективности защиты"""
        cutoff_time = int(time.time()) - (days * 24 * 60 * 60)
        
        stats = {}
        
        # Кол-во прошедших верификацию
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['verified'] = row['count'] if row else 0
        
        # Кол-во провалов капчи
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['failed_captcha'] = row['count'] if row else 0
        
        # Кол-во кикнутых в сессиях атак
        async with self._connection.execute('''
            SELECT SUM(total_kicked) as total FROM attack_sessions
            WHERE chat_id = ? AND start_time >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            stats['kicked_in_attack'] = row['total'] if row and row['total'] else 0
        
        # Примерный подсчёт кикнутых скорингом (good_users + failed_captcha = прошли скоринг)
        # scoring_banned = total_joins - verified - failed_captcha - kicked_in_attack
        # Но у нас нет total_joins, поэтому просто отметим что это неизвестно
        stats['scoring_banned'] = 0  # TODO: можно добавить счётчик если нужно
        
        return stats
    
    async def get_adjustment_history(self, chat_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Получить историю автокорректировок скоринга."""
        async with self._connection.execute(
            '''
            SELECT * FROM scoring_adjustments
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (chat_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()

        history = []
        for row in rows:
            item = dict(row)
            for field in ("old_weights_json", "new_weights_json", "reason_json"):
                raw = item.get(field)
                if raw:
                    try:
                        item[field] = json.loads(raw)
                    except Exception:
                        pass
            history.append(item)
        return history

    async def add_scoring_adjustment(
        self,
        *,
        chat_id: int,
        trigger_samples: int,
        old_threshold: Optional[int],
        new_threshold: Optional[int],
        old_weights: Dict[str, Any],
        new_weights: Dict[str, Any],
        changes: List[str],
        reason: Dict[str, Any],
    ):
        """Записать факт автокорректировки скоринга."""
        await self._connection.execute(
            '''
            INSERT INTO scoring_adjustments (
                chat_id, created_at, trigger_samples,
                old_threshold, new_threshold,
                old_weights_json, new_weights_json,
                changes_text, reason_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                chat_id,
                int(time.time()),
                trigger_samples,
                old_threshold,
                new_threshold,
                json.dumps(old_weights, ensure_ascii=False),
                json.dumps(new_weights, ensure_ascii=False),
                "\n".join(changes),
                json.dumps(reason, ensure_ascii=False),
            )
        )
        await self._connection.commit()

    async def get_daily_digest_events(self, since_ts: int) -> List[Dict[str, Any]]:
        """Получить агрегированные события для дайджеста по всем чатам."""
        query = '''
            SELECT
                c.chat_id,
                c.title,
                c.username,
                (SELECT COUNT(*)
                 FROM attack_sessions s
                 WHERE s.chat_id = c.chat_id AND s.start_time >= ?) AS attacks_started,
                (SELECT COUNT(*)
                 FROM attack_sessions s
                 WHERE s.chat_id = c.chat_id AND s.end_time IS NOT NULL AND s.end_time >= ?) AS attacks_ended,
                (SELECT COUNT(*)
                 FROM attack_kicks ak
                 WHERE ak.chat_id = c.chat_id AND ak.kicked_at >= ?) AS attack_kicks,
                (SELECT COUNT(*)
                 FROM scoring_kicks sk
                 WHERE sk.chat_id = c.chat_id AND sk.kicked_at >= ?) AS scoring_kicks,
                (SELECT COUNT(*)
                 FROM failed_users fu
                 WHERE fu.chat_id = c.chat_id AND fu.failed_at >= ?) AS captcha_failed,
                (SELECT COUNT(*)
                 FROM good_users gu
                 WHERE gu.chat_id = c.chat_id AND gu.verified_at >= ?) AS verified,
                (SELECT COUNT(*)
                 FROM scoring_adjustments sa
                 WHERE sa.chat_id = c.chat_id AND sa.created_at >= ?) AS auto_adjustments
            FROM chats c
            ORDER BY c.title
        '''
        params = (since_ts, since_ts, since_ts, since_ts, since_ts, since_ts, since_ts)
        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        events: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            counters = (
                item.get("attacks_started", 0),
                item.get("attacks_ended", 0),
                item.get("attack_kicks", 0),
                item.get("scoring_kicks", 0),
                item.get("captcha_failed", 0),
                item.get("verified", 0),
                item.get("auto_adjustments", 0),
            )
            if any(v > 0 for v in counters):
                events.append(item)
        return events

    async def get_scoring_stats(self, chat_id: int, days: int = 7) -> Dict[str, Any]:
        """Получить статистику для скоринга за последние N дней"""
        cutoff_time = int(time.time()) - (days * 24 * 60 * 60)
        
        # Подсчёт языков
        async with self._connection.execute('''
            SELECT language_code, COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ? AND language_code IS NOT NULL
            GROUP BY language_code
        ''', (chat_id, cutoff_time)) as cursor:
            lang_rows = await cursor.fetchall()
            lang_counts = {row['language_code']: row['count'] for row in lang_rows}
        
        # Общее количество
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            total = row['count'] if row else 0
        
        # Перцентили ID
        async with self._connection.execute('''
            SELECT user_id FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
            ORDER BY user_id
        ''', (chat_id, cutoff_time)) as cursor:
            user_ids = [row['user_id'] for row in await cursor.fetchall()]
        
        p95_id = None
        p99_id = None
        if user_ids:
            count = len(user_ids)
            p95_idx = int(count * 0.95)
            p99_idx = int(count * 0.99)
            if p95_idx < count:
                p95_id = user_ids[p95_idx]
            if p99_idx < count:
                p99_id = user_ids[p99_idx]
        
        return {
            'lang_counts': lang_counts,
            'total_good_joins': total,
            'p95_id': p95_id,
            'p99_id': p99_id
        }

    async def get_daily_join_stats(self, chat_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Получить дневные счетчики: скоринг-кики, провалы капчи, успешные входы."""
        from datetime import datetime, timedelta, time as time_obj

        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        cutoff_time = int(datetime.combine(start_date, time_obj.min).timestamp())

        async with self._connection.execute('''
            SELECT date(verified_at, 'unixepoch') as day, COUNT(*) as count
            FROM good_users
            WHERE chat_id = ? AND verified_at >= ?
            GROUP BY day
        ''', (chat_id, cutoff_time)) as cursor:
            good_rows = await cursor.fetchall()
            good_map = {row['day']: row['count'] for row in good_rows}

        async with self._connection.execute('''
            SELECT date(failed_at, 'unixepoch') as day, COUNT(*) as count
            FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
            GROUP BY day
        ''', (chat_id, cutoff_time)) as cursor:
            failed_rows = await cursor.fetchall()
            failed_map = {row['day']: row['count'] for row in failed_rows}

        async with self._connection.execute('''
            SELECT date(kicked_at, 'unixepoch') as day, COUNT(*) as count
            FROM scoring_kicks
            WHERE chat_id = ? AND kicked_at >= ?
            GROUP BY day
        ''', (chat_id, cutoff_time)) as cursor:
            scoring_rows = await cursor.fetchall()
            scoring_map = {row['day']: row['count'] for row in scoring_rows}

        async with self._connection.execute('''
            SELECT date(kicked_at, 'unixepoch') as day, COUNT(*) as count
            FROM attack_kicks
            WHERE chat_id = ? AND kicked_at >= ?
            GROUP BY day
        ''', (chat_id, cutoff_time)) as cursor:
            attack_rows = await cursor.fetchall()
            attack_map = {row['day']: row['count'] for row in attack_rows}

        stats = []
        current = start_date
        while current <= end_date:
            day_key = current.isoformat()
            stats.append({
                'date': day_key,
                'scoring_kicked': int(scoring_map.get(day_key, 0)),
                'attack_kicked': int(attack_map.get(day_key, 0)),
                'failed_captcha': int(failed_map.get(day_key, 0)),
                'joined': int(good_map.get(day_key, 0)),
            })
            current += timedelta(days=1)

        return stats


# Глобальный экземпляр
db = Database()
