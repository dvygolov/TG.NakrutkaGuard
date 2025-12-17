from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional
import logging
import re

from aiogram.types import User

logger = logging.getLogger(__name__)


# ---------------- Конфиг и статистика ---------------- #

@dataclass
class ScoringConfig:
    """
    Конфигурация скоринга для чата/канала.
    lang_distribution: ожидаемое распределение языков в долях (0–1).
        Пример: {'ru': 0.8, 'en': 0.2}
    """
    lang_distribution: Dict[str, float]
    max_lang_risk: int = 25      # максимум штрафа за редкий/неожиданный язык
    no_lang_risk: int = 15       # штраф за отсутствие языка
    max_id_risk: int = 20        # максимум штрафа за новый ID
    premium_bonus: int = -20     # сколько вычитаем за премиум
    no_avatar_risk: int = 15     # штраф за 0 аватаров
    one_avatar_risk: int = 5     # штраф за 1 аватар (подозрительно)
    no_username_risk: int = 5    # штраф за отсутствие username
    weird_name_risk: int = 10    # штраф за отсутствие латиницы/кириллицы в ФИО
    arabic_cjk_risk: int = 25    # штраф за арабские/китайские символы в имени


@dataclass
class ScoringStats:
    """
    Исторические данные за последние 7 дней (из БД).
    lang_counts: сколько 'нормальных' пользователей с каждым языком.
    total_good_joins: всего нормальных join'ов.
    p95_id / p99_id: перцентили ID по 'хорошим' юзерам.
    """
    lang_counts: Dict[str, int]
    total_good_joins: int
    p95_id: Optional[int] = None
    p99_id: Optional[int] = None


# ---------------- Вспомогательные функции ---------------- #

LANG_CODE_RE = re.compile(r"^[a-zA-Z]{2,3}")       # выцепляем базовый язык из 'en-US' и т.п.
NAME_HAS_LAT_CYR_RE = re.compile(r"[A-Za-zА-Яа-я]")  # проверка ФИО на латиницу/кириллицу
NAME_HAS_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")  # арабские символы
NAME_HAS_CJK_RE = re.compile(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]")  # китайские/японские/корейские

# Экспортируем для использования в других модулях (например, для логирования failed captcha)
LATIN_CYRILLIC_REGEX = NAME_HAS_LAT_CYR_RE
ARABIC_CJK_REGEX = re.compile(r"[\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]")  # арабские + CJK


def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    m = LANG_CODE_RE.match(lang)
    return m.group(0).lower() if m else lang.lower()


def _compute_lang_risk(user_lang: Optional[str],
                       cfg: ScoringConfig,
                       stats: ScoringStats) -> int:
    """
    Новая логика языкового риска:
    - Нет языка → no_lang_risk (штраф)
    - Язык в распределении → бонус пропорционально популярности: -(share * max_lang_risk)
    - Редкий/неожиданный язык → max_lang_risk (штраф)
    
    Примеры (max_lang_risk=30, no_lang_risk=15):
    - None → +15
    - ru (80%) → -24
    - en (20%) → -6
    - ar (не в распределении) → +30
    """
    if not user_lang:
        # Нет языка - отдельный штраф
        return cfg.no_lang_risk

    lang = _normalize_lang(user_lang)

    # Нормируем ожидаемое распределение
    total_expected = sum(cfg.lang_distribution.values()) or 1.0
    expected_share = cfg.lang_distribution.get(lang, 0.0) / total_expected

    # Эмпирическая доля за последние 7 дней
    if stats.total_good_joins > 0:
        empirical_share = stats.lang_counts.get(lang, 0) / stats.total_good_joins
    else:
        empirical_share = expected_share

    # Комбинируем prior (конфиг) и эмпирику
    combined_share = 0.7 * expected_share + 0.3 * empirical_share
    combined_share = max(0.0, min(1.0, combined_share))

    if combined_share > 0.01:  # Язык встречается (порог 1%)
        # Бонус пропорционально популярности языка
        return -int(combined_share * cfg.max_lang_risk)
    else:
        # Редкий/неожиданный язык - штраф
        return cfg.max_lang_risk


def _compute_id_risk(user_id: int, cfg: ScoringConfig, stats: ScoringStats) -> int:
    """
    Новый/подозрительно большой ID относительно p95/p99 получит штраф.
    """
    max_risk = cfg.max_id_risk
    if not stats.p95_id or not stats.p99_id:
        return 0

    if user_id > stats.p99_id:
        return max_risk
    elif user_id > stats.p95_id:
        return int(max_risk * 0.5)
    return 0


def _has_lat_or_cyrillic(full_name: str) -> bool:
    return bool(NAME_HAS_LAT_CYR_RE.search(full_name))


# ---------------- Основная функция скоринга ---------------- #

def score_user(
    user: User,
    *,
    photo_count: int,
    cfg: ScoringConfig,
    stats: ScoringStats,
    chat_id: Optional[int] = None,
    chat_username: Optional[str] = None,
) -> int:
    """
    Возвращает итоговый risk score (0–100) и логирует подробности.
    photo_count — количество аватаров пользователя (через get_user_profile_photos).
    chat_id/chat_username — для логирования с именем чата.
    """

    details = {}
    score = 0

    # 0. Premium
    is_premium = bool(getattr(user, "is_premium", False))
    if is_premium:
        score += cfg.premium_bonus
    details["is_premium"] = is_premium

    # 1. Язык
    lang = getattr(user, "language_code", None)
    lang_risk = _compute_lang_risk(lang, cfg, stats)
    score += lang_risk
    details["lang"] = lang
    details["lang_risk"] = lang_risk

    # 2. Аватары (количество)
    if photo_count == 0:
        score += cfg.no_avatar_risk
        details["avatar_count"] = 0
        details["avatar_risk"] = cfg.no_avatar_risk
    elif photo_count == 1:
        score += cfg.one_avatar_risk
        details["avatar_count"] = 1
        details["avatar_risk"] = cfg.one_avatar_risk
    else:
        # 2+ аватара - нормально
        details["avatar_count"] = photo_count
        details["avatar_risk"] = 0

    # 3. Username (есть / нет)
    username = user.username or ""
    has_username = bool(username)
    if not has_username:
        score += cfg.no_username_risk
        details["username"] = None
        details["username_risk"] = cfg.no_username_risk
    else:
        details["username"] = username
        details["username_risk"] = 0

    # 4. ФИО – проверка символов
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    has_normal_letters = _has_lat_or_cyrillic(full_name)
    has_arabic = bool(NAME_HAS_ARABIC_RE.search(full_name))
    has_cjk = bool(NAME_HAS_CJK_RE.search(full_name))
    
    # Отсутствие рус/англ букв = подозрительно
    if not has_normal_letters:
        score += cfg.weird_name_risk
    
    # Наличие арабских или CJK символов = очень подозрительно
    if has_arabic or has_cjk:
        score += cfg.arabic_cjk_risk
    
    details["full_name"] = full_name
    details["weird_name_risk"] = 0 if has_normal_letters else cfg.weird_name_risk
    details["arabic_cjk_risk"] = cfg.arabic_cjk_risk if (has_arabic or has_cjk) else 0
    details["has_arabic"] = has_arabic
    details["has_cjk"] = has_cjk

    # 5. Новизна ID
    id_risk = _compute_id_risk(user.id, cfg, stats)
    score += id_risk
    details["id_risk"] = id_risk

    # нормализуем итог: 0–100
    score = max(0, min(100, score))
    details["final_score"] = score
    details["user_id"] = user.id

    # лог с именем чата для удобства
    if chat_username or chat_id:
        # Используем отдельный логгер с именем чата
        chat_log_name = chat_username if chat_username else f"chat_{abs(chat_id)}"
        chat_logger = logging.getLogger(chat_log_name)
        chat_logger.info(
            "USER_SCORE id=%s username=%s lang=%s premium=%s avatars=%d score=%d details=%s",
            user.id,
            user.username,
            lang,
            is_premium,
            photo_count,
            score,
            details,
        )
    else:
        # Fallback на обычный логгер
        logger.info(
            "USER_SCORE id=%s username=%s lang=%s premium=%s avatars=%d score=%d details=%s",
            user.id,
            user.username,
            lang,
            is_premium,
            photo_count,
            score,
            details,
        )

    return score
