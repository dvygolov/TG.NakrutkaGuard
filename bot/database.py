import aiosqlite
import time
import json
import logging
from typing import Optional, List, Dict, Any
from bot.config import DB_PATH

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
                protect_premium BOOLEAN DEFAULT 1,
                allow_channel_posts BOOLEAN DEFAULT 1,
                captcha_enabled BOOLEAN DEFAULT 0,
                welcome_message TEXT,
                rules_message TEXT,
                added_at INTEGER NOT NULL,
                scoring_enabled BOOLEAN DEFAULT 0,
                scoring_threshold INTEGER DEFAULT 50,
                scoring_lang_distribution TEXT DEFAULT '{"ru": 0.8, "en": 0.2}',
                scoring_weights TEXT DEFAULT '{"max_lang_risk": 25, "no_lang_risk": 15, "max_id_risk": 20, "premium_bonus": -20, "no_avatar_risk": 15, "one_avatar_risk": 5, "no_username_risk": 5, "weird_name_risk": 10, "arabic_cjk_risk": 25}',
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
        ''')
        await self._connection.commit()

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

    async def remove_chat(self, chat_id: int):
        """Удалить чат из защиты"""
        await self._connection.execute('DELETE FROM chats WHERE chat_id = ?', (chat_id,))
        await self._connection.commit()

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
                logger.info(f"Chat {chat_id}: использует скоринг из связанного чата {row['linked_chat_id']}")
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
                'no_username_risk': weights.get('no_username_risk', 5),
                'weird_name_risk': weights.get('weird_name_risk', 10),
                'arabic_cjk_risk': weights.get('arabic_cjk_risk', 25),
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
        
        # Вычисляем характеристики имени на лету
        import re
        LATIN_CYRILLIC_RE = re.compile(r"[A-Za-zА-Яа-я]")
        ARABIC_CJK_RE = re.compile(r"[\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]")
        
        async with self._connection.execute('''
            SELECT first_name, last_name FROM failed_users
            WHERE chat_id = ? AND failed_at >= ?
        ''', (chat_id, cutoff_time)) as cursor:
            rows = await cursor.fetchall()
            arabic_cjk_count = 0
            weird_name_count = 0
            for row in rows:
                full_name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
                if ARABIC_CJK_RE.search(full_name):
                    arabic_cjk_count += 1
                if not LATIN_CYRILLIC_RE.search(full_name):
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
        """
        Получить историю автокорректировок скоринга.
        Пока возвращаем пустой список, т.к. мы не логируем историю изменений.
        В будущем можно добавить таблицу scoring_adjustments для логирования.
        """
        # TODO: создать таблицу scoring_adjustments для логирования изменений
        return []

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


# Глобальный экземпляр
db = Database()
