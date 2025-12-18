"""
Модуль для проверки символов в именах пользователей.
Вынесены регулярные выражения и функции проверки для избежания дублирования кода.
"""
import re
from typing import Tuple


# Регулярные выражения для проверки символов
NAME_HAS_LAT_CYR_RE = re.compile(r"[A-Za-zА-Яа-я]")

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

# Специальные/подозрительные символы
NAME_SPECIAL_CHARS_RE = re.compile(r"[<>«»@#$%^&*+=\[\]{}|\\`~]")


def has_latin_or_cyrillic(full_name: str) -> bool:
    """Проверяет наличие латиницы или кириллицы в имени."""
    return bool(NAME_HAS_LAT_CYR_RE.search(full_name))


def has_exotic_script(full_name: str) -> bool:
    """Проверяет наличие экзотических письменностей (арабская, CJK, эфиопская и т.д.)."""
    return bool(NAME_EXOTIC_SCRIPT_RE.search(full_name))


def has_special_chars(full_name: str) -> bool:
    """Проверяет наличие специальных символов."""
    return bool(NAME_SPECIAL_CHARS_RE.search(full_name))


def get_max_char_repeat(full_name: str) -> int:
    """
    Находит максимальное количество повторов одного символа подряд.
    Пример: "jjjjj" -> 5, "ааааа" -> 5
    """
    if not full_name:
        return 0
    max_repeat = 1
    current_repeat = 1
    prev_char = full_name[0]
    
    for ch in full_name[1:]:
        if ch == prev_char:
            current_repeat += 1
            max_repeat = max(max_repeat, current_repeat)
        else:
            current_repeat = 1
            prev_char = ch
    
    return max_repeat


def analyze_name(full_name: str) -> Tuple[bool, bool, bool, int]:
    """
    Анализирует имя пользователя на подозрительные признаки.
    
    Returns:
        Tuple[has_normal, has_exotic, has_special, max_repeat]:
        - has_normal: есть ли латиница/кириллица
        - has_exotic: есть ли экзотические письменности
        - has_special: есть ли специальные символы
        - max_repeat: максимальное количество повторов символа
    """
    return (
        has_latin_or_cyrillic(full_name),
        has_exotic_script(full_name),
        has_special_chars(full_name),
        get_max_char_repeat(full_name)
    )
