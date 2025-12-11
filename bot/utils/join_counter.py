"""
In-memory счётчик вступлений для быстрой детекции атак.
Хранит timestamp вступлений в памяти, автоматически очищает старые.
"""
from collections import deque, defaultdict
from time import time
from typing import Dict, Deque


class JoinCounter:
    """
    Высокопроизводительный счётчик вступлений в память.
    Использует deque для автоматической очистки старых событий.
    """
    
    def __init__(self):
        # Храним deque с timestamp для каждого чата
        self._joins: Dict[int, Deque[float]] = defaultdict(deque)
        # Храним (timestamp, user_id, is_premium) для получения списка юзеров в окне
        self._join_users: Dict[int, Deque[tuple]] = defaultdict(deque)
    
    def add_join(self, chat_id: int, user_id: int = None, is_premium: bool = False):
        """
        Добавить событие вступления.
        
        Args:
            chat_id: ID чата
            user_id: ID пользователя (опционально, для get_users_in_window)
            is_premium: Telegram Premium статус
        """
        now = time()
        self._joins[chat_id].append(now)
        
        if user_id is not None:
            self._join_users[chat_id].append((now, user_id, is_premium))
    
    def count_in_window(self, chat_id: int, window_seconds: int) -> int:
        """
        Подсчитать количество вступлений за последние window_seconds секунд.
        Автоматически очищает устаревшие записи.
        
        Args:
            chat_id: ID чата
            window_seconds: Размер окна в секундах
        
        Returns:
            Количество вступлений в окне
        """
        now = time()
        cutoff = now - window_seconds
        
        # Очищаем старые записи
        queue = self._joins[chat_id]
        while queue and queue[0] < cutoff:
            queue.popleft()
        
        return len(queue)
    
    def get_users_in_window(self, chat_id: int, window_seconds: int) -> list[dict]:
        """
        Получить список пользователей вступивших за окно.
        
        Args:
            chat_id: ID чата
            window_seconds: Размер окна в секундах
        
        Returns:
            Список словарей {'user_id': int, 'is_premium': bool}
        """
        now = time()
        cutoff = now - window_seconds
        
        # Очищаем старые записи
        queue = self._join_users[chat_id]
        while queue and queue[0][0] < cutoff:
            queue.popleft()
        
        return [{'user_id': user_id, 'is_premium': is_premium} for _, user_id, is_premium in queue]
    
    def clear_chat(self, chat_id: int):
        """Очистить данные чата (например, при удалении из защиты)"""
        if chat_id in self._joins:
            del self._joins[chat_id]
        if chat_id in self._join_users:
            del self._join_users[chat_id]
    
    def get_memory_usage(self) -> dict:
        """Получить информацию об использовании памяти (для мониторинга)"""
        return {
            'total_chats': len(self._joins),
            'total_events': sum(len(q) for q in self._joins.values()),
            'chats': {
                chat_id: len(queue) 
                for chat_id, queue in self._joins.items()
            }
        }


# Глобальный instance
join_counter = JoinCounter()
