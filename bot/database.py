import aiosqlite
import time
from typing import Optional, List, Dict, Any
from bot.config import DB_PATH


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
                protect_premium BOOLEAN DEFAULT 1,
                captcha_enabled BOOLEAN DEFAULT 0,
                added_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS join_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                is_bot BOOLEAN NOT NULL,
                is_premium BOOLEAN DEFAULT 0,
                join_time INTEGER NOT NULL,
                action_taken TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_join_time ON join_events(chat_id, join_time);

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
        ''')
        await self._connection.commit()

    # === CHATS ===

    async def add_chat(self, chat_id: int, title: str, username: Optional[str] = None,
                      threshold: int = 10, time_window: int = 60, protect_premium: bool = True):
        """Добавить чат под защиту"""
        await self._connection.execute('''
            INSERT OR REPLACE INTO chats (chat_id, title, username, threshold, time_window, 
                                         protection_active, protect_premium, added_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
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

    async def set_protection_active(self, chat_id: int, active: bool):
        """Включить/выключить режим защиты"""
        await self._connection.execute(
            'UPDATE chats SET protection_active = ? WHERE chat_id = ?',
            (active, chat_id)
        )
        await self._connection.commit()

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

    async def remove_chat(self, chat_id: int):
        """Удалить чат из защиты"""
        await self._connection.execute('DELETE FROM chats WHERE chat_id = ?', (chat_id,))
        await self._connection.commit()

    # === JOIN EVENTS ===

    async def log_join(self, chat_id: int, user_id: int, username: Optional[str],
                      is_bot: bool, is_premium: bool, action_taken: Optional[str] = None):
        """Записать событие вступления"""
        await self._connection.execute('''
            INSERT INTO join_events (chat_id, user_id, username, is_bot, is_premium, join_time, action_taken)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, username, is_bot, is_premium, int(time.time()), action_taken))
        await self._connection.commit()

    async def count_joins_in_window(self, chat_id: int, time_window: int) -> int:
        """Подсчитать кол-во вступлений за последние time_window секунд"""
        cutoff_time = int(time.time()) - time_window
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM join_events 
            WHERE chat_id = ? AND join_time >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            row = await cursor.fetchone()
            return row['count'] if row else 0

    async def get_users_in_window(self, chat_id: int, time_window: int) -> List[Dict[str, Any]]:
        """Получить всех пользователей, вступивших в окне"""
        cutoff_time = int(time.time()) - time_window
        async with self._connection.execute('''
            SELECT user_id, username, is_bot, is_premium FROM join_events 
            WHERE chat_id = ? AND join_time >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_action_taken(self, chat_id: int, user_id: int, action: str):
        """Обновить действие для последнего join event пользователя"""
        await self._connection.execute('''
            UPDATE join_events SET action_taken = ?
            WHERE chat_id = ? AND user_id = ? 
            AND id = (SELECT id FROM join_events WHERE chat_id = ? AND user_id = ? 
                     ORDER BY join_time DESC LIMIT 1)
        ''', (action, chat_id, user_id, chat_id, user_id))
        await self._connection.commit()

    # === ATTACK SESSIONS ===

    async def start_attack_session(self, chat_id: int) -> int:
        """Начать новую сессию атаки"""
        cursor = await self._connection.execute('''
            INSERT INTO attack_sessions (chat_id, start_time)
            VALUES (?, ?)
        ''', (chat_id, int(time.time())))
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

    async def count_joins_during_attack(self, chat_id: int, start_time: int, end_time: int) -> int:
        """Подсчитать кол-во вступлений за период атаки"""
        async with self._connection.execute('''
            SELECT COUNT(*) as count FROM join_events 
            WHERE chat_id = ? AND join_time >= ? AND join_time <= ?
        ''', (chat_id, start_time, end_time)) as cursor:
            row = await cursor.fetchone()
            return row['count'] if row else 0

    # === CAPTCHA ===

    async def add_pending_captcha(self, chat_id: int, user_id: int, message_id: int, 
                                  correct_answer: str, expires_at: int):
        """Добавить юзера в ожидание прохождения капчи"""
        await self._connection.execute('''
            INSERT OR REPLACE INTO pending_captcha 
            (chat_id, user_id, message_id, correct_answer, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, message_id, correct_answer, int(time.time()), expires_at))
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


# Глобальный экземпляр
db = Database()
