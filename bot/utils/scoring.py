from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional
import logging
import re

from aiogram.types import User
from bot.utils.username_analysis import username_randomness

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
    no_username_risk: int = 15    # штраф за отсутствие username
    weird_name_risk: int = 10    # штраф за отсутствие латиницы/кириллицы в ФИО
    exotic_script_risk: int = 25 # штраф за экзотические письменности (арабская, китайская, эфиопская, тайская и т.д.)
    special_chars_risk: int = 15 # штраф за специальные символы в имени (>, <, и т.д.)
    repeating_chars_risk: int = 5  # штраф за много повторяющихся символов (jjjjj)
    random_username_risk: int = 15  # штраф за рандомный username (типа Mpib3SFLNYzEzyV)


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

# Экзотические письменности (арабская, CJK, эфиопская, тайская, бенгальская и т.д.)
NAME_EXOTIC_SCRIPT_RE = re.compile(
    r"["
    r"\u0600-\u06FF"      # Arabic
    r"\u4E00-\u9FFF"      # CJK Unified Ideographs
    r"\u3040-\u309F"      # Hiragana
    r"\u30A0-\u30FF"      # Katakana
    r"\uAC00-\uD7AF"      # Hangul (Korean)
    r"\u1200-\u137F"      # Ethiopic
    r"\u0E00-\u0E7F"      # Thai
    r"\u0980-\u09FF"      # Bengali
    r"\u0A00-\u0A7F"      # Gurmukhi
    r"\u0D00-\u0D7F"      # Malayalam
    r"\u0C80-\u0CFF"      # Kannada
    r"\u0B00-\u0B7F"      # Oriya
    r"\u0780-\u07BF"      # Thaana
    r"\u1100-\u11FF"      # Hangul Jamo
    r"]"
)

# Специальные/подозрительные символы (не буквы, не цифры, не стандартные пробелы/дефисы)
NAME_SPECIAL_CHARS_RE = re.compile(r"[<>«»@#$%^&*+=\[\]{}|\\`~]")

def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    m = LANG_CODE_RE.match(lang)
    return m.group(0).lower() if m else lang.lower()


def _compute_lang_risk(user_lang: Optional[str],
                       cfg: ScoringConfig,
                       stats: ScoringStats) -> int:
    """
    Логика языкового риска:
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
        details["random_username"] = None
    else:
        details["username"] = username
        details["username_risk"] = 0
        
        # 3a. Проверка username на рандомность
        randomness = username_randomness(username, threshold=0.60)
        if randomness.is_randomish:
            score += cfg.random_username_risk
            details["random_username_risk"] = cfg.random_username_risk
            details["random_username_score"] = randomness.score
        else:
            details["random_username_risk"] = 0

    # 4. ФИО – проверка символов
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    has_normal_letters = _has_lat_or_cyrillic(full_name)
    has_exotic_script = bool(NAME_EXOTIC_SCRIPT_RE.search(full_name))
    has_special_chars = bool(NAME_SPECIAL_CHARS_RE.search(full_name))
    
    # Подсчёт повторяющихся символов (jjjjj, ааааа)
    max_repeat = 1
    if len(full_name) > 1:
        current_char = full_name[0].lower()
        current_count = 1
        for char in full_name[1:]:
            if char.lower() == current_char and char.isalnum():
                current_count += 1
                max_repeat = max(max_repeat, current_count)
            else:
                current_char = char.lower()
                current_count = 1
    
    # Отсутствие рус/англ букв = подозрительно
    if not has_normal_letters:
        score += cfg.weird_name_risk
    
    # Наличие экзотических письменностей = очень подозрительно
    if has_exotic_script:
        score += cfg.exotic_script_risk
    
    # Специальные символы (>, <, и т.д.) = подозрительно
    if has_special_chars:
        score += cfg.special_chars_risk
    
    # Много повторяющихся символов (5+ подряд) = подозрительно
    if max_repeat >= 5:
        score += cfg.repeating_chars_risk
    
    details["full_name"] = full_name
    details["weird_name_risk"] = 0 if has_normal_letters else cfg.weird_name_risk
    details["exotic_script_risk"] = cfg.exotic_script_risk if has_exotic_script else 0
    details["special_chars_risk"] = cfg.special_chars_risk if has_special_chars else 0
    details["repeating_chars_risk"] = cfg.repeating_chars_risk if max_repeat >= 5 else 0
    details["max_char_repeat"] = max_repeat

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
