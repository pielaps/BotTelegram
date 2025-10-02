#!/usr/bin/env python3
"""
Тестовый скрипт для проверки сервиса рассылки
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

async def test_newsletter_service():
    """Тестирование сервиса рассылки"""
    try:
        # Проверяем конфигурацию
        if not Config.validate():
            missing_vars = Config.get_missing_vars()
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing_vars)}")
        
        # Создаем мок-бот для тестирования
        class MockBot:
            async def send_message(self, chat_id, text, parse_mode=None):
                logger.info(f"Отправка сообщения пользователю {chat_id}: {text[:100]}...")
        
        # Инициализируем компоненты
        channel_monitor = ChannelMonitor(
            int(Config.API_ID), 
            Config.API_HASH, 
            Config.PHONE
        )
        
        mock_bot = MockBot()
        newsletter_service = NewsletterService(mock_bot, channel_monitor)
        
        # Тестируем подписку пользователей
        test_user_id = 123456789
        newsletter_service.subscribe_user(test_user_id)
        logger.info(f"Пользователь {test_user_id} подписан: {newsletter_service.is_user_subscribed(test_user_id)}")
        
        # Тестируем сканирование каналов
        logger.info("Начинаем тестовое сканирование каналов...")
        found_posts = await newsletter_service.scan_channels_for_posts()
        
        if found_posts:
            logger.info(f"Найдено {len(found_posts)} постов с целевыми тегами:")
            for post in found_posts:
                logger.info(f"- Канал: {post['channel_name']}, Тег: {post['tag']}")
            
            # Тестируем отправку рассылки
            await newsletter_service.send_newsletter_to_users(found_posts)
        else:
            logger.info("Постов с целевыми тегами не найдено")
        
        # Тестируем отписку
        newsletter_service.unsubscribe_user(test_user_id)
        logger.info(f"Пользователь {test_user_id} отписан: {not newsletter_service.is_user_subscribed(test_user_id)}")
        
    except Exception as e:
        logger.error(f"Ошибка при тестировании: {e}")

if __name__ == "__main__":
    asyncio.run(test_newsletter_service()) 