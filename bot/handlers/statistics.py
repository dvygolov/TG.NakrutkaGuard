"""Handlers для отображения статистики чата"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import db
from bot.handlers import statistics_clear

router = Router()
router.include_router(statistics_clear.router)


def get_statistics_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура меню статистики"""
    buttons = [
        [InlineKeyboardButton(text="⚙️ Текущие настройки", callback_data=f"stats_settings_{chat_id}")],
        [InlineKeyboardButton(text="📈 Эффективность защиты", callback_data=f"stats_effectiveness_{chat_id}")],
        [InlineKeyboardButton(text="🔄 История корректировок", callback_data=f"stats_history_{chat_id}")],
        [InlineKeyboardButton(text="❌ Профиль неудачников", callback_data=f"stats_failed_{chat_id}")],
        [InlineKeyboardButton(text="✅ Профиль успешных", callback_data=f"stats_success_{chat_id}")],
        [InlineKeyboardButton(text="◀️ Назад к чату", callback_data=f"chat_{chat_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("stats_menu_"))
async def show_statistics_menu(callback: CallbackQuery):
    """Показать главное меню статистики"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    if not chat_data:
        await callback.answer("Чат не найден", show_alert=True)
        return
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    await callback.message.edit_text(
        f"📊 <b>Статистика: {chat_name}</b>\n\n"
        "Выберите раздел:",
        reply_markup=get_statistics_menu_keyboard(chat_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_settings_"))
async def show_current_settings(callback: CallbackQuery):
    """Показать текущие настройки скоринга"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    config = await db.get_scoring_config(chat_id)
    
    if not config:
        await callback.answer("Скоринг не настроен", show_alert=True)
        return
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"⚙️ <b>Текущие настройки: {chat_name}</b>\n\n"
    
    text += f"<b>Основные параметры:</b>\n"
    text += f"• Порог скоринга: <code>{config['threshold']}</code>\n"
    text += f"• Автокорректировка: {'✅ Включена' if config.get('auto_adjust', True) else '❌ Выключена'}\n"
    text += f"• Скоринг: {'✅ Включён' if chat_data.get('scoring_enabled') else '❌ Выключен'}\n"
    text += f"• Капча: {'✅ Включена' if chat_data.get('captcha_enabled') else '❌ Выключена'}\n\n"
    
    text += f"<b>Веса признаков риска:</b>\n"
    text += f"• Нет username: <code>{config['no_username_risk']}</code>\n"
    text += f"• Арабские/CJK символы: <code>{config['arabic_cjk_risk']}</code>\n"
    text += f"• Странное имя (без лат/кир): <code>{config['weird_name_risk']}</code>\n"
    text += f"• Нет аватарок: <code>{config['no_avatar_risk']}</code>\n"
    text += f"• Одна аватарка: <code>{config['one_avatar_risk']}</code>\n"
    text += f"• Макс. риск по языку: <code>{config['max_lang_risk']}</code>\n"
    text += f"• Нет языка: <code>{config['no_lang_risk']}</code>\n"
    text += f"• Макс. риск по ID: <code>{config['max_id_risk']}</code>\n"
    text += f"• Бонус премиум: <code>{config['premium_bonus']}</code>\n\n"
    
    lang_dist = config.get('lang_distribution', {})
    if lang_dist:
        text += f"<b>Ожидаемые языки:</b>\n"
        for lang, pct in sorted(lang_dist.items(), key=lambda x: x[1], reverse=True):
            text += f"• {lang}: {int(pct * 100)}%\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_effectiveness_"))
async def show_effectiveness(callback: CallbackQuery):
    """Показать эффективность защиты"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    stats = await db.get_protection_effectiveness(chat_id, days=7)
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    total = stats['verified'] + stats['failed_captcha'] + stats['kicked_in_attack']
    
    text = f"📈 <b>Эффективность защиты: {chat_name}</b>\n\n"
    text += f"<b>За последние 7 дней:</b>\n\n"
    
    if total == 0:
        text += "<i>Недостаточно данных для отображения статистики</i>"
    else:
        text += f"✅ <b>Прошли верификацию:</b> {stats['verified']}\n"
        text += f"   → {stats['verified'] / total * 100:.1f}% от общего числа\n\n"
        
        text += f"❌ <b>Провалили капчу:</b> {stats['failed_captcha']}\n"
        text += f"   → {stats['failed_captcha'] / total * 100:.1f}% от общего числа\n\n"
        
        text += f"🚫 <b>Кикнуто в режиме атаки:</b> {stats['kicked_in_attack']}\n"
        text += f"   → {stats['kicked_in_attack'] / total * 100:.1f}% от общего числа\n\n"
        
        text += f"📊 <b>Всего обработано:</b> {total}\n\n"
        
        blocked = stats['failed_captcha'] + stats['kicked_in_attack']
        if blocked > 0:
            text += f"🛡 <b>Отсеяно ботов:</b> {blocked / total * 100:.1f}%"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_history_"))
async def show_adjustment_history(callback: CallbackQuery):
    """Показать историю автокорректировок"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=1)
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"🔄 <b>История корректировок: {chat_name}</b>\n\n"
    
    if not failed_stats:
        text += "<i>Нет данных о провалах капчи.\n"
        text += "Автокорректировка запускается после накопления минимум 30 провалов.</i>"
    else:
        total = failed_stats['total_failed']
        text += f"<b>Накоплено провалов капчи:</b> {total}\n\n"
        
        if total < 30:
            text += f"⏳ <i>Для первой корректировки нужно ещё {30 - total} провалов</i>\n\n"
        else:
            next_trigger = 50 - (total % 50)
            text += f"📊 <i>Следующая корректировка через {next_trigger} провалов</i>\n\n"
        
        text += f"<b>Текущие частоты признаков:</b>\n"
        text += f"• Без username: {failed_stats['no_username_rate'] * 100:.1f}%\n"
        text += f"• Арабские/CJK: {failed_stats['arabic_cjk_rate'] * 100:.1f}%\n"
        text += f"• Странное имя: {failed_stats['weird_name_rate'] * 100:.1f}%\n"
        text += f"• Без аватарок: {failed_stats['no_avatar_rate'] * 100:.1f}%\n"
        text += f"• Одна аватарка: {failed_stats['one_avatar_rate'] * 100:.1f}%\n"
        text += f"• Без языка: {failed_stats.get('no_language_rate', 0) * 100:.1f}%\n"
        text += f"• Новый ID (>8 млрд): {failed_stats.get('new_id_rate', 0) * 100:.1f}%\n\n"
        
        text += f"<b>Средний скор провалов:</b> {failed_stats['avg_failed_score']}\n\n"
        
        # Показываем параметры, достигшие максимума
        config = await db.get_scoring_config(chat_id)
        if config:
            max_limits = {
                'no_username_risk': 30,
                'arabic_cjk_risk': 40,
                'weird_name_risk': 25,
                'no_avatar_risk': 30,
                'one_avatar_risk': 15,
                'no_lang_risk': 25,
                'max_id_risk': 30
            }
            maxed_out = []
            for param, max_val in max_limits.items():
                if config.get(param, 0) >= max_val:
                    param_names = {
                        'no_username_risk': 'Без username',
                        'arabic_cjk_risk': 'Арабские/CJK',
                        'weird_name_risk': 'Странное имя',
                        'no_avatar_risk': 'Без аватарок',
                        'one_avatar_risk': 'Одна аватарка',
                        'no_lang_risk': 'Без языка',
                        'max_id_risk': 'ID риск'
                    }
                    maxed_out.append(param_names.get(param, param))
            
            if maxed_out:
                text += f"<b>⚠️ Достигли максимума:</b>\n"
                for name in maxed_out:
                    text += f"• {name}\n"
                text += "\n"
        
        text += "<i>💡 Если частота признака > 70%, вес автоматически увеличится на 5 пунктов</i>"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_failed_"))
async def show_failed_profile(callback: CallbackQuery):
    """Показать профиль неудачников (провалили капчу)"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=1)
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"❌ <b>Профиль неудачников: {chat_name}</b>\n\n"
    
    if not failed_stats:
        text += "<i>Нет данных о провалах капчи за последние 7 дней</i>"
    else:
        total = failed_stats['total_failed']
        text += f"<b>Всего провалов за 7 дней:</b> {total}\n\n"
        
        text += f"<b>Характеристики:</b>\n"
        text += f"• Без username: {failed_stats['no_username_rate'] * 100:.1f}%\n"
        text += f"• Арабские/CJK символы: {failed_stats['arabic_cjk_rate'] * 100:.1f}%\n"
        text += f"• Без лат/кир в имени: {failed_stats['weird_name_rate'] * 100:.1f}%\n"
        text += f"• Без аватарок: {failed_stats['no_avatar_rate'] * 100:.1f}%\n"
        text += f"• Одна аватарка: {failed_stats['one_avatar_rate'] * 100:.1f}%\n"
        text += f"• Без языка: {failed_stats.get('no_language_rate', 0) * 100:.1f}%\n"
        text += f"• Новый ID (>8 млрд): {failed_stats.get('new_id_rate', 0) * 100:.1f}%\n\n"
        
        text += f"<b>Средний скор:</b> {failed_stats['avg_failed_score']}\n\n"
        
        if failed_stats.get('top_failed_langs'):
            text += f"<b>Топ-5 языков неудачников:</b>\n"
            for lang, rate in failed_stats['top_failed_langs'].items():
                text += f"• {lang}: {rate * 100:.1f}%\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_success_"))
async def show_success_profile(callback: CallbackQuery):
    """Показать профиль успешных (прошли верификацию)"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    good_stats = await db.get_good_users_stats(chat_id, days=7, min_samples=1)
    scoring_stats = await db.get_scoring_stats(chat_id, days=7)
    
    chat_name = chat_data.get('chat_title') or f"ID {chat_id}"
    
    text = f"✅ <b>Профиль успешных: {chat_name}</b>\n\n"
    
    if not good_stats or good_stats['total_good'] == 0:
        text += "<i>Нет данных об успешных верификациях за последние 7 дней</i>"
    else:
        total = good_stats['total_good']
        text += f"<b>Всего прошло верификацию за 7 дней:</b> {total}\n\n"
        
        # Характеристики успешных юзеров
        text += f"<b>Характеристики:</b>\n"
        text += f"• Без username: {good_stats['no_username_rate'] * 100:.1f}%\n"
        text += f"• Без языка: {good_stats['no_language_rate'] * 100:.1f}%\n"
        text += f"• Premium пользователи: {good_stats.get('premium_rate', 0) * 100:.1f}%\n\n"
        
        # Топ языков
        if good_stats.get('top_langs'):
            text += f"<b>Топ-5 языков:</b>\n"
            for lang, rate in good_stats['top_langs'].items():
                text += f"• {lang}: {rate * 100:.1f}%\n"
            text += "\n"
        
        # ID статистика
        if scoring_stats.get('p95_id') and scoring_stats.get('p99_id'):
            text += f"<b>Статистика ID:</b>\n"
            if good_stats.get('avg_user_id'):
                text += f"• Средний ID: {good_stats['avg_user_id'] / 1e9:.2f} млрд\n"
            text += f"• 95-й перцентиль: {scoring_stats['p95_id'] / 1e9:.2f} млрд\n"
            text += f"• 99-й перцентиль: {scoring_stats['p99_id'] / 1e9:.2f} млрд\n\n"
        
        text += "<i>💡 Используется для защиты от false positives при автокорректировке</i>"
    
    buttons = [
        [InlineKeyboardButton(text="◀️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
    ]
    
    # Добавляем кнопку очистки только если есть данные
    if good_stats and good_stats['total_good'] > 0:
        buttons.insert(0, [InlineKeyboardButton(text="🗑 Очистить профиль", callback_data=f"clear_good_confirm_{chat_id}")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()
