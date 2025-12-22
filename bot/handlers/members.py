from aiogram import Router, F, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, MEMBER, KICKED, LEFT
from bot.utils.detector import detector
from bot.utils.logger import chat_logger
from bot.utils.scoring import score_user, ScoringConfig, ScoringStats
from bot.utils.join_counter import join_counter
from bot.database import db
from bot.config import ADMIN_IDS
from bot.handlers.captcha import send_captcha
import asyncio
import logging

logger = logging.getLogger(__name__)

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


async def cleanup_pending_captcha(bot: Bot, chat_id: int, user_id: int):
    """Удалить сообщение капчи и запись pending, если есть."""
    pending = await db.get_pending_captcha(chat_id, user_id)
    if not pending:
        return
    try:
        await bot.delete_message(chat_id, pending['message_id'])
    except Exception:
        pass
    try:
        await db.remove_pending_captcha(chat_id, user_id)
    except Exception:
        pass


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
    
    # === СКОРИНГ И КАПЧА ===
    chat_data = await db.get_chat(chat.id)
    is_group = chat.type in ["group", "supergroup"]
    captcha_enabled = chat_data and chat_data.get('captcha_enabled', False)
    protection_active = chat_data and chat_data.get('protection_active', False)
    scoring_enabled = chat_data and chat_data.get('scoring_enabled', False)

    chat_log_name = chat.username if chat.username else f"chat_{abs(chat.id)}"
    chat_log = logging.getLogger(chat_log_name)

    # Если началась атака
    if result['attack_started']:
        # Уведомляем админов
        time_window = (await db.get_chat(chat.id))['time_window']
        recent_joins = join_counter.count_in_window(chat.id, time_window)
        message = await detector.get_attack_start_message(chat.id, recent_joins)
        await notify_admins(bot, chat.id, message)

        # Кикаем всех из окна
        if 'users_to_kick' in result:
            kick_tasks = []
            for user_id in result['users_to_kick']:
                await cleanup_pending_captcha(bot, chat.id, user_id)
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
    # Важно: если атака только что завершилась на этом join'е, не кикаем текущего
    if result['should_kick'] and not result['attack_ended']:
        await cleanup_pending_captcha(bot, chat.id, user.id)
        success = await kick_user_safe(bot, chat.id, user.id)
        if success:
            chat_logger.log_kick(
                chat.id, chat.username, user.id,
                user.username, result['reason']
            )
        return
    
    # Скоринг работает только в обычном режиме (не в атаке)
    if scoring_enabled and not protection_active and not user.is_bot:
        try:
            # Получаем конфиг скоринга
            scoring_config_data = await db.get_scoring_config(chat.id)
            if scoring_config_data:
                # Получаем количество аватаров
                photo_count = 0
                try:
                    photos = await bot.get_user_profile_photos(user.id, limit=100)
                    photo_count = photos.total_count
                except Exception as e:
                    chat_log.warning(f"Не удалось получить фото профиля для {user.id}: {e}")
                
                # Получаем статистику
                stats_data = await db.get_scoring_stats(chat.id, days=7)
                
                # Создаём конфиг и статистику
                cfg = ScoringConfig(
                    lang_distribution=scoring_config_data['lang_distribution'],
                    max_lang_risk=scoring_config_data['max_lang_risk'],
                    no_lang_risk=scoring_config_data['no_lang_risk'],
                    max_id_risk=scoring_config_data['max_id_risk'],
                    premium_bonus=scoring_config_data['premium_bonus'],
                    no_avatar_risk=scoring_config_data['no_avatar_risk'],
                    one_avatar_risk=scoring_config_data['one_avatar_risk'],
                    no_username_risk=scoring_config_data['no_username_risk'],
                    weird_name_risk=scoring_config_data['weird_name_risk'],
                    exotic_script_risk=scoring_config_data.get('exotic_script_risk', scoring_config_data.get('arabic_cjk_risk', 25)),
                    special_chars_risk=scoring_config_data.get('special_chars_risk', 15),
                    repeating_chars_risk=scoring_config_data.get('repeating_chars_risk', 5),
                    random_username_risk=scoring_config_data['random_username_risk']
                )
                stats = ScoringStats(
                    lang_counts=stats_data['lang_counts'],
                    total_good_joins=stats_data['total_good_joins'],
                    p95_id=stats_data['p95_id'],
                    p99_id=stats_data['p99_id']
                )
                
                # Вычисляем скор
                risk_score = score_user(
                    user, photo_count=photo_count, cfg=cfg, stats=stats,
                    chat_id=chat.id, chat_username=chat.username
                )
                
                # Если скор превышает порог - кикаем
                if risk_score > scoring_config_data['threshold']:
                    success = await kick_user_safe(bot, chat.id, user.id)
                    if success:
                        chat_logger.log_kick(
                            chat.id, chat.username, user.id,
                            user.username, f"scoring_{risk_score}"
                        )
                    return
                else:
                    # Скор прошёл
                    # Добавляем в good_users только если капча НЕ включена
                    # (если капча включена - добавим после её прохождения)
                    if not captcha_enabled:
                        await db.add_good_user(
                            chat.id, user.id,
                            user.first_name, user.last_name, user.username,
                            user.language_code, user.is_premium or False,
                            photo_count,
                            scoring_score=risk_score
                        )
                    chat_log.info(
                        f"Юзер {user.id} прошёл скоринг: score={risk_score} <= threshold={scoring_config_data['threshold']}"
                    )
        except Exception as e:
            chat_log.error(f"Ошибка скоринга для {user.id}: {e}", exc_info=True)
    
    # Показываем капчу если:
    # 1. Это группа (не канал)
    # 2. Капча включена
    # 3. НЕ режим атаки
    # 4. Юзер не бот (ботов сразу кикаем)
    # 5. Юзер прошёл скоринг (или скоринг выключен)
    if is_group and captcha_enabled and not protection_active and not user.is_bot:
        # Отправляем капчу, передаем уже вычисленный risk_score если он есть
        await send_captcha(
            bot,
            chat.id,
            user.id,
            username=user.username,
            full_name=user.full_name,
            scoring_score=risk_score if 'risk_score' in locals() else 0,
        )
        # Больше ничего не делаем - ждём прохождения капчи
        return


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=[LEFT, KICKED]))
async def on_member_left(event: ChatMemberUpdated):
    """
    Обработчик выхода участников
    Можно использовать для дополнительной статистики если нужно
    """
    # Пока ничего не делаем, но можно логировать
    pass
