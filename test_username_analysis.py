#!/usr/bin/env python3
from bot.utils.username_analysis import username_randomness


def test(username: str):
    result = username_randomness(username, threshold=0.60)
    print(f"{username:20} = {result.score:.2f}")


if __name__ == "__main__":
    # Боты из реальных логов
    test("Mpib3SFLNYzEzyV")
    test("YAdBIOHobLc91Vp")
    test("biAEQOKoOGf")
    test("AXhRLq")
    
    # Типичные боты
    test("user12345")
    test("qwerty777")
    test("bot_user999")
    test("abc123xyz")
    test("JoHnDoE123")
    test("aaaabbbb1111")
    
    # Средний риск
    test("AlexPro")
    test("Mike_2024")
    test("john99")
    test("Rv003_022")
    test("Jftjfhf")
    
    # Нормальные
    test("alexander")
    test("mike_pro")
    test("developer")
    test("coolguy")
