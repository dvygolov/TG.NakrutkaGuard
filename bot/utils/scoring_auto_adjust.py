"""
Автоматическая корректировка весов скоринга на основе провалов капчи.
"""
import logging
from typing import Dict, Any, Optional
from bot.database import db

logger = logging.getLogger(__name__)


async def auto_adjust_scoring(chat_id: int) -> Optional[Dict[str, Any]]:
    """
    Автоматически корректировать веса скоринга на основе статистики провалов капчи.
    
    Алгоритм:
    1. Собираем статистику за последние 7 дней (минимум 30 провалов)
    2. Если какой-то признак встречается у 70%+ неудачников -> увеличиваем штраф
    3. Если средний скор неудачников < порог-10 -> повышаем порог или веса
    
    Args:
        chat_id: ID чата
    
    Returns:
        Dict с изменениями или None если корректировка не нужна
    """
    # Проверяем включена ли автокорректировка
    config = await db.get_scoring_config(chat_id)
    if not config or not config.get('auto_adjust', True):
        return None
    
    # Получаем статистику провалов (минимум 30 примеров)
    failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=30)
    if not failed_stats:
        logger.info(f"Chat {chat_id}: недостаточно данных для автокорректировки")
        return None
    
    logger.info(f"Chat {chat_id}: автокорректировка на основе {failed_stats['total_failed']} провалов")
    
    # Получаем статистику успешных юзеров для защиты от false positives
    good_stats = await db.get_good_users_stats(chat_id, days=7, min_samples=30)
    if good_stats:
        logger.info(f"Chat {chat_id}: анализируем {good_stats['total_good']} успешных юзеров для защиты от false positives")
    else:
        logger.info(f"Chat {chat_id}: недостаточно успешных юзеров (< 30) для проверки false positives")
    
    # Текущие веса
    current_weights = {
        'no_username_risk': config['no_username_risk'],
        'arabic_cjk_risk': config['arabic_cjk_risk'],
        'weird_name_risk': config['weird_name_risk'],
        'no_avatar_risk': config['no_avatar_risk'],
        'one_avatar_risk': config['one_avatar_risk'],
        'no_lang_risk': config['no_lang_risk'],
        'max_id_risk': config['max_id_risk'],
        'random_username_risk': config['random_username_risk'],
    }
    
    updated_weights = current_weights.copy()
    changes = []
    weights_changed = False
    
    # Корректируем на основе частот (порог 70%)
    HIGH_FREQ_THRESHOLD = 0.70
    FALSE_POSITIVE_THRESHOLD = 0.50  # если 50%+ успешных имеют признак - не повышаем вес
    ADJUSTMENT_STEP = 5
    
    # Username
    if failed_stats['no_username_rate'] > HIGH_FREQ_THRESHOLD:
        # Защита от false positives: проверяем успешных юзеров
        good_rate = good_stats.get('no_username_rate', 0) if good_stats else 0
        if good_stats and good_rate > FALSE_POSITIVE_THRESHOLD:
            msg = f"no_username_risk: НЕ повышаем - false positive (провалы: {failed_stats['no_username_rate']:.1%}, успешные: {good_rate:.1%})"
            changes.append(msg)
            logger.warning(f"Chat {chat_id}: {msg}")
        else:
            old = current_weights['no_username_risk']
            new = min(old + ADJUSTMENT_STEP, 30)  # макс 30
            if new != old:
                updated_weights['no_username_risk'] = new
                changes.append(f"no_username_risk: {old} -> {new} (failed={failed_stats['no_username_rate']:.2%})")
                weights_changed = True
    
    # Арабские/CJK
    if failed_stats['arabic_cjk_rate'] > HIGH_FREQ_THRESHOLD:
        old = current_weights['arabic_cjk_risk']
        new = min(old + ADJUSTMENT_STEP, 40)  # макс 40
        if new != old:
            updated_weights['arabic_cjk_risk'] = new
            changes.append(f"arabic_cjk_risk: {old} -> {new} (rate={failed_stats['arabic_cjk_rate']:.2%})")
            weights_changed = True
    
    # Weird names (без латиницы/кириллицы)
    if failed_stats['weird_name_rate'] > HIGH_FREQ_THRESHOLD:
        old = current_weights['weird_name_risk']
        new = min(old + ADJUSTMENT_STEP, 25)  # макс 25
        if new != old:
            updated_weights['weird_name_risk'] = new
            changes.append(f"weird_name_risk: {old} -> {new} (rate={failed_stats['weird_name_rate']:.2%})")
            weights_changed = True
    
    # Нет аватарок
    if failed_stats['no_avatar_rate'] > HIGH_FREQ_THRESHOLD:
        old = current_weights['no_avatar_risk']
        new = min(old + ADJUSTMENT_STEP, 30)  # макс 30
        if new != old:
            updated_weights['no_avatar_risk'] = new
            changes.append(f"no_avatar_risk: {old} -> {new} (rate={failed_stats['no_avatar_rate']:.2%})")
            weights_changed = True
    
    # Одна аватарка
    if failed_stats['one_avatar_rate'] > HIGH_FREQ_THRESHOLD:
        old = current_weights['one_avatar_risk']
        new = min(old + ADJUSTMENT_STEP, 15)  # макс 15
        if new != old:
            updated_weights['one_avatar_risk'] = new
            changes.append(f"one_avatar_risk: {old} -> {new} (rate={failed_stats['one_avatar_rate']:.2%})")
            weights_changed = True
    
    # Язык риск (нет языка)
    no_lang_rate = failed_stats.get('no_language_rate', 0)
    if no_lang_rate > HIGH_FREQ_THRESHOLD:
        # Защита от false positives
        good_no_lang = good_stats.get('no_language_rate', 0) if good_stats else 0
        if good_stats and good_no_lang > FALSE_POSITIVE_THRESHOLD:
            msg = f"no_lang_risk: НЕ повышаем - false positive (провалы: {no_lang_rate:.1%}, успешные: {good_no_lang:.1%})"
            changes.append(msg)
            logger.warning(f"Chat {chat_id}: {msg}")
        else:
            old_no_lang = config['no_lang_risk']
            new_no_lang = min(old_no_lang + ADJUSTMENT_STEP, 25)  # макс 25
            if new_no_lang != old_no_lang:
                updated_weights['no_lang_risk'] = new_no_lang
                changes.append(f"no_lang_risk: {old_no_lang} -> {new_no_lang} (failed={no_lang_rate:.2%})")
                weights_changed = True
    
    # ID риск (на основе p99/p95)
    id_p99_rate = failed_stats.get('id_above_p99_rate', 0)
    id_p95_rate = failed_stats.get('id_above_p95_rate', 0)
    
    if id_p99_rate > HIGH_FREQ_THRESHOLD:
        # Много ботов с супер новыми ID (выше p99)
        old_id_risk = config['max_id_risk']
        new_id_risk = min(old_id_risk + ADJUSTMENT_STEP, 30)  # макс 30
        if new_id_risk != old_id_risk:
            updated_weights['max_id_risk'] = new_id_risk
            changes.append(f"max_id_risk: {old_id_risk} -> {new_id_risk} (p99_rate={id_p99_rate:.2%})")
            weights_changed = True
    elif id_p95_rate > HIGH_FREQ_THRESHOLD:
        # Много ботов с новыми ID (выше p95, но не p99)
        old_id_risk = config['max_id_risk']
        new_id_risk = min(old_id_risk + ADJUSTMENT_STEP, 30)  # макс 30
        if new_id_risk != old_id_risk:
            updated_weights['max_id_risk'] = new_id_risk
            changes.append(f"max_id_risk: {old_id_risk} -> {new_id_risk} (p95_rate={id_p95_rate:.2%})")
            weights_changed = True
    
    # Проверяем порог
    # Если боты проходят скоринг с высоким скором и валятся на капче - понижаем порог
    threshold = config['threshold']
    avg_failed_score = failed_stats['avg_failed_score']
    threshold_changed = False
    
    if avg_failed_score > 0 and avg_failed_score >= threshold - 10:
        # Боты проходят скоринг с высоким скором (близким к порогу)
        # Значит порог слишком мягкий - понижаем, чтобы они банились скорингом
        new_threshold = max(threshold - 5, 20)  # мин порог 20
        if new_threshold != threshold:
            threshold = new_threshold
            changes.append(f"threshold: {config['threshold']} -> {new_threshold} (avg_failed={avg_failed_score}, too close to threshold)")
            threshold_changed = True
    
    # Применяем изменения
    if weights_changed or threshold_changed:
        import json
        
        updates = {}
        
        # Сохраняем обновлённые веса как JSON
        if weights_changed:
            # Берём все веса из конфига (не только те что изменились)
            all_weights = {
                'max_lang_risk': config['max_lang_risk'],
                'no_lang_risk': updated_weights['no_lang_risk'],  # используем обновлённый
                'max_id_risk': updated_weights['max_id_risk'],  # используем обновлённый
                'premium_bonus': config['premium_bonus'],
                'no_avatar_risk': updated_weights['no_avatar_risk'],
                'one_avatar_risk': updated_weights['one_avatar_risk'],
                'no_username_risk': updated_weights['no_username_risk'],
                'weird_name_risk': updated_weights['weird_name_risk'],
                'arabic_cjk_risk': updated_weights['arabic_cjk_risk'],
            }
            updates['scoring_weights'] = json.dumps(all_weights)
        
        # Обновляем порог если изменился
        if threshold_changed:
            updates['scoring_threshold'] = threshold
        
        await db.update_chat_settings(chat_id, **updates)
        logger.info(f"Chat {chat_id}: применены изменения:\n" + "\n".join(changes))
        return {
            'changes': changes,
            'stats': failed_stats
        }
    else:
        logger.info(f"Chat {chat_id}: корректировка не требуется")
        return None


async def should_trigger_auto_adjust(chat_id: int) -> bool:
    """
    Проверить нужно ли запускать автокорректировку.
    Запускается каждые 50 провалов капчи.
    """
    # Считаем провалы за последние 7 дней
    failed_stats = await db.get_failed_captcha_stats(chat_id, days=7, min_samples=1)
    if not failed_stats:
        return False
    
    total = failed_stats['total_failed']
    # Запускаем каждые 50 провалов (50, 100, 150, ...)
    return total > 0 and total % 50 == 0
