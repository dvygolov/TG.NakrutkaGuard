#!/usr/bin/env python3
from bot.utils.name_checks import (
    has_latin_or_cyrillic,
    has_exotic_script,
    has_special_chars,
    get_max_char_repeat
)


def test(full_name: str):
    has_normal = has_latin_or_cyrillic(full_name)
    has_exotic = has_exotic_script(full_name)
    has_special = has_special_chars(full_name)
    max_repeat = get_max_char_repeat(full_name)
    
    weird_risk = 10 if not has_normal else 0
    exotic_risk = 25 if has_exotic else 0
    special_risk = 15 if has_special else 0
    repeat_risk = 5 if max_repeat >= 5 else 0
    
    total = weird_risk + exotic_risk + special_risk + repeat_risk
    print(f"{full_name:25} = {total}")


if __name__ == "__main__":
    # Проблемные имена
    test("Jjj>jjjjj አለለህ")
    test("محمد علي")
    test("李明")
    test("🔥🔥�")
    test("User<>123")
    test("aaaaaaa")
    
    # Нормальные имена
    test("John Doe")
    test("Привет Мир")
    test("Alexander")
    test("Иван Петров")
