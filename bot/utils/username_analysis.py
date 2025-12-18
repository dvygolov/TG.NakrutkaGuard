from collections import Counter
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class UsernameRandomnessResult:
    score: float              # 0..1, выше = более "рандомный"
    is_randomish: bool        # score >= threshold (порог задаёте снаружи)
    features: Dict[str, Any]  # диагностические метрики


_VOWELS = set("aeiou")


def _cls(ch: str, underscore_as_own: bool) -> str:
    """Класс символа: D=digit, U=upper, L=lower, _=underscore, O=other"""
    if ch.isdigit():
        return "D"
    if ch.isalpha():
        return "U" if ch.isupper() else "L"
    if underscore_as_own and ch == "_":
        return "_"
    return "O"


def _transition_rate(s: str, underscore_as_own: bool) -> float:
    """
    Доля переходов между классами символов.
    0.0 = все одного класса, 1.0 = каждый символ меняет класс.
    """
    if len(s) <= 1:
        return 0.0
    prev = _cls(s[0], underscore_as_own)
    transitions = 0
    for ch in s[1:]:
        cur = _cls(ch, underscore_as_own)
        if cur != prev:
            transitions += 1
        prev = cur
    return transitions / (len(s) - 1)


def _max_same_run(s: str) -> int:
    """Максимальная длина подряд одинаковых символов."""
    if not s:
        return 0
    best = 1
    cur = 1
    low = s.lower()
    for i in range(1, len(low)):
        if low[i] == low[i - 1]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def _dominant_char_ratio(s: str) -> float:
    """Доля самого частого символа (чем больше, тем меньше "рандом")."""
    if not s:
        return 0.0
    c = Counter(s.lower())
    return max(c.values()) / len(s)


def _vowel_ratio(s: str) -> float:
    """Доля гласных среди букв (если букв нет — 0)."""
    letters = [ch.lower() for ch in s if ch.isalpha()]
    if not letters:
        return 0.0
    v = sum(ch in _VOWELS for ch in letters)
    return v / len(letters)


def username_randomness(
    username: Optional[str],
    threshold: float = 0.70,
    underscore_as_own: bool = False
) -> UsernameRandomnessResult:
    """
    Упрощённый скорер "рандомности" для username.
    Признаки:
      - transition_rate: смены lower/upper/digit (и _, опционально)
      - vowel_ratio: низкая доля гласных повышает score
      - repeats: повторы снижают score (т.к. это скорее "паттерн", чем равномерный рандом)
      - dominant_char_ratio: высокая концентрация снижает score

    score 0..1: выше = более "рандомно".
    threshold — порог, по которому выставляется is_randomish.
    """
    if not username:
        return UsernameRandomnessResult(
            score=0.0,
            is_randomish=False,
            features={"reason": "empty_or_none"}
        )

    s = username.strip()
    n = len(s)
    if n == 0:
        return UsernameRandomnessResult(
            score=0.0,
            is_randomish=False,
            features={"reason": "empty"}
        )

    tr = _transition_rate(s, underscore_as_own)  # 0..1
    vr = _vowel_ratio(s)                         # 0..1
    max_run = _max_same_run(s)                   # 1..n
    dom = _dominant_char_ratio(s)                # 1/n..1

    # 1) Смена классов — ключевой драйвер "рандома"
    # Усиливаем эффект степенью: низкие значения ещё ниже, высокие ещё выше.
    tr_component = tr ** 0.65

    # 2) Гласные: "рандомный" ник часто с малым числом гласных.
    # Преобразуем в "нехватку гласных": 1 - vr
    # И добавим мягкий порог: если vr > 0.35, снижаем рандомность сильнее.
    vowel_lack = 1.0 - vr
    if vr > 0.35:
        vowel_lack *= 0.75
    vowel_component = min(max(vowel_lack, 0.0), 1.0)

    # 3) Повторы: длинные повторы и высокая доминация символа — это скорее паттерн.
    # Поэтому это "штрафы" (penalty), которые вычитаются.
    # max_run >= 4 — ощутимый штраф, >=6 — сильный.
    if max_run <= 2:
        repeat_penalty = 0.0
    elif max_run == 3:
        repeat_penalty = 0.10
    elif max_run == 4:
        repeat_penalty = 0.20
    elif max_run == 5:
        repeat_penalty = 0.30
    else:
        repeat_penalty = 0.45

    # Доминирующий символ: если > 0.25, это уже не очень "равномерно"
    dom_penalty = 0.0
    if dom > 0.35:
        dom_penalty = 0.25
    elif dom > 0.28:
        dom_penalty = 0.18
    elif dom > 0.22:
        dom_penalty = 0.10

    # 4) Итоговый score: только нужные признаки.
    # Весами можно управлять под ваши данные.
    score = 0.0
    score += 0.60 * tr_component
    score += 0.40 * vowel_component
    score -= repeat_penalty
    score -= dom_penalty

    # 5) Нормализация по длине: слишком короткие строки трудно уверенно оценивать.
    if n <= 6:
        score *= 0.75
    elif n <= 9:
        score *= 0.90

    score = max(0.0, min(score, 1.0))

    return UsernameRandomnessResult(
        score=score,
        is_randomish=(score >= threshold),
        features={
            "len": n,
            "transition_rate": round(tr, 3),
            "vowel_ratio": round(vr, 3),
            "max_same_run": max_run,
            "dominant_char_ratio": round(dom, 3),
            "repeat_penalty": repeat_penalty,
            "dominant_penalty": dom_penalty,
        },
    )
