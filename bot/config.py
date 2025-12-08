import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
LOGS_DIR = BASE_DIR / 'logs'
DB_PATH = DATA_DIR / 'bot.db'

# Создаём директории если не существуют
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Дефолтные настройки
DEFAULT_THRESHOLD = 10  # вступлений за окно
DEFAULT_TIME_WINDOW = 60  # секунд
DEFAULT_PROTECT_PREMIUM = True
