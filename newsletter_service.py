import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
import re

from telegram import Bot
from telegram.ext import Application

from config import Config
from channel_monitor import ChannelMonitor

logger = logging.getLogger(__name__)

class NewsletterService:
    """Сервис для рассылки постов с определенными тегами"""
    
    def __init__(self, bot: Bot, channel_monitor: ChannelMonitor):
        self.bot = bot
        self.channel_monitor = channel_monitor
        self.subscribed_users: Set[int] = set()
        self.subscriber_times: Dict[int, int] = {}  # user_id -> час рассылки (9-23)
        self.subscribers_file = "newsletter_subscribers.json"
        self.target_tags = [
            "налоги",
            "внж",
            "наследники",
            "комплаенс",
            "израильские банки",
            "банки",
            "международные банки",
            "разблокировка",
            "активы",
            "капитал",
            "перевод капитала",
            "открытие счета",
            "инвестиции",
            "недвижимость",
            "благосостояние"
        ]
        
        # Кеш для результатов сканирования
        self.daily_posts_cache: List[Dict] = []
        self.last_scan_date: Optional[str] = None
        
        # Отслеживание отправленных рассылок
        self.sent_today: Set[int] = set()  # user_id тех, кому уже отправили сегодня
        self.standard_channels = [
            'moshkovic_law', 
            'movingtoIsrael',
            'gervits_eli',
            'pravo_israel',
            'elinacht',
            'Taxes_Israel',
            'myadvokat_il',
            'novikovalaw',
            'ENRLaw',
            'yadlolim',
            'israel_assistance',
            'ftladvisers'
        ]
        
        # Загружаем подписчиков из файла при инициализации
        self.load_subscribers()
    
    def save_subscribers(self):
        """Сохранить список подписчиков в файл"""
        try:
            # Новый формат: словарь с настройками для каждого пользователя
            subscriber_data = {}
            for user_id in self.subscribed_users:
                subscriber_data[str(user_id)] = {
                    "newsletter_time": self.subscriber_times.get(user_id, 12)  # Дефолт 12:00
                }
            
            with open(self.subscribers_file, 'w', encoding='utf-8') as f:
                json.dump(subscriber_data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Список подписчиков сохранен в {self.subscribers_file}")
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении подписчиков: {e}")
    
    def load_subscribers(self):
        """Загрузить список подписчиков из файла"""
        try:
            if os.path.exists(self.subscribers_file):
                with open(self.subscribers_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Поддерживаем старый формат (просто список ID)
                if isinstance(data, list):
                    self.subscribed_users = set(data)
                    # Устанавливаем дефолтное время для всех
                    self.subscriber_times = {user_id: 12 for user_id in self.subscribed_users}
                    logger.info(f"📂 Загружено {len(self.subscribed_users)} подписчиков из старого формата")
                    # Сохраняем в новом формате
                    self.save_subscribers()
                # Новый формат (словарь с настройками)
                elif isinstance(data, dict):
                    self.subscribed_users = set()
                    self.subscriber_times = {}
                    for user_id_str, settings in data.items():
                        user_id = int(user_id_str)
                        self.subscribed_users.add(user_id)
                        self.subscriber_times[user_id] = settings.get('newsletter_time', 12)
                    logger.info(f"📂 Загружено {len(self.subscribed_users)} подписчиков из {self.subscribers_file}")
                    if self.subscribed_users:
                        logger.info(f"👥 Подписчики: {list(self.subscribed_users)}")
                else:
                    logger.warning(f"⚠️ Неверный формат файла {self.subscribers_file}")
            else:
                logger.info(f"📂 Файл {self.subscribers_file} не найден, начинаем с пустого списка")
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке подписчиков: {e}")
            self.subscribed_users = set()  # Fallback к пустому списку
            self.subscriber_times = {}
        
    def subscribe_user(self, user_id: int) -> bool:
        """Подписать пользователя на рассылку"""
        if user_id not in self.subscribed_users:
            self.subscribed_users.add(user_id)
            # Устанавливаем дефолтное время рассылки (12:00)
            if user_id not in self.subscriber_times:
                self.subscriber_times[user_id] = 12
            self.save_subscribers()  # Сохраняем изменения в файл
            logger.info(f"Пользователь {user_id} подписан на рассылку")
            return True
        return False
    
    def unsubscribe_user(self, user_id: int) -> bool:
        """Отписать пользователя от рассылки"""
        if user_id in self.subscribed_users:
            self.subscribed_users.remove(user_id)
            # Также удаляем время рассылки
            self.subscriber_times.pop(user_id, None)
            self.save_subscribers()  # Сохраняем изменения в файл
            logger.info(f"Пользователь {user_id} отписан от рассылки")
            return True
        return False
    
    def is_user_subscribed(self, user_id: int) -> bool:
        """Проверить, подписан ли пользователь на рассылку"""
        return user_id in self.subscribed_users
    
    def set_user_newsletter_time(self, user_id: int, hour: int) -> bool:
        """Установить время рассылки для пользователя (9-20 часов)"""
        if user_id in self.subscribed_users and 9 <= hour <= 20:
            self.subscriber_times[user_id] = hour
            self.save_subscribers()
            logger.info(f"Время рассылки для пользователя {user_id} установлено на {hour}:00")
            return True
        return False
    
    def get_user_newsletter_time(self, user_id: int) -> int:
        """Получить время рассылки пользователя"""
        return self.subscriber_times.get(user_id, 12)  # Дефолт 12:00
    
    def get_active_hours(self) -> Set[int]:
        """Получить список часов, на которые подписались пользователи"""
        if not self.subscribed_users:
            return set()
        
        active_hours = set()
        for user_id in self.subscribed_users:
            hour = self.get_user_newsletter_time(user_id)
            if 9 <= hour <= 20:  # Проверяем диапазон
                active_hours.add(hour)
        
        return active_hours
    
    def has_target_tags(self, text: str) -> Optional[str]:
        """Проверить, содержит ли текст целевые теги"""
        if not text:
            return None
            
        text_lower = text.lower()
        for tag in self.target_tags:
            if tag in text_lower:
                return tag
        return None
    
    async def scan_channels_for_posts(self) -> List[Dict]:
        """Сканировать каналы на предмет постов с целевыми тегами за последние 24 часа"""
        found_posts = []
        yesterday = datetime.now() - timedelta(days=1)
        
        # Инициализируем клиент для сканирования
        await self.channel_monitor.initialize()
        
        for channel_name in self.standard_channels:
            try:
                # Получаем посты за последние 24 часа с ограничением
                posts = await self.channel_monitor.get_posts(
                    channels=[channel_name],
                    limit=20,  # Ограничиваем количество постов для проверки
                    start_date=yesterday.date()
                )
                
                if not posts:
                    continue
                
                # Проверяем каждый пост на наличие целевых тегов
                for post in posts:
                    if not post.get('text'):
                        continue
                        
                    found_tag = self.has_target_tags(post['text'])
                    if found_tag:
                        found_posts.append({
                            'channel_name': channel_name,
                            'tag': found_tag,
                            'text': post['text'],
                            'date': post.get('date', datetime.now()),
                            'message_id': post.get('id')
                        })
                        
            except Exception as e:
                logger.error(f"Ошибка при сканировании канала {channel_name}: {e}")
                continue
        
        # Закрываем соединение после сканирования
        await self.channel_monitor.close()
        
        return found_posts
    
    async def get_daily_posts(self) -> List[Dict]:
        """Получить посты за день (с кешированием)"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Если кеш актуален, возвращаем его
        if self.last_scan_date == today and self.daily_posts_cache:
            logger.info(f"📋 Используем кешированные посты: {len(self.daily_posts_cache)} постов")
            return self.daily_posts_cache
        
        # Если кеш устарел или пуст, сканируем заново
        logger.info("🔍 Сканируем каналы для получения актуальных постов...")
        posts = await self.scan_channels_for_posts()
        
        # Обновляем кеш
        self.daily_posts_cache = posts
        self.last_scan_date = today
        
        # Сбрасываем список отправленных рассылок при новом дне
        if self.last_scan_date != today:
            self.sent_today.clear()
        
        logger.info(f"✅ Кеш обновлен: найдено {len(posts)} постов с целевыми тегами")
        return posts
    
    async def send_newsletter_to_users(self, posts: List[Dict]):
        """Отправить рассылку всем подписанным пользователям (используется для принудительной рассылки)"""
        if not posts or not self.subscribed_users:
            logger.info("Нет постов для рассылки или нет подписчиков")
            return
        
        logger.info(f"Отправляем рассылку {len(posts)} постов {len(self.subscribed_users)} подписчикам")
        
        for user_id in self.subscribed_users:
            await self._send_newsletter_to_user(user_id, posts)
    
    async def send_newsletter_to_user_by_time(self, user_id: int, posts: List[Dict]):
        """Отправить рассылку конкретному пользователю (по расписанию)"""
        if user_id in self.sent_today:
            logger.info(f"Пользователю {user_id} рассылка уже отправлена сегодня")
            return
        
        await self._send_newsletter_to_user(user_id, posts)
        self.sent_today.add(user_id)
        logger.info(f"✅ Рассылка отправлена пользователю {user_id} в его персональное время")
    
    async def _send_newsletter_to_user(self, user_id: int, posts: List[Dict]):
        """Приватный метод отправки рассылки одному пользователю"""
        try:
            # Формируем сообщение для пользователя
            user_time = self.get_user_newsletter_time(user_id)
            message_text = f"📢 **Ваша ежедневная рассылка ({user_time:02d}:00):**\n\n"
            
            for post in posts:
                channel_display = f"@{post['channel_name']}" if not post['channel_name'].startswith('@') else post['channel_name']
                message_text += (
                    f"📺 **Канал:** {channel_display}\n"
                    f"🏷️ **Тег:** {post['tag']}\n"
                    f"📝 **Пост:**\n{post['text'][:500]}{'...' if len(post['text']) > 500 else ''}\n"
                    f"{'─' * 40}\n\n"
                )
            
            # Отправляем сообщение пользователю
            await self.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode='Markdown'
            )
            
            # Небольшая задержка между отправкой сообщений
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке рассылки пользователю {user_id}: {e}")
            # Если пользователь заблокировал бота, удаляем его из списка подписчиков
            if "bot was blocked by the user" in str(e).lower():
                self.subscribed_users.discard(user_id)
                self.subscriber_times.pop(user_id, None)
                self.save_subscribers()  # Сохраняем изменения в файл
                logger.info(f"Пользователь {user_id} удален из рассылки (заблокировал бота)")
    
    async def run_daily_scan(self):
        """Запустить ежедневное сканирование каналов (для принудительного сканирования)"""
        logger.info("🚀 Запуск принудительного сканирования каналов для рассылки")
        
        try:
            # Проверяем количество подписчиков
            logger.info(f"📊 Количество подписчиков: {len(self.subscribed_users)}")
            if self.subscribed_users:
                logger.info(f"👥 Подписчики: {list(self.subscribed_users)}")
            
            # Сканируем каналы на предмет постов с тегами
            logger.info("🔍 Начинаем сканирование каналов...")
            found_posts = await self.scan_channels_for_posts()
            
            if found_posts:
                logger.info(f"✅ Найдено {len(found_posts)} постов с целевыми тегами")
                for i, post in enumerate(found_posts, 1):
                    logger.info(f"  {i}. Канал: @{post['channel_name']}, Тег: {post['tag']}")
                
                # Отправляем рассылку всем подписанным пользователям (принудительно)
                await self.send_newsletter_to_users(found_posts)
            else:
                logger.info("ℹ️ Постов с целевыми тегами не найдено")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении ежедневного сканирования: {e}")
            import traceback
            logger.error(f"📋 Детали ошибки: {traceback.format_exc()}")
    
    async def force_scan_now(self):
        """Принудительно запустить сканирование прямо сейчас"""
        logger.info("⚡ Принудительный запуск сканирования")
        await self.run_daily_scan()
    
    async def check_and_send_hourly_newsletters(self):
        """Проверить и отправить рассылки пользователям в их персональное время"""
        current_hour = datetime.now().hour
        logger.info(f"⏰ Проверяем рассылки на {current_hour:02d}:00")
        
        # Получаем актуальные посты (из кеша или сканируем)
        posts = await self.get_daily_posts()
        
        if not posts:
            logger.info("ℹ️ Нет постов для рассылки")
            return
        
        # Находим пользователей, которым нужно отправить рассылку в этот час
        users_to_send = []
        for user_id in self.subscribed_users:
            user_hour = self.get_user_newsletter_time(user_id)
            if user_hour == current_hour and user_id not in self.sent_today:
                users_to_send.append(user_id)
        
        if not users_to_send:
            logger.info(f"ℹ️ Нет пользователей для рассылки в {current_hour:02d}:00")
            return
        
        logger.info(f"📤 Отправляем рассылку {len(users_to_send)} пользователям в {current_hour:02d}:00")
        
        # Отправляем рассылку каждому пользователю
        for user_id in users_to_send:
            await self.send_newsletter_to_user_by_time(user_id, posts)
    
    async def start_daily_scheduler(self):
        """Запустить умный планировщик персональных рассылок"""
        logger.info("🧠 Запущен умный планировщик персональных рассылок")
        
        while True:
            try:
                current_time = datetime.now()
                current_hour = current_time.hour
                
                # Получаем активные часы (только те, на которые подписались пользователи)
                active_hours = self.get_active_hours()
                
                if not active_hours:
                    logger.info("ℹ️ Нет активных подписчиков, ждем до следующего дня")
                    # Ждем до 9:00 следующего дня
                    next_check = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
                    if current_hour >= 9:
                        next_check += timedelta(days=1)
                    wait_seconds = (next_check - current_time).total_seconds()
                    logger.info(f"⏰ Следующая проверка в {next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                    await asyncio.sleep(wait_seconds)
                    continue
                
                # Проверяем, есть ли рассылка в текущий час
                if current_hour in active_hours:
                    logger.info(f"📡 Активный час {current_hour:02d}:00 - проверяем рассылки")
                    await self.check_and_send_hourly_newsletters()
                else:
                    logger.info(f"⏸️ Час {current_hour:02d}:00 неактивен (никто не подписан)")
                
                # Находим следующий активный час
                next_active_hour = self._find_next_active_hour(current_time, active_hours)
                wait_seconds = (next_active_hour - current_time).total_seconds()
                
                logger.info(f"⏰ Следующий активный час: {next_active_hour.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"🕐 Активные часы сегодня: {sorted(active_hours)}")
                
                await asyncio.sleep(wait_seconds)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике: {e}")
                import traceback
                logger.error(f"📋 Детали ошибки: {traceback.format_exc()}")
                await asyncio.sleep(3600)  # Ждем час перед повторной попыткой
    
    def _find_next_active_hour(self, current_time: datetime, active_hours: Set[int]) -> datetime:
        """Найти следующий активный час для рассылки"""
        current_hour = current_time.hour
        
        # Ищем следующий активный час сегодня
        today_active_hours = [h for h in active_hours if h > current_hour and 9 <= h <= 20]
        
        if today_active_hours:
            # Есть активные часы сегодня
            next_hour = min(today_active_hours)
            return current_time.replace(hour=next_hour, minute=0, second=0, microsecond=0)
        else:
            # Нет активных часов сегодня, ищем завтра
            if active_hours:
                next_hour = min(h for h in active_hours if 9 <= h <= 20)
                next_day = current_time + timedelta(days=1)
                return next_day.replace(hour=next_hour, minute=0, second=0, microsecond=0)
            else:
                # Нет активных часов вообще, ждем до 9:00 следующего дня
                next_day = current_time + timedelta(days=1)
                return next_day.replace(hour=9, minute=0, second=0, microsecond=0)