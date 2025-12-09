from __future__ import annotations

import asyncio
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.filters import ChatMemberUpdatedFilter, MEMBER, Command
from bot.database import db
from bot.utils.captcha import captcha_gen
from bot.utils.logger import chat_logger
from bot.utils.message_utils import delete_message_later
import time
import html

router = Router()


def _is_not_command(message: Message) -> bool:
    """True если сообщение не команда."""
    text = message.text or message.caption or ""
    return not text.startswith("/")


def _format_welcome_text(template: str, user: Message | CallbackQuery) -> str:
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


async def send_captcha(bot: Bot, chat_id: int, user_id: int, username: str = None):
    """
    Отправить капчу пользователю
    
    Returns:
        True если капча отправлена, False если ошибка
    """
    try:
        print(f"[CAPTCHA] Отправляю капчу для user={user_id} (@{username}) в chat={chat_id}")
        
        # Генерируем капчу
        question, correct_answer, keyboard = captcha_gen.generate()
        print(f"[CAPTCHA] Сгенерирована капча, правильный ответ: {correct_answer}")
        
        # Отправляем сообщение
        user_mention = f"@{username}" if username else f"ID: {user_id}"
        text = (
            f"{user_mention}, чтобы вступить, пройдите проверку.\n\n"
            f"{question}"
        )
        
        message = await bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard
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
        
        chat_logger.log_join(chat_id, None, user_id, username, False, False)
        
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
        
        # Не прошёл - баним
        kick_success = False
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)  # kick
            kick_success = True
            print(f"[CAPTCHA] User={user_id} кикнут")
            chat_logger.log_kick(chat_id, None, user_id, None, "captcha_timeout")
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

        # Приветственное сообщение
        chat_data = await db.get_chat(chat_id)
        welcome_text = chat_data.get('welcome_message') if chat_data else None
        if welcome_text:
            try:
                formatted_text = _format_welcome_text(welcome_text, callback)
                welcome_msg = await bot.send_message(chat_id, formatted_text)
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


@router.message(_is_not_command, F.chat.type.in_({"group", "supergroup"}))
async def handle_group_messages(message: Message, bot: Bot):
    """Обработка сообщений в группах"""
    chat_id = message.chat.id
    
    # Проверяем защищён ли чат
    chat_data = await db.get_chat(chat_id)
    if not chat_data:
        # Чат не под защитой - ничего не делаем
        return
    
    # 1. Удаляем системные сообщения (join/left/kicked)
    if message.new_chat_members or message.left_chat_member:
        print(f"[SYSTEM] Удаляю системное сообщение в chat={chat_id}, message_id={message.message_id}")
        try:
            await bot.delete_message(chat_id, message.message_id)
            print(f"[SYSTEM] Системное сообщение удалено")
        except Exception as e:
            print(f"[SYSTEM] Не удалось удалить системное сообщение: {e}")
        return
    
    # 2. Удаляем сообщения от юзеров которые не прошли капчу
    if message.from_user:
        user_id = message.from_user.id
        pending = await db.get_pending_captcha(chat_id, user_id)
        
        if pending:
            print(f"[CAPTCHA] User={user_id} написал сообщение но не прошёл капчу, удаляю...")
            try:
                await bot.delete_message(chat_id, message.message_id)
                print(f"[CAPTCHA] Сообщение от user={user_id} удалено")
            except Exception as e:
                print(f"[CAPTCHA] Ошибка удаления сообщения от pending user {user_id}: {e}")


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
