#!/usr/bin/env python3
import re

# Импортируем регулярки из scoring.py
NAME_HAS_LAT_CYR_RE = re.compile(r"[A-Za-zА-Яа-я]")

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

NAME_SPECIAL_CHARS_RE = re.compile(r"[<>«»@#$%^&*+=\[\]{}|\\`~]")


def analyze_name(full_name: str):
    """Анализирует имя по новой логике"""
    has_normal_letters = bool(NAME_HAS_LAT_CYR_RE.search(full_name))
    has_exotic_script = bool(NAME_EXOTIC_SCRIPT_RE.search(full_name))
    has_special_chars = bool(NAME_SPECIAL_CHARS_RE.search(full_name))
    
    # Подсчёт повторяющихся символов
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
    
    # Подсчёт рисков (как в ScoringConfig по умолчанию)
    weird_name_risk = 10 if not has_normal_letters else 0
    exotic_script_risk = 30 if has_exotic_script else 0
    special_chars_risk = 15 if has_special_chars else 0
    repeating_chars_risk = 10 if max_repeat >= 5 else 0
    
    total_name_risk = weird_name_risk + exotic_script_risk + special_chars_risk + repeating_chars_risk
    
    print(f"\n{'='*80}")
    print(f"Имя: {full_name!r}")
    print(f"{'='*80}")
    print(f"✓ Есть латиница/кириллица: {has_normal_letters}")
    print(f"✗ Есть экзотическая письменность: {has_exotic_script}")
    print(f"✗ Есть специальные символы: {has_special_chars}")
    print(f"✗ Макс. повтор символа: {max_repeat}")
    print(f"\nРиски:")
    print(f"  weird_name_risk: {weird_name_risk}")
    print(f"  exotic_script_risk: {exotic_script_risk}")
    print(f"  special_chars_risk: {special_chars_risk}")
    print(f"  repeating_chars_risk: {repeating_chars_risk}")
    print(f"\n🔴 ИТОГО (только за имя): {total_name_risk} баллов")
    return total_name_risk


if __name__ == "__main__":
    print("="*80)
    print("ТЕСТ УСИЛЕННОЙ ДЕТЕКЦИИ СТРАННЫХ ИМЁН")
    print("="*80)
    
    # Проблемный пример от пользователя
    analyze_name("Jjj>jjjjj አለለህ")
    
    # Дополнительные тесты
    analyze_name("John Doe")  # нормальное имя
    analyze_name("محمد علي")  # арабское имя
    analyze_name("李明")  # китайское имя
    analyze_name("aaaaaaa")  # много повторов
    analyze_name("User<>123")  # спецсимволы
    analyze_name("🔥🔥🔥")  # эмодзи (без лат/кир)
    analyze_name("Привет Мир")  # кириллица
