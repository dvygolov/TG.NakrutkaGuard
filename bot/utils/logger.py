import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from bot.config import LOGS_DIR


class ChatLogger:
    """Логгер для записи событий по чатам"""
    
    def __init__(self):
        self._loggers = {}
        self._chat_names = {}  # Кеш имен чатов {chat_id: username}
    
    def _get_chat_username(self, chat_id: int, username: Optional[str] = None) -> str:
        """Получить username чата (из кеша или переданного значения)"""
        if username:
            self._chat_names[chat_id] = username
            return username
        
        # Проверяем кеш
        if chat_id in self._chat_names:
            return self._chat_names[chat_id]
        
        # Fallback на chat_ID
        return f"chat_{abs(chat_id)}"
    
    def update_chat_name(self, chat_id: int, username: str):
        """Обновить имя чата в кеше (вызывается при получении данных из БД)"""
        if username:
            old_name = self._chat_names.get(chat_id)
            self._chat_names[chat_id] = username
            
            # Если был старый логгер - переключаем на новый
            if old_name and old_name in self._loggers and old_name != username:
                del self._loggers[old_name]
    
    def _get_chat_folder(self, chat_id: int, username: Optional[str] = None) -> Path:
        """Получить папку для логов чата (username приоритетнее chat_id)"""
        folder_name = self._get_chat_username(chat_id, username)
        chat_dir = LOGS_DIR / folder_name
        chat_dir.mkdir(exist_ok=True)
        return chat_dir
    
    def _get_logger(self, chat_id: int, username: Optional[str] = None) -> logging.Logger:
        """Получить или создать логгер для чата"""
        # Получаем username чата (из параметра, кеша или БД)
        chat_name = self._get_chat_username(chat_id, username)
        
        if chat_name in self._loggers:
            return self._loggers[chat_name]
        
        # Создаём логгер с понятным именем
        logger = logging.getLogger(chat_name)
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
            '[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        self._loggers[chat_name] = logger
        
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
    
    def log_captcha_sent(self, chat_id: int, username: Optional[str], user_id: int,
                        user_username: Optional[str], message_id: int, correct_answer: str):
        """Логировать отправку капчи"""
        logger = self._get_logger(chat_id, username)
        logger.info(
            f"CAPTCHA | USER | ID: {user_id} | Username: {user_username or 'None'} | "
            f"Sent captcha {message_id}, correct answer: {correct_answer}"
        )
    
    def log_captcha_answer(self, chat_id: int, username: Optional[str], user_id: int,
                          user_username: Optional[str], answer: str, passed: bool):
        """Логировать ответ на капчу"""
        logger = self._get_logger(chat_id, username)
        result = "passed" if passed else "failed"
        logger.info(
            f"CAPTCHA | USER | ID: {user_id} | Username: {user_username or 'None'} | "
            f"Answered {answer} and {result}"
        )
    
    def log_settings_change(self, chat_id: int, username: Optional[str], 
                           setting: str, old_value, new_value):
        """Логировать изменение настроек"""
        logger = self._get_logger(chat_id, username)
        logger.info(
            f"SETTINGS CHANGED | {setting}: {old_value} -> {new_value}"
        )


# Глобальный экземпляр
chat_logger = ChatLogger()
