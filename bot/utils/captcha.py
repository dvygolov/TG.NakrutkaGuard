import random
from typing import Tuple, List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class CaptchaGenerator:
    """Генератор математических капч с эмодзи"""
    
    # Эмодзи-цифры
    DIGIT_EMOJIS = {
        0: "0️⃣",
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
    }
    
    @staticmethod
    def generate() -> Tuple[str, str, InlineKeyboardMarkup]:
        """
        Генерирует капчу
        
        Returns:
            (текст_задачи, правильный_ответ, клавиатура)
        """
        # Генерируем простую математическую задачу
        operation = random.choice(['+', '-', '*', '//'])
        
        if operation == '+':
            num1 = random.randint(1, 5)
            num2 = random.randint(1, 5)
            result = num1 + num2
            
            question = f"Сколько будет {CaptchaGenerator.DIGIT_EMOJIS[num1]} + {CaptchaGenerator.DIGIT_EMOJIS[num2]} ?"
        
        elif operation == '-':
            num1 = random.randint(5, 9)
            num2 = random.randint(1, num1 - 1)
            result = num1 - num2
            
            question = f"Сколько будет {CaptchaGenerator.DIGIT_EMOJIS[num1]} - {CaptchaGenerator.DIGIT_EMOJIS[num2]} ?"
        
        elif operation == '*':
            num1 = random.randint(2, 5)
            num2 = random.randint(2, 5)
            result = num1 * num2
            
            question = f"Сколько будет {CaptchaGenerator.DIGIT_EMOJIS[num1]} × {CaptchaGenerator.DIGIT_EMOJIS[num2]} ?"
        
        else:  # '//'
            # Генерируем целочисленное деление с результатом 1-9
            result = random.randint(1, 9)
            divisor = random.randint(2, 9)
            num1 = result * divisor
            
            # Форматируем делимое (может быть > 9)
            num1_str = str(num1)
            if len(num1_str) == 1:
                num1_display = CaptchaGenerator.DIGIT_EMOJIS[int(num1_str)]
            else:
                # Двузначное число - показываем каждую цифру
                num1_display = ''.join(CaptchaGenerator.DIGIT_EMOJIS[int(d)] for d in num1_str)
            
            question = f"Сколько будет {num1_display} ÷ {CaptchaGenerator.DIGIT_EMOJIS[divisor]} ?"
        
        # Генерируем варианты ответов
        correct_answer = str(result)
        wrong_answers = CaptchaGenerator._generate_wrong_answers(result)
        
        # Миксуем ответы
        all_answers = [correct_answer] + wrong_answers
        random.shuffle(all_answers)
        
        # Создаём клавиатуру
        keyboard = CaptchaGenerator._create_keyboard(all_answers, correct_answer)
        
        return question, correct_answer, keyboard
    
    @staticmethod
    def _generate_wrong_answers(correct: int, count: int = 3) -> List[str]:
        """Генерирует неправильные ответы близкие к правильному"""
        wrong = set()
        
        while len(wrong) < count:
            # Генерируем близкие числа
            offset = random.choice([-2, -1, 1, 2, 3])
            candidate = correct + offset
            
            # Не используем отрицательные числа и правильный ответ
            if candidate > 0 and candidate != correct:
                wrong.add(str(candidate))
        
        return list(wrong)
    
    @staticmethod
    def _create_keyboard(answers: List[str], correct_answer: str) -> InlineKeyboardMarkup:
        """Создаёт inline клавиатуру с ответами"""
        buttons = []
        row = []
        
        for i, answer in enumerate(answers):
            # callback_data формат: captcha:{answer}
            row.append(InlineKeyboardButton(
                text=answer,
                callback_data=f"captcha:{answer}"
            ))
            
            # По 2 кнопки в ряд
            if len(row) == 2:
                buttons.append(row)
                row = []
        
        # Добавляем оставшиеся кнопки
        if row:
            buttons.append(row)
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)


# Глобальный экземпляр
captcha_gen = CaptchaGenerator()
