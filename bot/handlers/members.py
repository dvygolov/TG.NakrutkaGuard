from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, MEMBER, KICKED, LEFT
from bot.utils.detector import detector
from bot.utils.logger import chat_logger
from bot.database import db
from bot.config import ADMIN_IDS
from bot.handlers.captcha import send_captcha
import asyncio

router = Router()


async def kick_user_safe(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Безопасно кикнуть пользователя из чата
    Returns: True если успешно, False если ошибка
    """
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)  # Kick вместо ban
        return True
    except Exception as e:
        # Логируем ошибку но не падаем
        print(f"Error kicking user {user_id} from {chat_id}: {e}")
        return False


async def notify_admins(bot: Bot, chat_id: int, message: str):
    """Отправить уведомление всем админам"""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message, parse_mode="HTML")
        except Exception as e:
            print(f"Error notifying admin {admin_id}: {e}")


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def on_new_member(event: ChatMemberUpdated, bot: Bot):
    """
    Обработчик новых участников в чате/канале
    Срабатывает когда пользователь вступает в группу или подписывается на канал
    """
    chat = event.chat
    user = event.new_chat_member.user
    
    # Игнорируем самого бота
    if user.id == bot.id:
        return
    
    # Обрабатываем вступление через детектор
    result = await detector.check_and_handle_join(chat, user)
    
    # Если чат не защищён - ничего не делаем
    if result['reason'] == 'chat_not_protected':
        return
    
    # === КАПЧА (только для групп в обычном режиме) ===
    chat_data = await db.get_chat(chat.id)
    is_group = chat.type in ["group", "supergroup"]
    captcha_enabled = chat_data and chat_data.get('captcha_enabled', False)
    protection_active = chat_data and chat_data.get('protection_active', False)
    
    # Показываем капчу если:
    # 1. Это группа (не канал)
    # 2. Капча включена
    # 3. НЕ режим атаки
    # 4. Юзер не бот (ботов сразу кикаем)
    if is_group and captcha_enabled and not protection_active and not user.is_bot:
        # Отправляем капчу
        await send_captcha(
            bot,
            chat.id,
            user.id,
            username=user.username,
            full_name=user.full_name,
        )
        # Больше ничего не делаем - ждём прохождения капчи
        return
    
    # Если началась атака
    if result['attack_started']:
        # Уведомляем админов
        recent_joins = await db.count_joins_in_window(chat.id, (await db.get_chat(chat.id))['time_window'])
        message = await detector.get_attack_start_message(chat.id, recent_joins)
        await notify_admins(bot, chat.id, message)
        
        # Кикаем всех из окна
        if 'users_to_kick' in result:
            kick_tasks = []
            for user_id in result['users_to_kick']:
                kick_tasks.append(kick_user_safe(bot, chat.id, user_id))
                chat_logger.log_kick(chat.id, chat.username, user_id, None, "attack_window")
            
            # Выполняем кики параллельно (батчами по 50)
            kicked_count = 0
            for i in range(0, len(kick_tasks), 50):
                batch = kick_tasks[i:i+50]
                results = await asyncio.gather(*batch, return_exceptions=True)
                # Считаем успешные кики
                kicked_count += sum(1 for r in results if r is True)
                # Небольшая задержка между батчами чтобы не словить rate limit
                if i + 50 < len(kick_tasks):
                    await asyncio.sleep(1)
            
            # Обновляем счётчик кикнутых в БД
            for _ in range(kicked_count):
                await db.increment_kicked(chat.id)
    
    # Если атака закончилась
    if result['attack_ended']:
        # Уведомляем админов
        message = result.get('attack_end_message') or await detector.get_attack_stats_message(chat.id)
        if message:
            await notify_admins(bot, chat.id, message)
    
    # Если нужно кикнуть текущего пользователя
    if result['should_kick']:
        success = await kick_user_safe(bot, chat.id, user.id)
        if success:
            chat_logger.log_kick(
                chat.id, chat.username, user.id, 
                user.username, result['reason']
            )


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=[LEFT, KICKED]))
async def on_member_left(event: ChatMemberUpdated):
    """
    Обработчик выхода участников
    Можно использовать для дополнительной статистики если нужно
    """
    # Пока ничего не делаем, но можно логировать
    pass
