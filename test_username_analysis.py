#!/usr/bin/env python3
"""
Тесты для анализатора рандомности username.

Запуск:
    python test_username_analysis.py
"""

from bot.utils.username_analysis import username_randomness


def test_username(username: str, description: str = ""):
    """Тестирует username и выводит результаты"""
    result = username_randomness(username, threshold=0.70)
    
    print(f"\n{'='*80}")
    print(f"Username: {username}")
    if description:
        print(f"Описание: {description}")
    print(f"{'='*80}")
    print(f"Score: {result.score:.3f} (0..1)")
    print(f"Is Random: {result.is_randomish} (>= 0.70)")
    print(f"Risk Applied (из 10): {int(10 * result.score)}")
    print(f"\nФичи:")
    for key, val in result.features.items():
        print(f"  {key}: {val}")


def run_all_tests():
    """Запускает все тесты"""
    print("="*80)
    print("ТЕСТЫ АНАЛИЗАТОРА РАНДОМНОСТИ USERNAME")
    print("="*80)
    
    print("\n" + "🔴 КАТЕГОРИЯ: Очевидно рандомные (ожидаем score > 0.6)".center(80))
    print("-"*80)
    
    # Примеры из реальных логов
    test_username("Mpib3SFLNYzEzyV", "Реальный бот из логов - много смен регистра")
    test_username("YAdBIOHobLc91Vp", "Реальный бот из логов - смены регистра + цифры")
    test_username("AXhRLq", "Реальный бот из логов - короткий рандом")
    
    # Типичные паттерны ботов
    test_username("user12345", "Классика: префикс + цифры")
    test_username("qwerty777", "Клавиатурная последовательность + цифры")
    test_username("bot_user999", "Префикс bot + цифры")
    test_username("abc123xyz", "Микс букв и цифр")
    test_username("JoHnDoE123", "Рандомный регистр + цифры")
    test_username("xXx_killer_xXx", "Типичный боковой паттерн с xXx")
    test_username("aaaabbbb1111", "Повторяющиеся символы")
    
    print("\n" + "🟡 КАТЕГОРИЯ: Средний риск (ожидаем score 0.3-0.6)".center(80))
    print("-"*80)
    
    test_username("AlexPro", "CapitalCase но осмысленный")
    test_username("Mike_2024", "Имя + год")
    test_username("john99", "Короткое имя + цифры")
    test_username("crypto_trader", "Составное слово")
    
    print("\n" + "🟢 КАТЕГОРИЯ: Нормальные username (ожидаем score < 0.3)".center(80))
    print("-"*80)
    
    test_username("alexander", "Обычное имя")
    test_username("mike_pro", "Имя + слово")
    test_username("john_doe", "Классический placeholder")
    test_username("developer", "Профессия")
    test_username("coolguy", "Прилагательное + существительное")
    test_username("maxpain", "Составное слово")
    test_username("team_leader", "Роль")
    test_username("shopkeeper", "Профессия")
    
    print("\n" + "⚪ КАТЕГОРИЯ: Граничные случаи".center(80))
    print("-"*80)
    
    test_username("a", "Один символ")
    test_username("aa", "Два символа")
    test_username("___", "Только подчеркивания")
    test_username("", "Пустая строка")
    test_username("ALLCAPS", "Все заглавные")
    test_username("alllowercase", "Все строчные")
    test_username("123456", "Только цифры")
    test_username("a1b2c3", "Чередование букв и цифр")
    
    print("\n" + "="*80)
    print("ТЕСТЫ ЗАВЕРШЕНЫ")
    print("="*80)
    print("\nДобавьте свои примеры в функцию run_all_tests() выше!")


if __name__ == "__main__":
    run_all_tests()
