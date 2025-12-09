import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from bot.config import LOGS_DIR


class ChatLogger:
    """Логгер для записи событий по чатам"""
    
    def __init__(self):
        self._loggers = {}
    
    def _get_chat_folder(self, chat_id: int, username: Optional[str] = None) -> Path:
        """Получить папку для логов чата (username приоритетнее chat_id)"""
        folder_name = username if username else f"chat_{abs(chat_id)}"
        chat_dir = LOGS_DIR / folder_name
        chat_dir.mkdir(exist_ok=True)
        return chat_dir
    
    def _get_logger(self, chat_id: int, username: Optional[str] = None) -> logging.Logger:
        """Получить или создать логгер для чата"""
        logger_key = username if username else str(chat_id)
        
        if logger_key in self._loggers:
            return self._loggers[logger_key]
        
        # Создаём логгер
        logger = logging.getLogger(f'chat_{logger_key}')
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        
        # Путь к файлу логов (по дате)
        chat_dir = self._get_chat_folder(chat_id, username)
        log_file = chat_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        
        # Хендлер для записи в файл
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Формат логов
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        self._loggers[logger_key] = logger
        
        return logger
    
    def log_join(self, chat_id: int, username: Optional[str], user_id: int, 
                 user_username: Optional[str], is_bot: bool, is_premium: bool):
        """Логировать вступление пользователя"""
        logger = self._get_logger(chat_id, username)
        user_type = "BOT" if is_bot else ("PREMIUM" if is_premium else "USER")
        logger.info(
            f"JOIN | {user_type} | ID: {user_id} | "
            f"Username: {user_username or 'None'}"
        )
    
    def log_kick(self, chat_id: int, username: Optional[str], user_id: int, 
                 user_username: Optional[str], reason: str = "protection"):
        """Логировать кик пользователя"""
        logger = self._get_logger(chat_id, username)
        logger.info(
            f"KICK | ID: {user_id} | Username: {user_username or 'None'} | "
            f"Reason: {reason}"
        )
    
    def log_attack_start(self, chat_id: int, username: Optional[str], 
                        threshold: int, detected: int):
        """Логировать начало атаки"""
        logger = self._get_logger(chat_id, username)
        logger.warning(
            f"ATTACK STARTED | Threshold: {threshold} | Detected: {detected} joins"
        )
    
    def log_attack_end(self, chat_id: int, username: Optional[str], 
                      duration_seconds: int, total_joins: int, total_kicked: int):
        """Логировать конец атаки"""
        logger = self._get_logger(chat_id, username)
        duration_min = duration_seconds // 60
        duration_sec = duration_seconds % 60
        logger.warning(
            f"ATTACK ENDED | Duration: {duration_min}m {duration_sec}s | "
            f"Total joins: {total_joins} | Kicked: {total_kicked}"
        )
    
    def log_protection_mode(self, chat_id: int, username: Optional[str], enabled: bool):
        """Логировать изменение режима защиты"""
        logger = self._get_logger(chat_id, username)
        status = "ENABLED" if enabled else "DISABLED"
        logger.info(f"PROTECTION MODE: {status}")
    
    def log_settings_change(self, chat_id: int, username: Optional[str], 
                           setting: str, old_value, new_value):
        """Логировать изменение настроек"""
        logger = self._get_logger(chat_id, username)
        logger.info(
            f"SETTINGS CHANGED | {setting}: {old_value} -> {new_value}"
        )


# Глобальный экземпляр
chat_logger = ChatLogger()
