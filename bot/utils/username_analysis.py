import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class UsernameRandomnessResult:
    score: float              # 0..1, выше = более "рандомный"
    is_randomish: bool        # score >= threshold (порог задаёте снаружи)
    features: Dict[str, Any]  # диагностические метрики


_ALNUM_UND_RE = re.compile(r"^[A-Za-z0-9_]+$")  # типичный телеграм-алфавит
_VOWELS = set("aeiou")
_COMMON_BIGRAMS = {
    # небольшой "якорный" набор частых биграмм в английских словах
    "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es", "or", "te", "of"
}
_COMMON_WORD_FRAGS = {
    # короткие фрагменты/морфемы, которые часто встречаются в осмысленных никах
    "alex", "max", "john", "mike", "anna", "kate", "nick", "pro", "boss", "team", "shop", "bet", "win"
}


def _shannon_entropy(s: str) -> float:
    """
    Энтропия Шеннона (бит/символ). Для равномерных строк растёт.
    """
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    ent = 0.0
    for c in counts.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def _char_type_run_count(s: str) -> int:
    """
    Кол-во смен "типа" символов: letter/digit/underscore/other.
    У "a1b2c3" будет много смен.
    """
    def t(ch: str) -> str:
        if ch.isalpha():
            return "L"
        if ch.isdigit():
            return "D"
        if ch == "_":
            return "_"
        return "O"

    if not s:
        return 0
    runs = 1
    prev = t(s[0])
    for ch in s[1:]:
        cur = t(ch)
        if cur != prev:
            runs += 1
            prev = cur
    return runs


def _has_common_patterns(s: str) -> bool:
    low = s.lower()
    if any(frag in low for frag in _COMMON_WORD_FRAGS):
        return True
    # биграммы
    bigrams = {low[i:i+2] for i in range(len(low) - 1)}
    return len(bigrams & _COMMON_BIGRAMS) >= 1


def username_randomness(
    username: Optional[str],
    threshold: float = 0.70
) -> UsernameRandomnessResult:
    """
    Оценивает, похож ли username на рандомный набор латиницы/цифр.
    Возвращает score 0..1 (чем выше, тем подозрительнее).

    threshold — порог, по которому выставляется is_randomish.
    """
    if not username:
        return UsernameRandomnessResult(
            score=0.0,
            is_randomish=False,
            features={"reason": "empty_or_none"}
        )

    s = username.strip()
    low = s.lower()
    n = len(s)

    # Базовые доли
    letters = sum(ch.isalpha() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    underscores = s.count("_")
    others = n - letters - digits - underscores

    frac_digits = digits / n
    frac_letters = letters / n
    frac_other = others / n

    # Сигналы "рандома"
    ent = _shannon_entropy(low)              # 0..~5
    ent_norm = min(ent / 4.2, 1.0)           # грубая нормализация под a-z0-9_
    runs = _char_type_run_count(s)
    runs_norm = min((runs - 1) / max(n - 1, 1), 1.0)  # доля смен типа

    # Вокалы: у "словоподобных" никнеймов обычно есть гласные
    vowel_cnt = sum((ch in _VOWELS) for ch in low if "a" <= ch <= "z")
    vowel_ratio = vowel_cnt / max(letters, 1) if letters else 0.0
    low_vowels = 1.0 if (letters >= 5 and vowel_ratio < 0.20) else 0.0

    # Повторы / паттерны: 111, aaaa, ababab
    max_run_same = 1
    cur_run = 1
    for i in range(1, n):
        if low[i] == low[i-1]:
            cur_run += 1
            max_run_same = max(max_run_same, cur_run)
        else:
            cur_run = 1
    repeated_chars_penalty = 1.0 if max_run_same >= 4 else 0.0  # часто у ботов бывает "xxxx" или "1111"

    # "Словоподобность" (смягчаем скор, если есть признаки осмысленного ника)
    has_common = _has_common_patterns(s)
    common_bonus = 0.15 if has_common else 0.0

    # Telegram username обычно a-z0-9_ (без других символов) — если "другие" есть, это само по себе подозрительно,
    # но это уже не "рандомный алнум", поэтому даём отдельный флаг.
    is_alnum_und = bool(_ALNUM_UND_RE.match(s))

    # Логика скоринга: взвешенная сумма сигналов
    # Основные драйверы: много цифр, высокая энтропия, много смен типов, мало гласных.
    score = 0.0
    score += 0.30 * ent_norm
    score += 0.25 * min(frac_digits / 0.6, 1.0)     # 0..1, если цифр >=60% => 1
    score += 0.20 * runs_norm
    score += 0.15 * low_vowels
    score += 0.10 * repeated_chars_penalty

    # Штраф за "другие символы" (не underscore/латиница/цифры)
    # Это больше про общий риск, но пусть поднимет скор.
    score += 0.25 * min(frac_other / 0.2, 1.0)

    # Смягчение, если ник похож на "человеческий"
    score = max(0.0, score - common_bonus)

    # Короткие имена не пытаемся "сильно банить" — слишком много FP.
    if n <= 5:
        score *= 0.65

    score = max(0.0, min(score, 1.0))

    features = {
        "len": n,
        "frac_digits": round(frac_digits, 3),
        "frac_letters": round(frac_letters, 3),
        "frac_other": round(frac_other, 3),
        "entropy": round(ent, 3),
        "entropy_norm": round(ent_norm, 3),
        "type_runs": runs,
        "type_runs_norm": round(runs_norm, 3),
        "vowel_ratio": round(vowel_ratio, 3),
        "low_vowels_flag": bool(low_vowels),
        "max_same_char_run": max_run_same,
        "repeated_chars_flag": bool(repeated_chars_penalty),
        "has_common_patterns": has_common,
        "is_alnum_underscore": is_alnum_und,
    }

    return UsernameRandomnessResult(
        score=score,
        is_randomish=(score >= threshold),
        features=features
    )
