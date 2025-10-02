import os
import asyncio
import logging
import re
import threading
from typing import Dict, List, Any
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

from config import Config
from channel_monitor import ChannelMonitor
from summarizer import PostSummarizer
from newsletter_service import NewsletterService

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния пользователя
USER_STATE = {
    'WAITING_CHANNEL': 'waiting_channel',
    'WAITING_MORE_CHANNELS': 'waiting_more_channels', 
    'WAITING_POST_COUNT': 'waiting_post_count',
    'WAITING_DATE': 'waiting_date',
    'WAITING_KEYWORDS': 'waiting_keywords',
    'WAITING_OUTPUT_FORMAT': 'waiting_output_format',
    'EDITING_STANDARD_LIST': 'editing_standard_list',
    'ADDING_TO_STANDARD': 'adding_to_standard',
    'CHOOSING_FILTER_TYPE': 'choosing_filter_type'
}

# Хранилище состояний пользователей
user_sessions: Dict[int, Dict[str, Any]] = {}

class TelegramBot:
    def __init__(self):
        # Проверяем конфигурацию
        if not Config.validate():
            missing_vars = Config.get_missing_vars()
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing_vars)}. Проверьте .env файл")
        
        self.bot_token = Config.BOT_TOKEN
        self.api_id = int(Config.API_ID)
        self.api_hash = Config.API_HASH
        self.phone = Config.PHONE
        
        self.channel_monitor = ChannelMonitor(self.api_id, self.api_hash, self.phone)
        
        # Инициализируем саммаризатор
        self.summarizer = PostSummarizer()
        
        # Инициализируем сервис рассылки (бот будет создан позже)
        self.newsletter_service = None
        
    def extract_channel_name(self, channel_input: str) -> str:
        """Извлекает имя канала из различных форматов ввода"""
        channel_input = channel_input.strip()
        
        # Убираем @ если есть
        if channel_input.startswith('@'):
            return channel_input[1:]
        
        # Извлекаем из ссылки t.me
        t_me_match = re.search(r't\.me/([^/?]+)', channel_input)
        if t_me_match:
            return t_me_match.group(1)
        
        # Извлекаем из полной ссылки https://t.me/
        https_match = re.search(r'https?://t\.me/([^/?]+)', channel_input)
        if https_match:
            return https_match.group(1)
        
        # Если это просто текст без ссылки, возвращаем как есть
        return channel_input
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start - перезапуск бота (очистка сессии)"""
        user_id = update.effective_user.id
        
        # Очищаем сессию пользователя
        if user_id in user_sessions:
            del user_sessions[user_id]
            logger.info(f"Сессия пользователя {user_id} очищена")
        
        await update.message.reply_text("🔄 Сессия очищена! Добро пожаловать!")
        await self.show_main_menu(update, context)
    
    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /scan - принудительный запуск сканирования"""
        user_id = update.effective_user.id
        
        if not self.newsletter_service:
            await update.message.reply_text("❌ Сервис рассылки недоступен")
            return
        
        # Проверяем, подписан ли пользователь
        if not self.newsletter_service.is_user_subscribed(user_id):
            await update.message.reply_text("❌ Вы не подписаны на рассылку. Сначала подпишитесь через главное меню.")
            return
        
        await update.message.reply_text("🔍 Запускаю сканирование каналов...")
        
        try:
            # Принудительно запускаем сканирование
            await self.newsletter_service.force_scan_now()
            await update.message.reply_text("✅ Сканирование завершено! Проверьте, получили ли вы уведомления.")
        except Exception as e:
            logger.error(f"Ошибка при принудительном сканировании: {e}")
            await update.message.reply_text("❌ Произошла ошибка при сканировании. Попробуйте позже.")
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать главное меню с кнопками"""
        user_id = update.effective_user.id
        
        # Проверяем, подписан ли пользователь на рассылку
        is_subscribed = False
        if self.newsletter_service:
            is_subscribed = self.newsletter_service.is_user_subscribed(user_id)
        
        keyboard = [
            [InlineKeyboardButton("🚀 Начать мониторинг каналов", callback_data="start_monitoring")]
        ]
        
        # Добавляем кнопку подписки/отписки в зависимости от статуса
        if is_subscribed:
            keyboard.append([InlineKeyboardButton("📢 Отписаться от рассылки", callback_data="unsubscribe_newsletter")])
        else:
            keyboard.append([InlineKeyboardButton("📢 Подписаться на рассылку", callback_data="subscribe_newsletter")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        main_menu_text = (
            "🤖 **Бот поиска информации из Telegram каналов**\n\n"
            "Что умеет этот бот:\n"
            "📊 Получать последние посты из каналов\n"
            "🔍 Фильтровать посты по ключевым словам\n"
            "📱 Отслежитвать несколько каналов одновременно\n"
            "📢 Рассылка постов с тегами 'скидка' и 'налоги'\n\n"
            "💡 **Доступные команды:** `/menu` `/scan` `/start` `/manual`\n\n"
            "Выберите действие:"
        )
        
        # Проверяем откуда пришел запрос
        if update.message:
            await update.message.reply_text(main_menu_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            try:
                await update.callback_query.edit_message_text(main_menu_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                # Если не удалось отредактировать (например, содержимое идентично), отправляем новое сообщение
                await update.callback_query.message.reply_text(main_menu_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def start_monitoring(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать процесс мониторинга"""
        user_id = update.effective_user.id
        
        # Инициализируем сессию пользователя
        user_sessions[user_id] = {
            'channels': [],
            'post_count': 10,
            'keywords': '',
            'output_format': 'full',
            'state': USER_STATE['WAITING_CHANNEL']
        }
        
        welcome_message = (
            "🚀 **Выбор каналов для мониторинга**\n\n"
            "Выберите способ добавления каналов:"
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 Стандартный список", callback_data="standard_list")],
            [InlineKeyboardButton("✏️ Ввести каналы вручную", callback_data="manual_input")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /menu - показывает главное меню"""
        await self.show_main_menu(update, context)
    
    async def manual_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /manual - показывает инструкцию по использованию"""
        await self.show_help(update, context)
    
    async def newsletter_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /newsletter - настройки времени рассылки"""
        await self.show_newsletter_settings(update, context)
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать справку по использованию бота"""
        help_text = (
            "📖 **Как пользоваться ботом:**\n\n"
            "**Шаг 1: Добавление каналов**\n"
            "• Введите название канала или ссылку на канал (например: `smartgen_israel` или `@telegram`)\n"
            "• Можете добавить несколько каналов подряд\n\n"
            "**Шаг 2: Настройка количества постов**\n"
            "• Укажите сколько последних постов получить (от 1 до 100)\n\n"
            "**Шаг 3: Фильтрация (опционально)**\n"
            "• Введите ключевые слова через запятую для поиска\n"
            "• Или нажмите \"Без фильтрации\"\n\n"
            "**Шаг 4: Выбор формата**\n"
            "• Полные посты - весь текст сообщений\n"
            "• Саммари - краткое содержание с помощью ИИ\n\n"
            "**Доступ к каналам:**\n"
            "• Публичные каналы доступны всем\n"
            "• Для приватных каналов нужно быть участником\n\n"
            "**Примеры каналов для тестирования:**\n"         
            "• `@smartgen_israel` - канал SMARTGEN\n"
            "• `@telegram` - официальный канал Telegram"
        )
        
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    def get_standard_channels(self):
        """Получить стандартный список каналов"""
        return [
            'gervits_eli',
            'pravo_israel',
            'Taxes_Israel',
            'yadlolim',
            'israel_assistance'
        ]
    
    async def show_standard_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать стандартный список каналов"""
        standard_channels = self.get_standard_channels()
        
        # Экранируем подчеркивания для Markdown
        escaped_channels = []
        for ch in standard_channels:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        
        message_text = (
            "📋 **Стандартный список каналов:**\n\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Что хотите сделать?"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Использовать как есть", callback_data="use_standard_list")],
            [InlineKeyboardButton("✏️ Изменить список", callback_data="edit_standard_list")],
            [InlineKeyboardButton("🔙 Назад", callback_data="start_monitoring")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def start_manual_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать ввод каналов вручную"""
        user_id = update.effective_user.id
        
        # Инициализируем сессию пользователя
        user_sessions[user_id] = {
            'channels': [],
            'post_count': 10,
            'keywords': '',
            'output_format': 'full',
            'state': USER_STATE['WAITING_CHANNEL']
        }
        
        message_text = (
            "✏️ **Ввод каналов вручную**\n\n"
            "📢 Введите название, ссылку или @username канала:\n\n"
            "Примеры:\n"
            "• `@smartgen_israel`\n"
            "• `telegram`\n"
    
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="start_monitoring")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def use_standard_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Использовать стандартный список каналов"""
        user_id = update.effective_user.id
        
        # Инициализируем сессию пользователя
        user_sessions[user_id] = {
            'channels': self.get_standard_channels().copy(),
            'post_count': 10,
            'keywords': '',
            'output_format': 'full',
            'state': USER_STATE['WAITING_MORE_CHANNELS']
        }
        
        session = user_sessions[user_id]
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще канал", callback_data="add_more")],
            [InlineKeyboardButton("✅ Продолжить", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Экранируем подчеркивания для Markdown
        escaped_channels = []
        for ch in session['channels']:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        
        message_text = (
            "✅ **Стандартный список добавлен!**\n\n"
            f"📢 Выбранные каналы ({len(session['channels'])}):\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Хотите добавить еще каналы или продолжить?"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def edit_standard_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Редактировать стандартный список"""
        user_id = update.effective_user.id
        
        # Инициализируем сессию с стандартным списком только если её нет
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                'channels': self.get_standard_channels().copy(),
                'post_count': 10,
                'keywords': '',
                'output_format': 'full',
                'state': USER_STATE['EDITING_STANDARD_LIST']
            }
        
        session = user_sessions[user_id]
        # Если каналов нет, заполняем стандартными, но НЕ перезаписываем существующие
        if not session.get('channels'):
            session['channels'] = self.get_standard_channels().copy()
        
        # Устанавливаем правильное состояние
        session['state'] = USER_STATE['EDITING_STANDARD_LIST']
        
        # Экранируем подчеркивания для Markdown
        escaped_channels = []
        for ch in session['channels']:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        
        message_text = (
            "✏️ **Редактирование списка каналов**\n\n"
            f"📢 Текущие каналы ({len(session['channels'])}):\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Выберите действие:"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить канал", callback_data="add_to_standard")],
            [InlineKeyboardButton("➖ Удалить канал", callback_data="remove_from_standard")],
            [InlineKeyboardButton("✅ Готово", callback_data="finish_editing")],
            [InlineKeyboardButton("🔙 Назад", callback_data="standard_list")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def add_channel_to_standard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавить канал в стандартный список"""
        user_id = update.effective_user.id
        session = user_sessions.get(user_id, {})
        session['state'] = USER_STATE['ADDING_TO_STANDARD']
        
        message_text = (
            "➕ **Добавление канала**\n\n"
            "📢 Введите название, ссылку или @username канала для добавления:\n\n"
            "Примеры:\n"
            "• `@smartgen_israel`\n"
            "• `telegram`\n"
        )
        
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к редактированию", callback_data="edit_standard_list")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def remove_channel_from_standard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удалить канал из стандартного списка"""
        user_id = update.effective_user.id
        session = user_sessions.get(user_id, {})
        
        if not session.get('channels'):
            await update.callback_query.answer("Список каналов пуст!")
            return
        
        # Создаем кнопки для каждого канала
        keyboard = []
        for channel in session['channels']:
            keyboard.append([InlineKeyboardButton(f"➖ @{channel}", callback_data=f"remove_{channel}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад к редактированию", callback_data="edit_standard_list")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "➖ **Удаление канала**\n\n"
            "Выберите канал для удаления:"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def ask_filter_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Спрашиваем тип фильтрации постов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        session['state'] = USER_STATE['CHOOSING_FILTER_TYPE']
        
        keyboard = [
            [InlineKeyboardButton("📊 По количеству постов", callback_data="filter_by_count")],
            [InlineKeyboardButton("📅 По дате", callback_data="filter_by_date")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "⚙️ **Выбор типа фильтрации**\n\n"
            "Как вы хотите получить посты?"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def ask_post_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Спрашиваем количество постов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        session['state'] = USER_STATE['WAITING_POST_COUNT']
        session['filter_type'] = 'count'
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "📊 **Количество постов**\n\n"
            "Сколько последних постов показать?\n"
            "Введите число от 1 до 100:"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def ask_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Спрашиваем дату начала"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        session['state'] = USER_STATE['WAITING_DATE']
        session['filter_type'] = 'date'
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "📅 **Фильтрация по дате**\n\n"
            "Введите дату, начиная с которой показать посты.\n\n"
            "**Форматы:**\n"
            "• `ДД.ММ.ГГГГ` (например: 15.06.2024)\n"
            "• `ДД.ММ` (текущий год)\n"
            "• `ДД` (текущий месяц и год)\n\n"
            "Будут показаны все посты с указанной даты до сегодня."
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def finish_editing_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершить редактирование списка и продолжить к настройкам"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        # Переводим в состояние выбора дополнительных каналов
        session['state'] = USER_STATE['WAITING_MORE_CHANNELS']
        
        # Экранируем подчеркивания для Markdown
        escaped_channels = []
        for ch in session['channels']:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще канал", callback_data="add_more")],
            [InlineKeyboardButton("✅ Продолжить", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "✅ **Список каналов готов!**\n\n"
            f"📢 Итоговые каналы ({len(session['channels'])}):\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Хотите добавить еще каналы или продолжить к настройкам?"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def add_popular_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавить стандартные каналы"""
        user_id = update.effective_user.id
        
        # Инициализируем сессию пользователя если её нет
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                'channels': [],
                'post_count': 10,
                'keywords': '',
                'output_format': 'full',
                'state': USER_STATE['WAITING_CHANNEL']
            }
        
        session = user_sessions[user_id]
        
        # Список популярных каналов
        popular_channels = [
            'gervits_eli',
            'pravo_israel',
            'Taxes_Israel',
            'yadlolim',
            'israel_assistance'
        ]
        
        # Добавляем популярные каналы к уже существующим
        for channel in popular_channels:
            if channel not in session['channels']:
                session['channels'].append(channel)
        
        session['state'] = USER_STATE['WAITING_MORE_CHANNELS']
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще канал", callback_data="add_more")],
            [InlineKeyboardButton("✅ Продолжить", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "🚀 **Стандартные каналы добавлены!**\n\n"
            f"📢 Текущие каналы ({len(session['channels'])}):\n"
            f"{chr(10).join(['• @' + ch for ch in session['channels']])}\n\n"
            "Хотите добавить еще каналы или продолжить?"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if user_id not in user_sessions:
            await self.show_main_menu(update, context)
            return
        
        session = user_sessions[user_id]
        state = session['state']
        
        if state == USER_STATE['WAITING_CHANNEL']:
            await self.handle_channel_input(update, context, message_text)
            
        elif state == USER_STATE['WAITING_MORE_CHANNELS']:
            await self.handle_additional_channel(update, context, message_text)
            
        elif state == USER_STATE['WAITING_POST_COUNT']:
            await self.handle_post_count(update, context, message_text)
            
        elif state == USER_STATE['WAITING_KEYWORDS']:
            await self.handle_keywords(update, context, message_text)
            
        elif state == USER_STATE['ADDING_TO_STANDARD']:
            await self.handle_add_to_standard(update, context, message_text)
            
        elif state == USER_STATE['WAITING_DATE']:
            await self.handle_date_input(update, context, message_text)
    
    async def handle_channel_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel):
        """Обработка ввода канала"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        # Извлекаем имя канала из различных форматов
        channel_name = self.extract_channel_name(channel)
        session['channels'].append(channel_name)
        
        await self.show_channels_menu(update, context)
        session['state'] = USER_STATE['WAITING_MORE_CHANNELS']
    
    async def handle_additional_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel):
        """Обработка дополнительных каналов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        # Извлекаем имя канала из различных форматов
        channel_name = self.extract_channel_name(channel)
        session['channels'].append(channel_name)
        
        await self.show_channels_menu(update, context)
    
    async def handle_post_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE, count_text):
        """Обработка количества постов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        try:
            count = int(count_text)
            if count <= 0 or count > 100:
                await update.message.reply_text(
                    "❌ Количество постов должно быть от 1 до 100. Попробуйте еще раз:"
                )
                return
            
            session['post_count'] = count
            session['state'] = USER_STATE['WAITING_KEYWORDS']
            
            keyboard = [
                [InlineKeyboardButton("🚫 Без фильтрации", callback_data="no_filter")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Будет получено {count} последних постов.\n\n"
                "🔍 Введите ключевые слова для фильтрации постов (через запятую) или нажмите кнопку ниже:",
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Пожалуйста, введите число. Сколько постов показать?"
            )
    
    async def handle_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE, keywords):
        """Обработка ключевых слов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        session['keywords'] = keywords.strip()
        await self.ask_output_format(update, context)
    
    async def handle_add_to_standard(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_name):
        """Обработка добавления канала в стандартный список"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        # Извлекаем имя канала из различных форматов
        channel = self.extract_channel_name(channel_name)
        
        if channel in session['channels']:
            await update.message.reply_text(
                f"❌ Канал @{channel} уже добавлен в список!"
            )
            return
        
        session['channels'].append(channel)
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще канал", callback_data="add_to_standard")],
            [InlineKeyboardButton("✅ Готово", callback_data="finish_editing")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Экранируем подчеркивания для Markdown
        escaped_channels = []
        for ch in session['channels']:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        
        escaped_channel_name = channel.replace('_', '\\_')
        
        await update.message.reply_text(
            f"✅ Канал @{escaped_channel_name} добавлен в список!\n\n"
            f"📢 Текущие каналы ({len(session['channels'])}):\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Хотите добавить еще каналы?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_date_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, date_text):
        """Обработка ввода даты"""
        from datetime import datetime, date
        
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        try:
            # Пробуем разные форматы даты
            date_text = date_text.strip()
            today = date.today()
            
            if '.' in date_text:
                parts = date_text.split('.')
                if len(parts) == 3:  # ДД.ММ.ГГГГ
                    day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                elif len(parts) == 2:  # ДД.ММ (текущий год)
                    day, month, year = int(parts[0]), int(parts[1]), today.year
                else:
                    raise ValueError("Неправильный формат даты")
            else:  # ДД (текущий месяц и год)
                day, month, year = int(date_text), today.month, today.year
            
            # Создаем объект даты
            start_date = date(year, month, day)
            
            # Проверяем что дата не в будущем
            if start_date > today:
                await update.message.reply_text(
                    "❌ Дата не может быть в будущем. Попробуйте еще раз:"
                )
                return
            
            # Сохраняем дату в сессии
            session['start_date'] = start_date
            session['state'] = USER_STATE['WAITING_KEYWORDS']
            
            keyboard = [
                [InlineKeyboardButton("🚫 Без фильтрации", callback_data="no_filter")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Будут получены все посты с {start_date.strftime('%d.%m.%Y')} до сегодня.\n\n"
                "🔍 Введите ключевые слова для фильтрации постов (через запятую) или нажмите кнопку ниже:",
                reply_markup=reply_markup
            )
            
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Неправильный формат даты. Используйте:\n"
                "• ДД.ММ.ГГГГ (например: 15.06.2024)\n"
                "• ДД.ММ (например: 15.06)\n"
                "• ДД (например: 15)\n\n"
                "Попробуйте еще раз:"
            )
    
    async def ask_output_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Спрашиваем формат вывода"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        session['state'] = USER_STATE['WAITING_OUTPUT_FORMAT']
        
        keyboard = [
            [InlineKeyboardButton("📄 Полные посты", callback_data="format_full")],
            [InlineKeyboardButton("📝 Саммари", callback_data="format_summary")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        filter_text = f"Фильтр: {session['keywords']}" if session['keywords'] else "Без фильтрации"
        
        # Определяем тип фильтрации постов
        if session.get('filter_type') == 'date':
            posts_info = f"📅 Посты с: {session['start_date'].strftime('%d.%m.%Y')}"
        else:
            posts_info = f"📊 Количество постов: {session['post_count']}"
        
        message_text = (
            f"⚙️ **Настройки:**\n"
            f"📢 Каналы: {', '.join(['@' + ch for ch in session['channels']])}\n"
            f"{posts_info}\n"
            f"🔍 {filter_text}\n\n"
            "Выберите формат вывода:"
        )
        
        # Проверяем откуда пришел вызов - из сообщения или callback
        if update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup)
        else:
            # Если из callback, отправляем новое сообщение
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text,
                reply_markup=reply_markup
            )
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        # Обработчики кнопок, которые не требуют сессии
        if query.data == "main_menu":
            await self.show_main_menu(update, context)
            return
            
        elif query.data == "start_monitoring":
            await self.start_monitoring(update, context)
            return
            

            
        elif query.data == "standard_list":
            await self.show_standard_list(update, context)
            return
            
        elif query.data == "manual_input":
            await self.start_manual_input(update, context)
            return
            
        elif query.data == "edit_standard_list":
            await self.edit_standard_list(update, context)
            return
            
        elif query.data == "use_standard_list":
            await self.use_standard_list(update, context)
            return
            
        elif query.data == "add_to_standard":
            await self.add_channel_to_standard(update, context)
            return
            
        elif query.data == "remove_from_standard":
            await self.remove_channel_from_standard(update, context)
            return
            
        elif query.data == "finish_editing":
            await self.finish_editing_list(update, context)
            return
            
        elif query.data == "filter_by_count":
            await self.ask_post_count(update, context)
            return
            
        elif query.data == "filter_by_date":
            await self.ask_date(update, context)
            return
        
        elif query.data == "remove_channel_menu":
            await self.show_remove_channel_menu(update, context)
            return
        
        elif query.data == "back_to_channels_menu":
            await self.show_channels_menu(update, context)
            return
        
        elif query.data == "subscribe_newsletter":
            await self.handle_subscribe_newsletter(update, context)
            return
        
        elif query.data == "unsubscribe_newsletter":
            await self.handle_unsubscribe_newsletter(update, context)
            return
        
        elif query.data.startswith("set_time_"):
            await self.handle_set_newsletter_time(update, context)
            return
        
        # Для остальных кнопок проверяем наличие сессии
        if user_id not in user_sessions:
            await self.show_main_menu(update, context)
            return
        
        session = user_sessions[user_id]
        
        if query.data == "add_more":
            session = user_sessions[user_id]
            session['state'] = USER_STATE['WAITING_MORE_CHANNELS']
            await query.edit_message_text(
                "📢 Введите название, ссылку или @username следующего канала:"
            )
            
        elif query.data == "continue":
            # Если пользователь в состоянии выбора типа фильтрации, возвращаем к этому шагу
            if session.get('state') == USER_STATE['CHOOSING_FILTER_TYPE']:
                await self.ask_filter_type(update, context)
            else:
                await self.ask_filter_type(update, context)
            
        elif query.data == "no_filter":
            session['keywords'] = ''
            await query.edit_message_text("✅ Фильтрация отключена")
            await self.ask_output_format(update, context)
            
        elif query.data == "format_full":
            session['output_format'] = 'full'
            await query.edit_message_text("⏳ Получаю посты...")
            await self.fetch_and_send_posts(update, context)
            
        elif query.data == "format_summary":
            session['output_format'] = 'summary'
            await query.edit_message_text("⏳ Получаю посты и создаю саммари...")
            await self.fetch_and_send_posts(update, context)
            
        elif query.data.startswith("remove_"):
            channel_to_remove = query.data[7:]
            session = user_sessions.get(user_id, {})
            if channel_to_remove in session.get('channels', []):
                session['channels'].remove(channel_to_remove)
                await query.answer(f"Канал @{channel_to_remove} удален!")
                # Возвращаемся к меню каналов
                await self.show_channels_menu(update, context)
            else:
                await query.answer("Канал не найден!")
        
        elif query.data == "restart":
            # Сбрасываем сессию и начинаем заново (старая кнопка для совместимости)
            user_sessions[user_id] = {
                'channels': [],
                'post_count': 10,
                'keywords': '',
                'output_format': 'full',
                'state': USER_STATE['WAITING_CHANNEL']
            }
            await query.edit_message_text(
                "🔄 Начинаем заново!\n\n"
                "📢 Введите название, ссылку или @username канала, который хотите просмотреть:"
            )
    
    async def fetch_and_send_posts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение и отправка постов"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        
        try:
            # Инициализируем мониторинг каналов если еще не инициализирован
            if self.channel_monitor.client is None:
                await self.channel_monitor.initialize()
            
            # Получаем посты через ChannelMonitor
            # Определяем параметры запроса в зависимости от типа фильтрации
            if session.get('filter_type') == 'date':
                posts = await self.channel_monitor.get_posts(
                    channels=session['channels'],
                    keywords=session['keywords'],
                    start_date=session.get('start_date')
                )
            else:
                posts = await self.channel_monitor.get_posts(
                    channels=session['channels'],
                    limit=session['post_count'],
                    keywords=session['keywords']
                )
            
            if not posts:
                keyboard = [
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text="😔 Посты не найдены или каналы недоступны.\n\n💡 Используйте команду /start для перезапуска",
                    reply_markup=reply_markup
                )
                return
            
            # Проверяем формат вывода
            if session['output_format'] == 'summary':
                # Группируем посты по каналам для подсчета
                channels_posts = {}
                for post in posts:
                    channel = post['channel']
                    if channel not in channels_posts:
                        channels_posts[channel] = []
                    channels_posts[channel].append(post)
                
                # Создаем саммари по батчам
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔄 Найдено {len(posts)} постов из {len(channels_posts)} каналов. Создаю саммари по батчам с помощью ИИ..."
                )
                
                logger.info("Начинаем батчевую саммаризацию постов")
                
                summarizer = PostSummarizer()
                
                # Определяем колбэк для отправки готовых саммари
                async def send_batch_summary(channel_name: str, summary: str):
                    """Отправляет готовый саммари батча пользователю"""
                    # Разбиваем саммари на части по 4000 символов
                    summary_parts = summarizer.split_summary_by_length(summary, 4000)
                    
                    # Отправляем каждую часть
                    for i, part in enumerate(summary_parts, 1):
                        if len(summary_parts) > 1:
                            header = f"📝 Саммари канала @{channel_name} (часть {i}/{len(summary_parts)}):\n\n"
                            message_text = header + part
                        else:
                            message_text = part
                        
                        # Защита от ошибок markdown парсинга
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=message_text,
                                parse_mode='Markdown'
                            )
                        except Exception as parse_error:
                            logger.warning(f"Ошибка парсинга markdown: {parse_error}")
                            # Отправляем без форматирования в случае ошибки
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=message_text,
                                parse_mode=None
                            )
                        
                        # Небольшая пауза между сообщениями
                        await asyncio.sleep(Config.MESSAGE_DELAY)
                
                # Запускаем батчевую саммаризацию
                await summarizer.summarize_posts_in_batches(
                    posts=posts,
                    keywords=session.get('keywords', ''),
                    batch_size=Config.SUMMARY_BATCH_SIZE,
                    send_callback=send_batch_summary
                )
                
                # Отправляем финальное сообщение о завершении
                await context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Все саммари готовы и отправлены!"
                )
            
            else:
                # Отправляем полные посты
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📊 Найдено {len(posts)} постов:"
                )
            
                for i, post in enumerate(posts, 1):
                    message_text = (
                        f"📄 Пост {i}/{len(posts)}\n"
                        f"📢 Канал: @{post['channel']}\n"
                        f"📅 Дата: {post['date'].strftime('%d.%m.%Y %H:%M')}\n"
                        f"👀 Просмотры: {post.get('views', 'N/A')}\n\n"
                        f"{post['text'][:4000]}{'...' if len(post['text']) > 4000 else ''}"
                    )
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                    
                    # Небольшая пауза между сообщениями
                    await asyncio.sleep(Config.MESSAGE_DELAY)
            
            # Показываем кнопки для дальнейших действий
            keyboard = [
                [InlineKeyboardButton("🔄 Начать заново", callback_data="start_monitoring")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Все посты отправлены!",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Ошибка при получении постов: {e}")
            
            keyboard = [
                [InlineKeyboardButton("🔄 Начать заново", callback_data="start_monitoring")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Произошла ошибка при получении постов. Попробуйте позже.",
                reply_markup=reply_markup
            )
    
    async def show_remove_channel_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать меню для удаления канала из текущего списка (ручной/стандартный)"""
        user_id = update.effective_user.id
        session = user_sessions.get(user_id, {})
        if not session.get('channels'):
            await update.callback_query.answer("Список каналов пуст!")
            return
        keyboard = []
        for channel in session['channels']:
            keyboard.append([InlineKeyboardButton(f"➖ @{channel}", callback_data=f"remove_{channel}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_channels_menu")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = (
            "➖ **Удаление канала**\n\n"
            "Выберите канал для удаления из списка анализа:"
        )
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def show_channels_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать меню с текущим списком каналов, возможностью добавить, удалить или продолжить"""
        user_id = update.effective_user.id
        session = user_sessions[user_id]
        escaped_channels = []
        for ch in session['channels']:
            escaped_ch = ch.replace('_', '\\_')
            escaped_channels.append(f"• @{escaped_ch}")
        message_text = (
            "📢 **Текущий список каналов:**\n\n"
            f"{chr(10).join(escaped_channels)}\n\n"
            "Выберите действие:"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще канал", callback_data="add_more")],
            [InlineKeyboardButton("➖ Удалить канал", callback_data="remove_channel_menu")],
            [InlineKeyboardButton("✅ Продолжить", callback_data="continue")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def handle_subscribe_newsletter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик подписки на рассылку"""
        user_id = update.effective_user.id
        
        if not self.newsletter_service:
            await update.callback_query.answer("❌ Сервис рассылки недоступен")
            return
        
        if self.newsletter_service.subscribe_user(user_id):
            await update.callback_query.answer("✅ Вы успешно подписались на рассылку!")
            
            # Показываем обновленное главное меню
            await self.show_main_menu(update, context)
        else:
            await update.callback_query.answer("ℹ️ Вы уже подписаны на рассылку")
    
    async def handle_unsubscribe_newsletter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик отписки от рассылки"""
        user_id = update.effective_user.id
        
        if not self.newsletter_service:
            await update.callback_query.answer("❌ Сервис рассылки недоступен")
            return
        
        if self.newsletter_service.unsubscribe_user(user_id):
            await update.callback_query.answer("✅ Вы успешно отписались от рассылки!")
            
            # Показываем обновленное главное меню
            await self.show_main_menu(update, context)
        else:
            await update.callback_query.answer("ℹ️ Вы не были подписаны на рассылку")
    
    async def show_newsletter_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать настройки времени рассылки"""
        user_id = update.effective_user.id
        
        if not self.newsletter_service:
            await update.message.reply_text("❌ Сервис рассылки недоступен")
            return
        
        if not self.newsletter_service.is_user_subscribed(user_id):
            await update.message.reply_text(
                "❌ Вы не подписаны на рассылку!\n\n"
                "Сначала подпишитесь через главное меню (/menu)"
            )
            return
        
        current_time = self.newsletter_service.get_user_newsletter_time(user_id)
        
        # Создаем кнопки для выбора времени (9-20 часов)
        keyboard = []
        for hour in range(9, 21):
            if hour == current_time:
                button_text = f"✅ {hour:02d}:00"
            else:
                button_text = f"{hour:02d}:00"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_time_{hour}")])
        
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            f"⏰ **Настройки времени рассылки**\n\n"
            f"📍 Текущее время: **{current_time:02d}:00** (израильское время)\n\n"
            f"🕐 Выберите час, в который хотите получать ежедневную рассылку:\n"
            f"(доступны часы с 09:00 до 20:00)"
        )
        
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_set_newsletter_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик установки времени рассылки"""
        user_id = update.effective_user.id
        query = update.callback_query
        
        if not self.newsletter_service:
            await query.answer("❌ Сервис рассылки недоступен")
            return
        
        # Извлекаем час из callback_data
        try:
            hour = int(query.data.split("_")[2])
        except (IndexError, ValueError):
            await query.answer("❌ Ошибка в формате времени")
            return
        
        if self.newsletter_service.set_user_newsletter_time(user_id, hour):
            await query.answer(f"✅ Время рассылки установлено на {hour:02d}:00!")
            
            # Обновляем сообщение с новыми настройками
            await self.show_newsletter_settings_update(update, context)
        else:
            await query.answer("❌ Не удалось установить время. Проверьте подписку.")
    
    async def show_newsletter_settings_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обновить сообщение с настройками времени рассылки"""
        user_id = update.effective_user.id
        current_time = self.newsletter_service.get_user_newsletter_time(user_id)
        
        # Создаем кнопки для выбора времени (9-20 часов)
        keyboard = []
        for hour in range(9, 21):
            if hour == current_time:
                button_text = f"✅ {hour:02d}:00"
            else:
                button_text = f"{hour:02d}:00"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_time_{hour}")])
        
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            f"⏰ **Настройки времени рассылки**\n\n"
            f"📍 Текущее время: **{current_time:02d}:00** (израильское время)\n\n"
            f"🕐 Выберите час, в который хотите получать ежедневную рассылку:\n"
            f"(доступны часы с 09:00 до 20:00)"
        )
        
        try:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    def run(self):
        """Запуск бота"""
        try:
            # Создаем приложение
            application = Application.builder().token(self.bot_token).build()
            
            # Инициализируем сервис рассылки
            self.newsletter_service = NewsletterService(application.bot, self.channel_monitor)
            
            # Настраиваем меню команд бота
            async def setup_bot_commands():
                commands = [
                    BotCommand("menu", "🏠 Показать главное меню"),
                    BotCommand("scan", "📡 Принудительное сканирование каналов"),
                    BotCommand("newsletter", "⏰ Настройки времени рассылки"),
                    BotCommand("start", "🔄 Перезапустить бота (очистить сессию)"),
                    BotCommand("manual", "📖 Инструкция по использованию")
                ]
                await application.bot.set_my_commands(commands)
                logger.info("📋 Меню команд бота настроено")
            
            # Устанавливаем команды при запуске
            application.job_queue.run_once(
                lambda context: asyncio.create_task(setup_bot_commands()),
                when=0.5  # Запускаем через полсекунды
            )
            
            # Добавляем обработчики
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("menu", self.menu_command))
            application.add_handler(CommandHandler("scan", self.scan_command))
            application.add_handler(CommandHandler("newsletter", self.newsletter_command))
            application.add_handler(CommandHandler("manual", self.manual_command))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            application.add_handler(CallbackQueryHandler(self.handle_callback_query))
            
            # Запускаем планировщик рассылки в том же event loop
            async def start_scheduler_with_app():
                await self.newsletter_service.start_daily_scheduler()
            
            # Добавляем задачу планировщика в event loop приложения
            application.job_queue.run_once(
                lambda context: asyncio.create_task(start_scheduler_with_app()),
                when=1  # Запускаем через 1 секунду
            )
            
            # Запускаем бота
            logger.info("🤖 Бот запущен и готов к работе!")
            logger.info("📢 Сервис рассылки активирован")
            application.run_polling()
            
        except Exception as e:
            logger.error(f"Ошибка запуска бота: {e}")
            raise

def main():
    """Главная функция"""
    try:
        bot = TelegramBot()
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"\n❌ Ошибка запуска: {e}")
        print("Проверьте настройки в файле .env")

if __name__ == "__main__":
    main() 