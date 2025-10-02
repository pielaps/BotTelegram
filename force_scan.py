#!/usr/bin/env python3
"""
Принудительный запуск сканирования рассылки
"""

import asyncio
import logging
from newsletter_service import NewsletterService
from config import Config
from channel_monitor import ChannelMonitor

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def force_scan():
    """Принудительный запуск сканирования"""
    try:
        # Проверяем конфигурацию
        if not Config.validate():
            missing_vars = Config.get_missing_vars()
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing_vars)}")
        
        # Создаем мок-бот для тестирования
        class MockBot:
            async def send_message(self, chat_id, text, parse_mode=None):
                logger.info(f"📤 Отправка сообщения пользователю {chat_id}")
                logger.info(f"📝 Текст: {text[:300]}...")
        
        # Инициализируем компоненты
        channel_monitor = ChannelMonitor(
            int(Config.API_ID), 
            Config.API_HASH, 
            Config.PHONE
        )
        
        # Инициализируем клиент
        await channel_monitor.initialize()
        
        mock_bot = MockBot()
        newsletter_service = NewsletterService(mock_bot, channel_monitor)
        
        # Добавляем тестового пользователя
        test_user_id = 438387955  # Ваш ID
        newsletter_service.subscribe_user(test_user_id)
        logger.info(f"✅ Пользователь {test_user_id} подписан")
        
        # Принудительно запускаем сканирование
        logger.info("🚀 Принудительный запуск сканирования...")
        await newsletter_service.force_scan_now()
        
        # Закрываем соединение
        await channel_monitor.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при принудительном сканировании: {e}")
        import traceback
        logger.error(f"📋 Детали ошибки: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(force_scan()) 