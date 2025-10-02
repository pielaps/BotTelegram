import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Конфигурация приложения"""
    
    # Telegram Bot API
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # Telegram Client API (для получения сообщений из каналов)
    API_ID = os.getenv('API_ID')
    API_HASH = os.getenv('API_HASH')
    PHONE = os.getenv('PHONE')
    
    # OpenAI API для саммаризации
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'XXXXXXXXXXсюдавставитьключXXXXXXXX')
    OPENAI_MODEL = "gpt-4o-mini"  # Cost-effective model for summaries
    
    # Настройки по умолчанию
    DEFAULT_POST_LIMIT = 10
    MAX_POST_LIMIT = 100
    MESSAGE_DELAY = 0.5  # Задержка между отправкой сообщений (секунды)
    
    # Настройки батчевой саммаризации
    SUMMARY_BATCH_SIZE = 10  # Максимальное количество постов в одном батче
    BATCH_DELAY = 1.0  # Задержка между обработкой батчей (секунды)
    MAX_CONCURRENT_REQUESTS = 6  # Максимальное количество одновременных запросов к OpenAI
    
    @classmethod
    def validate(cls) -> bool:
        """Проверка наличия всех необходимых переменных окружения"""
        required_vars = [cls.BOT_TOKEN, cls.API_ID, cls.API_HASH, cls.PHONE]
        return all(var is not None and str(var).strip() for var in required_vars)
    
    @classmethod
    def get_missing_vars(cls) -> list:
        """Получение списка отсутствующих переменных"""
        missing = []
        if not cls.BOT_TOKEN:
            missing.append('BOT_TOKEN')
        if not cls.API_ID:
            missing.append('API_ID')
        if not cls.API_HASH:
            missing.append('API_HASH')
        if not cls.PHONE:
            missing.append('PHONE')
        return missing 