from typing import Optional, Dict, Any
from aiogram.types import Chat, User
from bot.database import db
from bot.utils.logger import chat_logger
from bot.utils.join_counter import join_counter
import time


class AttackDetector:
    """Детектор атак и управление режимом защиты"""
    
    async def check_and_handle_join(self, chat: Chat, user: User) -> Dict[str, Any]:
        """
        Обработать вступление пользователя и определить действие
        
        Returns:
            {
                'should_kick': bool,
                'reason': str,
                'attack_started': bool,
                'attack_ended': bool
            }
        """
        chat_id = chat.id
        chat_username = chat.username
        
        # Проверяем есть ли чат в БД
        chat_data = await db.get_chat(chat_id)
        if not chat_data:
            # Чат не добавлен в систему защиты
            return {
                'should_kick': False,
                'reason': 'chat_not_protected',
                'attack_started': False,
                'attack_ended': False
            }
        
        # Добавляем вступление в in-memory счётчик
        join_counter.add_join(chat_id, user.id, user.is_premium or False)
        
        # Логируем вступление в файл
        chat_logger.log_join(
            chat_id, chat_username, user.id, 
            user.username, user.is_bot, user.is_premium or False
        )
        
        # Получаем настройки
        threshold = chat_data['threshold']
        time_window = chat_data['time_window']
        protect_premium = chat_data['protect_premium']
        protection_active = chat_data['protection_active']
        
        # Считаем вступления в окне - МГНОВЕННО из памяти!
        recent_joins = join_counter.count_in_window(chat_id, time_window)
        
        result = {
            'should_kick': False,
            'reason': '',
            'attack_started': False,
            'attack_ended': False,
            'attack_end_message': None
        }
        
        # Режим защиты АКТИВЕН
        if protection_active:
            # Проверяем premium защиту
            if user.is_premium and protect_premium:
                result['should_kick'] = False
                result['reason'] = 'premium_protected'
            else:
                result['should_kick'] = True
                result['reason'] = 'protection_mode'
                await db.increment_kicked(chat_id)
            
            # Проверяем не пора ли выключить защиту
            if recent_joins < threshold:
                changed = await db.set_protection_active(chat_id, False)
                if changed:
                    # Атака закончилась!
                    await db.end_attack_session(chat_id)
                    
                    result['attack_ended'] = True
                    result['attack_end_message'] = await self.get_attack_stats_message(chat_id)
                    
                    # Логируем конец атаки
                    stats = await db.get_last_attack_stats(chat_id)
                    if stats:
                        duration = stats['end_time'] - stats['start_time']
                        # Приблизительное кол-во joins (т.к. точная история не хранится)
                        total_joins = stats['total_kicked']
                        chat_logger.log_attack_end(
                            chat_id, chat_username, duration, total_joins, stats['total_kicked']
                        )
                        chat_logger.log_protection_mode(chat_id, chat_username, False)
        
        # Обычный режим
        else:
            # Проверяем превышение порога
            if recent_joins >= threshold:
                changed = await db.set_protection_active(chat_id, True)
                
                if changed:
                    # АТАКА! Включаем защиту
                    attack_start_time = int(time.time())
                    await db.start_attack_session(chat_id, attack_start_time)
                    
                    result['attack_started'] = True
                    
                    # Логируем начало атаки
                    chat_logger.log_attack_start(chat_id, chat_username, threshold, recent_joins)
                    chat_logger.log_protection_mode(chat_id, chat_username, True)
                    
                    # Кикаем ВСЕХ из окна (кроме premium и текущего - его отдельно)
                    users_in_window = join_counter.get_users_in_window(chat_id, time_window)
                    result['users_to_kick'] = []
                    
                    for user_data in users_in_window:
                        # Пропускаем текущего юзера (его кикнем отдельно)
                        if user_data['user_id'] == user.id:
                            continue
                        # Проверяем premium защиту
                        if user_data['is_premium'] and protect_premium:
                            continue
                        result['users_to_kick'].append(user_data['user_id'])
                
                # Кикаем текущего тоже
                if not (user.is_premium and protect_premium):
                    result['should_kick'] = True
                    result['reason'] = 'attack_detected'
                    await db.increment_kicked(chat_id)
        
        return result
    
    async def get_attack_stats_message(self, chat_id: int) -> Optional[str]:
        """Получить сообщение со статистикой последней атаки"""
        stats = await db.get_last_attack_stats(chat_id)
        if not stats:
            return None
        
        chat_data = await db.get_chat(chat_id)
        chat_title = chat_data['title'] if chat_data else str(chat_id)
        chat_username = chat_data.get('username') if chat_data else None
        chat_ref = f"@{chat_username}" if chat_username else chat_title
        
        duration = stats['end_time'] - stats['start_time']
        duration_min = duration // 60
        duration_sec = duration % 60
        
        message = (
            f"✅ <b>АТАКА ЗАВЕРШЕНА</b>\n"
            f"📍 Чат: {chat_ref}\n\n"
            f"⏱ Длительность: {duration_min}м {duration_sec}с\n"
            f"🚫 Кикнуто: {stats['total_kicked']}\n"
        )
        
        return message
    
    async def get_attack_start_message(self, chat_id: int, detected_count: int) -> str:
        """Получить сообщение о начале атаки"""
        chat_data = await db.get_chat(chat_id)
        chat_title = chat_data['title'] if chat_data else str(chat_id)
        chat_username = chat_data.get('username') if chat_data else None
        chat_ref = f"@{chat_username}" if chat_username else chat_title
        
        message = (
            f"⚠️ <b>АТАКА ОБНАРУЖЕНА</b>\n"
            f"📍 Чат: {chat_ref}\n\n"
            f"📊 Порог: {chat_data['threshold']} вступлений/{chat_data['time_window']}с\n"
            f"🔴 Обнаружено: {detected_count} вступлений\n"
            f"🛡 Режим защиты: <b>АКТИВЕН</b>"
        )
        
        return message


# Глобальный экземпляр
detector = AttackDetector()
