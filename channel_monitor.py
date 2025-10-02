import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from telethon.errors import ChannelPrivateError, UsernameNotOccupiedError, FloodWaitError

logger = logging.getLogger(__name__)

class ChannelMonitor:
    def __init__(self, api_id: int, api_hash: str, phone: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = None
    
    async def initialize(self):
        """Инициализация клиента Telegram"""
        try:
            self.client = TelegramClient('session', self.api_id, self.api_hash)
            await self.client.start(phone=self.phone)
            logger.info("Telethon клиент инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации Telethon: {e}")
            raise
    
    async def get_posts(self, channels: List[str], limit: int = 10, keywords: str = '', start_date=None) -> List[Dict[str, Any]]:
        """
        Получение постов из каналов
        
        Args:
            channels: Список каналов (@username или ID)
            limit: Количество постов на канал (используется только если start_date=None)
            keywords: Ключевые слова для фильтрации (через запятую)
            start_date: Дата начала для фильтрации (datetime.date или None)
            
        Returns:
            Список постов
        """
        if not self.client:
            raise RuntimeError("Клиент не инициализирован")
        
        all_posts = []
        keywords_list = [kw.strip().lower() for kw in keywords.split(',') if kw.strip()] if keywords else []
        
        for channel in channels:
            try:
                posts = await self._get_channel_posts(channel, limit, keywords_list, start_date)
                all_posts.extend(posts)
            except Exception as e:
                logger.error(f"Ошибка получения постов из канала {channel}: {e}")
                continue
        
        # Сортируем по дате (новые первыми)
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Если фильтрация по дате, возвращаем все найденные посты
        # Если по количеству, ограничиваем
        if start_date:
            return all_posts
        else:
            return all_posts[:limit * len(channels)]  # Ограничиваем общее количество
    
    async def _get_channel_posts(self, channel: str, limit: int, keywords: List[str], start_date=None) -> List[Dict[str, Any]]:
        """Получение постов из одного канала"""
        from datetime import datetime, timezone
        
        try:
            # Получаем сущность канала
            entity = await self.client.get_entity(channel)
            
            if not isinstance(entity, (Channel, Chat)):
                logger.warning(f"{channel} не является каналом или группой")
                return []
            
            posts = []
            
            # Если фильтрация по дате, получаем больше сообщений
            # Если по количеству, ограничиваем
            if start_date:
                # Преобразуем date в datetime с началом дня
                start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                messages_limit = 1500  # Получаем много сообщений для фильтрации по дате
            else:
                start_datetime = None
                messages_limit = limit * 3  # Берем больше для фильтрации по ключевым словам
            
            # Получаем сообщения
            async for message in self.client.iter_messages(entity, limit=messages_limit):
                if not message.text:
                    continue
                
                # Фильтрация по дате (если указана)
                if start_date and message.date < start_datetime:
                    break  # Сообщения идут от новых к старым, можно прекратить
                
                # Фильтрация по ключевым словам
                if keywords:
                    message_text_lower = message.text.lower()
                    if not any(keyword in message_text_lower for keyword in keywords):
                        continue
                
                post_data = {
                    'channel': channel,
                    'text': message.text,
                    'date': message.date,
                    'views': message.views,
                    'message_id': message.id,
                    'url': f"https://t.me/{channel}/{message.id}" if hasattr(entity, 'username') and entity.username else None
                }
                
                posts.append(post_data)
                
                # Если фильтрация по количеству, останавливаемся при достижении лимита
                if not start_date and len(posts) >= limit:
                    break
            
            logger.info(f"Получено {len(posts)} постов из канала {channel}")
            return posts
            
        except ChannelPrivateError:
            logger.error(f"Канал {channel} приватный или недоступен")
            return []
        except UsernameNotOccupiedError:
            logger.error(f"Канал {channel} не найден")
            return []
        except FloodWaitError as e:
            logger.warning(f"Превышен лимит запросов, ждем {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении постов из {channel}: {e}")
            return []
    
    async def close(self):
        """Закрытие соединения"""
        if self.client:
            await self.client.disconnect()
            logger.info("Telethon клиент отключен") 