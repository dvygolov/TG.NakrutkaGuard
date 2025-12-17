import asyncio
import logging
from typing import Optional, Union
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.filters import ChatMemberUpdatedFilter, MEMBER, Command
from bot.database import db
from bot.utils.captcha import captcha_gen
from bot.utils.logger import chat_logger
from bot.utils.message_utils import delete_message_later
from bot.utils.scoring import score_user, ScoringConfig, ScoringStats, LATIN_CYRILLIC_REGEX, ARABIC_CJK_REGEX
from bot.utils.scoring_auto_adjust import auto_adjust_scoring, should_trigger_auto_adjust
import time
import html

logger = logging.getLogger(__name__)

router = Router()


async def _log_failed_captcha_user(bot: Bot, chat_id: int, user_id: int):
    """
    Логировать пользователя, не прошедшего капчу.
    Сохраняет полные данные для экспериментов с корректировкой скоринга.
    """
    try:
        # Получаем информацию о пользователе
        user = await bot.get_chat_member(chat_id, user_id)
        user_obj = user.user
        
        # Получаем данные чата для логирования
        chat_data = await db.get_chat(chat_id)
        chat_username = chat_data.get('username') if chat_data else None
        
        # Получаем количество аватарок
        photo_count = 0
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=100)
            photo_count = photos.total_count
        except Exception:
            pass
        
        # Вычисляем скор, который был у этого пользователя
        scoring_score = 0
        scoring_config = await db.get_scoring_config(chat_id)
        if scoring_config:
            try:
                stats_data = await db.get_scoring_stats(chat_id, days=7)
                cfg = ScoringConfig(
                    lang_distribution=scoring_config['lang_distribution'],
                    max_lang_risk=scoring_config['max_lang_risk'],
                    max_id_risk=scoring_config['max_id_risk'],
                    premium_bonus=scoring_config['premium_bonus'],
                    no_avatar_risk=scoring_config['no_avatar_risk'],
                    one_avatar_risk=scoring_config['one_avatar_risk'],
                    no_username_risk=scoring_config['no_username_risk'],
                    weird_name_risk=scoring_config['weird_name_risk'],
                    arabic_cjk_risk=scoring_config['arabic_cjk_risk']
                )
                stats = ScoringStats(
                    lang_counts=stats_data['lang_counts'],
                    total_good_joins=stats_data['total_good_joins'],
                    p95_id=stats_data['p95_id'],
                    p99_id=stats_data['p99_id']
                )
                scoring_score = score_user(
                    user_obj, photo_count=photo_count, cfg=cfg, stats=stats,
                    chat_id=chat_id, chat_username=chat_username
                )
            except Exception as e:
                logger.warning(f"Не удалось вычислить скор для failed user {user_id}: {e}")
        
        # Сохраняем в БД (идентичная структура с good_users для экспериментов)
        await db.add_failed_user(
            chat_id=chat_id,
            user_id=user_id,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name,
            username=user_obj.username,
            language_code=user_obj.language_code,
            is_premium=user_obj.is_premium or False,
            photo_count=photo_count,
            scoring_score=scoring_score
        )
        
        logger.info(f"Logged failed user {user_id} in chat {chat_id}: score={scoring_score}, photos={photo_count}")
        
    except Exception as e:
        logger.error(f"Ошибка логирования failed user {user_id}: {e}")


def _format_welcome_text(template: str, user: Union[Message, CallbackQuery]) -> str:
    """Подставляет макросы в приветственном сообщении."""
    user_obj = user.from_user if hasattr(user, "from_user") else None
    if not user_obj:
        return template.replace("{username}", "")
    
    if user_obj.username:
        mention = f"@{user_obj.username}"
    else:
        full_name = user_obj.full_name or "пользователь"
        mention = f'<a href="tg://user?id={user_obj.id}">{html.escape(full_name)}</a>'
    
    return template.replace("{username}", mention)


async def send_captcha(
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
):
    """
    Отправить капчу пользователю
    
    Returns:
        True если капча отправлена, False если ошибка
    """
    try:
        print(f"[CAPTCHA] Отправляю капчу для user={user_id} (@{username}) в chat={chat_id}")
        
        # Получаем данные чата для логирования
        chat_data = await db.get_chat(chat_id)
        chat_username = chat_data.get('username') if chat_data else None
        
        # Генерируем капчу
        question, correct_answer, keyboard = captcha_gen.generate()
        print(f"[CAPTCHA] Сгенерирована капча, правильный ответ: {correct_answer}")
        
        # Отправляем сообщение
        if username:
            user_mention = f"@{username}"
        else:
            fallback_name = full_name or f"ID: {user_id}"
            user_mention = f'<a href="tg://user?id={user_id}">{html.escape(fallback_name)}</a>'
        text = (
            f"{user_mention}, чтобы вступить, пройдите проверку.\n\n"
            f"{question}"
        )
        
        message = await bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        print(f"[CAPTCHA] Сообщение отправлено, message_id={message.message_id}")
        
        # Сохраняем в БД (60 секунд на ответ)
        expires_at = int(time.time()) + 60
        await db.add_pending_captcha(
            chat_id, user_id, message.message_id, 
            correct_answer, expires_at
        )
        print(f"[CAPTCHA] Капча сохранена в БД, expires_at={expires_at}")
        
        # Запускаем таймер для автобана
        task = asyncio.create_task(_captcha_timeout_handler(bot, chat_id, user_id, message.message_id))
        print(f"[CAPTCHA] Таймер создан: {task}")
        
        chat_logger.log_join(chat_id, chat_username, user_id, username, False, False)
        
        return True
        
    except Exception as e:
        print(f"[CAPTCHA] ОШИБКА отправки капчи для user={user_id} в chat={chat_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def _captcha_timeout_handler(bot: Bot, chat_id: int, user_id: int, message_id: int):
    """Обработчик таймаута капчи (60 секунд)"""
    try:
        print(f"[CAPTCHA] Таймер запущен для user={user_id} в chat={chat_id}")
        await asyncio.sleep(60)
        
        print(f"[CAPTCHA] Таймер истёк для user={user_id}, проверяю статус...")
        
        # Проверяем не прошёл ли юзер капчу за это время
        pending = await db.get_pending_captcha(chat_id, user_id)
        if not pending:
            # Уже прошёл или был удалён
            print(f"[CAPTCHA] User={user_id} уже прошёл капчу или был удалён")
            return
        
        print(f"[CAPTCHA] User={user_id} НЕ прошёл капчу, кикаю...")
        
        # Логируем характеристики неудачника для ML
        await _log_failed_captcha_user(bot, chat_id, user_id)
        
        # Получаем username для лога
        username = None
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            username = member.user.username
        except Exception:
            pass
        
        # Не прошёл - баним
        kick_success = False
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)  # kick
            kick_success = True
            print(f"[CAPTCHA] User={user_id} кикнут")
            chat_logger.log_kick(chat_id, None, user_id, username, "captcha_timeout")
        except Exception as e:
            print(f"[CAPTCHA] Ошибка кика user={user_id}: {e}")
        
        # Удаляем сообщение с капчей (ВСЕГДА, даже если кик не удался)
        try:
            await bot.delete_message(chat_id, message_id)
            print(f"[CAPTCHA] Сообщение {message_id} удалено")
        except Exception as e:
            print(f"[CAPTCHA] Не удалось удалить сообщение {message_id}: {e}")
        
        # Удаляем из pending (ВСЕГДА)
        try:
            await db.remove_pending_captcha(chat_id, user_id)
            print(f"[CAPTCHA] User={user_id} удалён из pending")
        except Exception as e:
            print(f"[CAPTCHA] Ошибка удаления из pending: {e}")
        
        # Проверяем нужна ли автокорректировка скоринга
        if kick_success:
            try:
                if await should_trigger_auto_adjust(chat_id):
                    result = await auto_adjust_scoring(chat_id)
                    if result:
                        logger.info(f"Chat {chat_id}: автокорректировка выполнена: {result['changes']}")
            except Exception as e:
                logger.error(f"Ошибка автокорректировки для chat {chat_id}: {e}")
            
    except asyncio.CancelledError:
        print(f"[CAPTCHA] Таймер отменён для user={user_id}")
        raise
    except Exception as e:
        print(f"[CAPTCHA] КРИТИЧЕСКАЯ ошибка в таймере для user={user_id}: {e}")
        import traceback
        traceback.print_exc()


@router.callback_query(F.data.startswith("captcha:"))
async def handle_captcha_answer(callback: CallbackQuery, bot: Bot):
    """Обработчик ответа на капчу"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    print(f"[CAPTCHA] Получен ответ от user={user_id} в chat={chat_id}")
    
    # Проверяем есть ли pending капча для этого юзера
    pending = await db.get_pending_captcha(chat_id, user_id)
    
    if not pending:
        # Капчи нет (или уже прошёл, или истекла)
        print(f"[CAPTCHA] Капча не найдена для user={user_id}")
        await callback.answer("⏱ Время истекло или вы уже прошли проверку", show_alert=True)
        return
    
    # Проверяем что это именно тот юзер который должен отвечать
    # (другие юзеры не должны мочь ответить за него)
    if pending['user_id'] != user_id:
        print(f"[CAPTCHA] User={user_id} пытается ответить за другого юзера")
        await callback.answer("❌ Эта проверка не для вас", show_alert=True)
        return
    
    # Парсим ответ
    answer = callback.data.split(":")[1]
    correct_answer = pending['correct_answer']
    
    print(f"[CAPTCHA] Ответ user={user_id}: {answer}, правильный: {correct_answer}")
    
    if answer == correct_answer:
        # ПРАВИЛЬНЫЙ ОТВЕТ
        print(f"[CAPTCHA] User={user_id} ПРОШЁЛ капчу!")
        await callback.answer("✅ Верно! Добро пожаловать в чат", show_alert=True)
        
        # Удаляем сообщение с капчей
        try:
            await bot.delete_message(chat_id, pending['message_id'])
            print(f"[CAPTCHA] Сообщение удалено")
        except Exception as e:
            print(f"[CAPTCHA] Не удалось удалить сообщение: {e}")
        
        # Удаляем из pending
        await db.remove_pending_captcha(chat_id, user_id)
        print(f"[CAPTCHA] User={user_id} удалён из pending")

        # Добавляем в good_users для статистики скоринга
        try:
            user = callback.from_user
            
            # Получаем photo_count
            photo_count = 0
            try:
                photos = await bot.get_user_profile_photos(user_id, limit=100)
                photo_count = photos.total_count
            except Exception as e:
                logger.warning(f"Не удалось получить фото для {user_id}: {e}")
            
            # Получаем данные чата для логирования
            chat_data = await db.get_chat(chat_id)
            chat_username = chat_data.get('username') if chat_data else None
            
            # Вычисляем скор для статистики
            scoring_score = 0
            try:
                scoring_config_data = await db.get_scoring_config(chat_id)
                if scoring_config_data:
                    stats_data = await db.get_scoring_stats(chat_id, days=7)
                    
                    cfg = ScoringConfig(**scoring_config_data)
                    stats = ScoringStats(
                        lang_counts=stats_data['lang_counts'],
                        total_good_joins=stats_data['total_good_joins'],
                        p95_id=stats_data['p95_id'],
                        p99_id=stats_data['p99_id']
                    )
                    
                    scoring_score = score_user(
                        user, photo_count=photo_count, cfg=cfg, stats=stats,
                        chat_id=chat_id, chat_username=chat_username
                    )
            except Exception as e:
                logger.error(f"Не удалось вычислить скор для good_user {user_id}: {e}")
            
            await db.add_good_user(
                chat_id, user.id,
                user.first_name, user.last_name, user.username,
                user.language_code, user.is_premium or False,
                photo_count,
                scoring_score=scoring_score
            )
            print(f"[CAPTCHA] User={user_id} добавлен в good_users (score={scoring_score}, photos={photo_count})")
        except Exception as e:
            print(f"[CAPTCHA] Не удалось добавить в good_users: {e}")

        # Приветственное сообщение
        chat_data = await db.get_chat(chat_id)
        welcome_text = chat_data.get('welcome_message') if chat_data else None
        if welcome_text:
            try:
                formatted_text = _format_welcome_text(welcome_text, callback)
                welcome_msg = await bot.send_message(
                    chat_id,
                    formatted_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                asyncio.create_task(delete_message_later(bot, chat_id, welcome_msg.message_id, delay=180))
            except Exception as e:
                print(f"[CAPTCHA] Не удалось отправить приветствие: {e}")
        
    else:
        # НЕПРАВИЛЬНЫЙ ОТВЕТ - бан
        print(f"[CAPTCHA] User={user_id} НЕ прошёл капчу, кикаю...")
        await callback.answer("❌ Неверно. До свидания!", show_alert=True)
        
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)  # kick
            print(f"[CAPTCHA] User={user_id} кикнут за неправильный ответ")
            
            # Удаляем сообщение
            try:
                await bot.delete_message(chat_id, pending['message_id'])
            except:
                pass
            
            # Удаляем из pending
            await db.remove_pending_captcha(chat_id, user_id)
            
            chat_logger.log_kick(chat_id, None, user_id, callback.from_user.username, "captcha_wrong")
            
        except Exception as e:
            print(f"[CAPTCHA] Ошибка кика user={user_id} за неправильный ответ: {e}")




@router.message(Command("rules"))
async def handle_rules_command(message: Message, bot: Bot):
    """Вывод правил чата по команде /rules"""
    chat_id = message.chat.id
    chat_data = await db.get_chat(chat_id)
    
    if not chat_data:
        return
    
    rules_text = chat_data.get('rules_message')
    
    if not rules_text:
        reply_text = "ℹ️ Правила ещё не заданы для этого чата."
    else:
        reply_text = rules_text
    
    try:
        rules_message = await bot.send_message(chat_id, reply_text)
        asyncio.create_task(delete_message_later(bot, chat_id, rules_message.message_id, delay=180))
        asyncio.create_task(delete_message_later(bot, chat_id, message.message_id, delay=180))
    except Exception as e:
        print(f"[RULES] Не удалось отправить правила: {e}")
