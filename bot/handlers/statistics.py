"""Handlers для отображения статистики чата"""
import html
import io
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from bot.database import db
from bot.handlers import statistics_clear

router = Router()
router.include_router(statistics_clear.router)


def get_statistics_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура меню статистики"""
    buttons = [
        [InlineKeyboardButton(text="⚙️ Текущие настройки", callback_data=f"stats_settings_{chat_id}")],
        [InlineKeyboardButton(text="📈 Эффективность защиты", callback_data=f"stats_effectiveness_{chat_id}")],
        [InlineKeyboardButton(text="📊 График по дням", callback_data=f"stats_daily_{chat_id}")],

        [InlineKeyboardButton(text="🔄 История корректировок", callback_data=f"stats_history_{chat_id}")],
        [InlineKeyboardButton(text="❌ Профиль неудачников", callback_data=f"stats_failed_{chat_id}")],
        [InlineKeyboardButton(text="✅ Профиль успешных", callback_data=f"stats_success_{chat_id}")],
        [InlineKeyboardButton(text="◀️ Назад к чату", callback_data=f"chat_{chat_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_daily_chart(stats: list, title: str) -> io.BytesIO:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [item['date'][5:] for item in stats]
    x = list(range(len(labels)))
    scoring = [item['scoring_kicked'] for item in stats]
    attack = [item['attack_kicked'] for item in stats]
    failed = [item['failed_captcha'] for item in stats]
    joined = [item['joined'] for item in stats]

    fig, (ax_chart, ax_table) = plt.subplots(
        2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [2, 3]}
    )

    ax_chart.plot(x, scoring, label="Scoring kicks", color="#0072B2", linewidth=3, marker="o", markersize=3)
    ax_chart.plot(x, attack, label="Attack kicks", color="#CC79A7", linewidth=3, marker="s", markersize=3)
    ax_chart.plot(x, failed, label="Captcha failed", color="#E69F00", linewidth=3, marker="^", markersize=3)
    ax_chart.plot(x, joined, label="Joined", color="#000000", linewidth=3, marker="D", markersize=3)
    ax_chart.set_ylabel("Users")
    ax_chart.set_title(f"Daily stats (last {len(stats)} days): {title}")
    ax_chart.grid(True, alpha=0.3)
    ax_chart.legend(loc="upper left")

    tick_step = 2 if len(labels) <= 20 else 3
    tick_positions = x[::tick_step]
    tick_labels = [labels[i] for i in tick_positions]
    ax_chart.set_xticks(tick_positions)
    ax_chart.set_xticklabels(tick_labels, rotation=45, ha="right")

    ax_table.axis("off")
    total_scoring = sum(item['scoring_kicked'] for item in stats)
    total_attack = sum(item['attack_kicked'] for item in stats)
    total_failed = sum(item['failed_captcha'] for item in stats)
    total_joined = sum(item['joined'] for item in stats)
    table_rows = [
        [item['date'], item['scoring_kicked'], item['attack_kicked'], item['failed_captcha'], item['joined']]
        for item in stats
    ]
    table_rows.append(["ИТОГО", total_scoring, total_attack, total_failed, total_joined])
    table = ax_table.table(
        cellText=table_rows,
        colLabels=["Date", "Scoring", "Attack", "Captcha", "Joined"],
        colWidths=[0.22, 0.16, 0.16, 0.16, 0.16],
        loc="center",
        bbox=[0.07, 0.0, 0.86, 1.0]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(0.9, 1.15)
    for col_idx in range(5):
        header_cell = table[(0, col_idx)]
        header_cell.set_text_props(weight="bold")
        header_cell.set_facecolor("#F0F0F0")

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer


@router.callback_query(F.data.startswith("stats_menu_"))
async def show_statistics_menu(callback: CallbackQuery):
    """Показать главное меню статистики"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    if not chat_data:
        await callback.answer("Чат не найден", show_alert=True)
        return
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
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
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
    text = f"⚙️ <b>Текущие настройки: {chat_name}</b>\n\n"
    
    text += f"<b>Основные параметры:</b>\n"
    text += f"• Порог скоринга: <code>{config['threshold']}</code>\n"
    text += f"• Автокорректировка: {'✅ Включена' if config.get('auto_adjust', True) else '❌ Выключена'}\n"
    text += f"• Скоринг: {'✅ Включён' if chat_data.get('scoring_enabled') else '❌ Выключен'}\n"
    text += f"• Капча: {'✅ Включена' if chat_data.get('captcha_enabled') else '❌ Выключена'}\n\n"
    
    text += f"<b>Веса признаков риска:</b>\n"
    text += f"• Нет username: <code>{config['no_username_risk']}</code>\n"
    text += f"• Рандомный username: <code>{config['random_username_risk']}</code>\n"
    text += f"• Экзотические письменности: <code>{config['exotic_script_risk']}</code>\n"
    text += f"• Странное имя (без лат/кир): <code>{config['weird_name_risk']}</code>\n"
    text += f"• Спецсимволы в имени: <code>{config.get('special_chars_risk', 15)}</code>\n"
    text += f"• Повторы символов: <code>{config.get('repeating_chars_risk', 5)}</code>\n"
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
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
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


@router.callback_query(F.data.startswith("stats_daily_"))
async def show_daily_chart(callback: CallbackQuery):
    """Показать график по дням за последние 30 дней."""
    chat_id = int(callback.data.split("_")[2])

    chat_data = await db.get_chat(chat_id)
    if not chat_data:
        await callback.answer("Чат не найден", show_alert=True)
        return

    chat_name = chat_data.get('title') or f"ID {chat_id}"
    stats = await db.get_daily_join_stats(chat_id, days=30)

    chart = _build_daily_chart(stats, chat_name)
    await callback.message.edit_text(
        f"📊 <b>График за последние {len(stats)} дней</b>\n{html.escape(chat_name)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к статистике", callback_data=f"stats_menu_{chat_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.message.answer_photo(
        BufferedInputFile(chart.getvalue(), filename="daily-stats.png")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stats_history_"))
async def show_adjustment_history(callback: CallbackQuery):
    """Показать историю автокорректировок"""
    chat_id = int(callback.data.split("_")[2])
    
    chat_data = await db.get_chat(chat_id)
    failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=1)
    history = await db.get_adjustment_history(chat_id, limit=10)
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
    text = f"🔄 <b>История корректировок: {chat_name}</b>\n\n"
    if history:
        text += "<b>Последние автокорректировки:</b>\n"
        for item in history[:5]:
            ts = datetime.fromtimestamp(item['created_at']).strftime("%d.%m %H:%M")
            changes = [line for line in (item.get('changes_text') or '').splitlines() if line.strip()]
            summary = changes[0] if changes else "Обновлены параметры скоринга"
            text += (
                f"• <b>{ts}</b> | samples: {item.get('trigger_samples', 0)}\n"
                f"  {html.escape(summary)}\n"
            )
            if item.get('old_threshold') != item.get('new_threshold'):
                text += f"  threshold: {item.get('old_threshold')} → {item.get('new_threshold')}\n"
        text += "\n"
    else:
        text += "<i>История изменений пока пуста.</i>\n\n"
    
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
                'exotic_script_risk': 40,
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
                        'exotic_script_risk': 'Экзотические письменности',
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
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
    text = f"❌ <b>Профиль неудачников: {chat_name}</b>\n\n"
    
    if not failed_stats:
        text += "<i>Нет данных о провалах капчи за последние 7 дней</i>"
    else:
        total = failed_stats['total_failed']
        text += f"<b>Всего провалов за 7 дней:</b> {total}\n\n"
        
        text += f"<b>Характеристики:</b>\n"
        text += f"• Без username: {failed_stats['no_username_rate'] * 100:.1f}%\n"
        text += f"• Рандомный username: {failed_stats.get('random_username_rate', 0) * 100:.1f}%\n"
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
    
    chat_name = chat_data.get('title') or f"ID {chat_id}"
    
    text = f"✅ <b>Профиль успешных: {chat_name}</b>\n\n"
    
    if not good_stats or good_stats['total_good'] == 0:
        text += "<i>Нет данных об успешных верификациях за последние 7 дней</i>"
    else:
        total = good_stats['total_good']
        text += f"<b>Всего прошло верификацию за 7 дней:</b> {total}\n\n"
        
        # Характеристики успешных юзеров
        text += f"<b>Характеристики:</b>\n"
        text += f"• Без username: {good_stats['no_username_rate'] * 100:.1f}%\n"
        text += f"• Рандомный username: {good_stats.get('random_username_rate', 0) * 100:.1f}%\n"
        text += f"• Без языка: {good_stats['no_language_rate'] * 100:.1f}%\n"
        text += f"• Premium пользователи: {good_stats.get('premium_rate', 0) * 100:.1f}%\n\n"
        
        # Топ языков
        if good_stats.get('top_langs'):
            text += f"<b>Топ-5 языков:</b>\n"
            for lang, rate in good_stats['top_langs'].items():
                text += f"• {lang}: {rate * 100:.1f}%\n"
            text += "\n"
        
        # Скоринг
        avg_good_score = good_stats.get('avg_score', 0)
        text += f"<b>Средний скор:</b> {avg_good_score}\n"
        
        # Сравнение с провалами капчи
        failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=1)
        if failed_stats:
            avg_failed_score = failed_stats.get('avg_failed_score', 0)
            diff = avg_failed_score - avg_good_score
            
            text += f"<b>Средний скор провалов:</b> {avg_failed_score}\n"
            text += f"<b>Разница:</b> {diff:+d} 📊\n\n"
            
            if diff > 20:
                text += "✅ <i>Отличное разделение! Скоринг работает эффективно</i>\n\n"
            elif diff > 10:
                text += "⚠️ <i>Неплохо, но можно улучшить автокорректировкой</i>\n\n"
            else:
                text += "🔴 <i>Слабое разделение! Рекомендуется включить автокорректировку</i>\n\n"
        else:
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
