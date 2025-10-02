#!/usr/bin/env python3
"""
Быстрый тест сканирования каналов для рассылки
"""

import asyncio
import logging
from datetime import datetime, timedelta
from newsletter_service import NewsletterService
from config import Config
from channel_monitor import ChannelMonitor

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def quick_scan_test():
    """Быстрый тест сканирования"""
    try:
        # Проверяем конфигурацию
        if not Config.validate():
            missing_vars = Config.get_missing_vars()
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing_vars)}")
        
        # Создаем мок-бот для тестирования
        class MockBot:
            async def send_message(self, chat_id, text, parse_mode=None):
                logger.info(f"📤 Отправка сообщения пользователю {chat_id}")
                logger.info(f"📝 Текст: {text[:200]}...")
        
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
        
        # Тестируем подписку пользователя
        test_user_id = 123456789
        newsletter_service.subscribe_user(test_user_id)
        logger.info(f"✅ Пользователь {test_user_id} подписан")
        
        # Быстрое сканирование
        logger.info("🔍 Начинаем быстрое сканирование каналов...")
        start_time = datetime.now()
        
        found_posts = await newsletter_service.scan_channels_for_posts()
        
        end_time = datetime.now()
        scan_duration = (end_time - start_time).total_seconds()
        
        logger.info(f"⏱️ Сканирование завершено за {scan_duration:.2f} секунд")
        
        if found_posts:
            logger.info(f"✅ Найдено {len(found_posts)} постов с целевыми тегами:")
            for i, post in enumerate(found_posts, 1):
                logger.info(f"  {i}. Канал: @{post['channel_name']}, Тег: {post['tag']}")
                logger.info(f"     Текст: {post['text'][:100]}...")
            
            # Тестируем отправку рассылки
            logger.info("📤 Тестируем отправку рассылки...")
            await newsletter_service.send_newsletter_to_users(found_posts)
        else:
            logger.info("ℹ️ Постов с целевыми тегами не найдено")
        
        # Закрываем соединение
        await channel_monitor.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании: {e}")

if __name__ == "__main__":
    asyncio.run(quick_scan_test()) 