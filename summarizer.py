import asyncio
import logging
from typing import List, Dict, Any, Callable, Optional
from openai import OpenAI
from config import Config

logger = logging.getLogger(__name__)

class PostSummarizer:
    def __init__(self):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.model = Config.OPENAI_MODEL
    
    async def summarize_posts(self, posts: List[Dict[str, Any]], keywords: str = '') -> str:
        """
        Создает структурированное саммари всех постов с группировкой по каналам
        
        Args:
            posts: Список постов для саммаризации
            keywords: Ключевые слова фильтрации (для контекста)
            
        Returns:
            Структурированное саммари в виде строки
        """
        try:
            if not posts:
                return "❌ Нет постов для саммаризации."
            
            # Подготавливаем текст всех постов для OpenAI
            posts_text = self._prepare_all_posts_text(posts)
            
            # Создаем промпт для саммаризации
            prompt = self._create_structured_prompt(posts_text, keywords, len(posts))
            
            # Отправляем запрос к OpenAI
            logger.info(f"Отправляем {len(posts)} постов на структурированную саммаризацию в OpenAI")
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "Ты - эксперт по анализу и саммаризации контента из Telegram каналов. Твоя задача создавать подробные и структурированные саммари на русском языке, группируя посты по каналам. Не используй жирный шрифт или курсив."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=4000,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content.strip()
            logger.info("Структурированная саммаризация завершена успешно")
            
            return summary
            
        except Exception as e:
            logger.error(f"Ошибка при саммаризации: {e}")
            return f"❌ Ошибка при создании саммари: {str(e)}"
    
    def _prepare_all_posts_text(self, posts: List[Dict[str, Any]]) -> str:
        """Подготавливает текст всех постов для отправки в OpenAI с группировкой по каналам"""
        # Группируем посты по каналам
        channels_posts = {}
        for post in posts:
            channel = post['channel']
            if channel not in channels_posts:
                channels_posts[channel] = []
            channels_posts[channel].append(post)
        
        # Сортируем каналы для консистентности
        sorted_channels = sorted(channels_posts.keys())
        
        prepared_text = []
        for channel in sorted_channels:
            channel_posts = channels_posts[channel]
            prepared_text.append(f"📢 КАНАЛ: @{channel}")
            prepared_text.append("=" * 50)
            
            for i, post in enumerate(channel_posts, 1):
                date_str = post['date'].strftime('%d.%m.%Y %H:%M')
                text = post['text'][:3000]  # Ограничиваем длину текста поста
                
                post_text = f"ПОСТ {i}:\nДата: {date_str}\nТекст: {text}\n"
                prepared_text.append(post_text)
            
            prepared_text.append("\n" + "=" * 50 + "\n")
        
        return "\n".join(prepared_text)
    
    def _create_structured_prompt(self, posts_text: str, keywords: str, posts_count: int) -> str:
        """Создает промпт для структурированной саммаризации"""
        keywords_info = f"\nКлючевые слова фильтрации: {keywords}" if keywords else ""
        
        prompt = f"""Проанализируй {posts_count} постов из Telegram каналов и создай подробное структурированное саммари на русском языке.{keywords_info}

ТРЕБОВАНИЯ К САММАРИ:
1. Группируй саммари по каналам, указывая название канала перед каждым блоком
2. Для каждого поста создавай подробное саммари с сохранением всех важных деталей
3. Включи все важные детали, цифры, ссылки, действия из оригинальных постов
4. Сохрани структуру и логику оригинальных постов
5. Не используй жирный шрифт или курсив
6. Не Используй эмодзи для структурирования и разделения
7. Обязательно сохраняй ссылки, номера телефонов, даты, время, и т.д.
8. Делай саммари подробным, минимум 40% от всего текста постов.
9. У тебя нет лимита слов, ты можешь писать столько, сколько нужно.

ФОРМАТ ВЫВОДА:
📢 Канал: @channel_name
📄 Пост 1: [подробное саммари]
📄 Пост 2: [подробное саммари]
...

📢 Канал: @another_channel
📄 Пост 1: [подробное саммари]
...

ПОСТЫ ДЛЯ АНАЛИЗА:
{posts_text}

Создай подробное и структурированное саммари:"""
        
        return prompt
    
    def split_summary_by_length(self, summary: str, max_length: int = 4000) -> List[str]:
        """Разбивает саммари на части по длине, не обрезая слова"""
        if len(summary) <= max_length:
            return [summary]
        
        parts = []
        current_part = ""
        lines = summary.split('\n')
        
        for line in lines:
            # Если добавление этой строки превысит лимит
            if len(current_part) + len(line) + 1 > max_length and current_part:
                parts.append(current_part.strip())
                current_part = line
            else:
                if current_part:
                    current_part += '\n' + line
                else:
                    current_part = line
        
        # Добавляем последнюю часть
        if current_part:
            parts.append(current_part.strip())
        
        return parts

    async def summarize_posts_in_batches(
        self, 
        posts: List[Dict[str, Any]], 
        keywords: str = '',
        batch_size: int = 10,
        send_callback: Optional[Callable[[str, str], Any]] = None
    ) -> List[str]:
        """
        Создает саммари постов по батчам, где каждый батч содержит посты только из одного канала.
        Отправляет готовые саммари через колбэк сразу после обработки каждого батча.
        Ограничивает количество одновременных запросов к OpenAI.
        
        Args:
            posts: Список постов для саммаризации
            keywords: Ключевые слова фильтрации (для контекста)
            batch_size: Максимальное количество постов в одном батче
            send_callback: Функция для отправки готового саммари (channel_name, summary)
            
        Returns:
            Список всех созданных саммари
        """
        try:
            if not posts:
                return ["❌ Нет постов для саммаризации."]
            
            # Группируем посты по каналам
            channels_posts = {}
            for post in posts:
                channel = post['channel']
                if channel not in channels_posts:
                    channels_posts[channel] = []
                channels_posts[channel].append(post)
            
            logger.info(f"Обрабатываем {len(posts)} постов из {len(channels_posts)} каналов по батчам")
            
            # Создаем семафор для ограничения параллельных запросов
            semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_REQUESTS)
            
            # Создаем структуры для упорядоченной отправки
            channel_buffers = {}  # Буферы готовых саммари для каждого канала
            channel_next_batch = {}  # Следующий ожидаемый номер батча для каждого канала
            channel_total_batches = {}  # Общее количество батчей для каждого канала
            channel_locks = {}  # Блокировки для синхронизации отправки
            
            # Собираем все батчи для параллельной обработки
            all_batch_tasks = []
            
            for channel_name, channel_posts in channels_posts.items():
                logger.info(f"Подготавливаем батчи для канала @{channel_name} ({len(channel_posts)} постов)")
                
                # Разбиваем посты канала на батчи
                batches = [
                    channel_posts[i:i + batch_size] 
                    for i in range(0, len(channel_posts), batch_size)
                ]
                
                # Инициализируем структуры для канала
                channel_buffers[channel_name] = {}
                channel_next_batch[channel_name] = 1
                channel_total_batches[channel_name] = len(batches)
                channel_locks[channel_name] = asyncio.Lock()
                
                # Создаем задачи для каждого батча
                for batch_idx, batch_posts in enumerate(batches, 1):
                    task = self._process_batch_with_ordered_sending(
                        semaphore=semaphore,
                        batch_posts=batch_posts,
                        channel_name=channel_name,
                        keywords=keywords,
                        batch_idx=batch_idx,
                        total_batches=len(batches),
                        send_callback=send_callback,
                        channel_buffers=channel_buffers,
                        channel_next_batch=channel_next_batch,
                        channel_total_batches=channel_total_batches,
                        channel_locks=channel_locks
                    )
                    all_batch_tasks.append(task)
            
            logger.info(f"Запускаем параллельную обработку {len(all_batch_tasks)} батчей (макс. {Config.MAX_CONCURRENT_REQUESTS} одновременно)")
            
            # Выполняем все задачи параллельно с ограничением семафора
            results = await asyncio.gather(*all_batch_tasks, return_exceptions=True)
            
            # Обрабатываем результаты
            all_summaries = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Ошибка в батче {i+1}: {result}")
                    all_summaries.append(f"❌ Ошибка в батче {i+1}: {str(result)}")
                elif result:
                    all_summaries.append(result)
            
            logger.info(f"Обработка завершена. Создано {len(all_summaries)} саммари")
            return all_summaries
            
        except Exception as e:
            logger.error(f"Ошибка при саммаризации по батчам: {e}")
            error_msg = f"❌ Ошибка при создании саммари: {str(e)}"
            return [error_msg]
    
    async def _process_batch_with_ordered_sending(
        self,
        semaphore: asyncio.Semaphore,
        batch_posts: List[Dict[str, Any]],
        channel_name: str,
        keywords: str,
        batch_idx: int,
        total_batches: int,
        send_callback: Optional[Callable[[str, str], Any]],
        channel_buffers: Dict[str, Dict[int, str]],
        channel_next_batch: Dict[str, int],
        channel_total_batches: Dict[str, int],
        channel_locks: Dict[str, asyncio.Lock]
    ) -> str:
        """
        Обрабатывает один батч с упорядоченной отправкой результатов
        
        Args:
            semaphore: Семафор для ограничения параллельных запросов
            batch_posts: Посты для обработки
            channel_name: Название канала
            keywords: Ключевые слова
            batch_idx: Номер батча
            total_batches: Общее количество батчей для канала
            send_callback: Колбэк для отправки результата
            channel_buffers: Буферы готовых саммари для каждого канала
            channel_next_batch: Следующий ожидаемый номер батча для каждого канала
            channel_total_batches: Общее количество батчей для каждого канала
            channel_locks: Блокировки для синхронизации отправки
            
        Returns:
            Саммари батча
        """
        async with semaphore:
            logger.info(f"Начинаем обработку батча {batch_idx}/{total_batches} канала @{channel_name} ({len(batch_posts)} постов)")
            
            try:
                # Создаем саммари для батча
                batch_summary = await self._summarize_batch(
                    batch_posts, 
                    channel_name, 
                    keywords,
                    batch_idx,
                    total_batches
                )
                
                if batch_summary and send_callback:
                    # Сохраняем саммари в буфер и проверяем возможность отправки
                    await self._buffer_and_send_ordered(
                        channel_name=channel_name,
                        batch_idx=batch_idx,
                        batch_summary=batch_summary,
                        send_callback=send_callback,
                        channel_buffers=channel_buffers,
                        channel_next_batch=channel_next_batch,
                        channel_total_batches=channel_total_batches,
                        channel_locks=channel_locks
                    )
                
                return batch_summary
                
            except Exception as e:
                logger.error(f"Ошибка при обработке батча {batch_idx} канала @{channel_name}: {e}")
                return f"❌ Ошибка при обработке батча {batch_idx} канала @{channel_name}: {str(e)}"
    
    async def _buffer_and_send_ordered(
        self,
        channel_name: str,
        batch_idx: int,
        batch_summary: str,
        send_callback: Callable[[str, str], Any],
        channel_buffers: Dict[str, Dict[int, str]],
        channel_next_batch: Dict[str, int],
        channel_total_batches: Dict[str, int],
        channel_locks: Dict[str, asyncio.Lock]
    ):
        """
        Буферизует саммари и отправляет их в правильном порядке
        
        Args:
            channel_name: Название канала
            batch_idx: Номер батча
            batch_summary: Готовый саммари
            send_callback: Колбэк для отправки
            channel_buffers: Буферы готовых саммари
            channel_next_batch: Следующий ожидаемый номер батча
            channel_total_batches: Общее количество батчей
            channel_locks: Блокировки для синхронизации
        """
        async with channel_locks[channel_name]:
            # Сохраняем саммари в буфер
            channel_buffers[channel_name][batch_idx] = batch_summary
            logger.info(f"Саммари батча {batch_idx} канала @{channel_name} сохранен в буфер")
            
            # Отправляем все готовые батчи по порядку
            while (channel_next_batch[channel_name] in channel_buffers[channel_name] and
                   channel_next_batch[channel_name] <= channel_total_batches[channel_name]):
                
                current_batch = channel_next_batch[channel_name]
                summary_to_send = channel_buffers[channel_name][current_batch]
                
                try:
                    await send_callback(channel_name, summary_to_send)
                    logger.info(f"Саммари батча {current_batch}/{channel_total_batches[channel_name]} канала @{channel_name} отправлен")
                    
                    # Удаляем отправленный саммари из буфера
                    del channel_buffers[channel_name][current_batch]
                    
                    # Переходим к следующему батчу
                    channel_next_batch[channel_name] += 1
                    
                except Exception as callback_error:
                    logger.error(f"Ошибка при отправке саммари батча {current_batch} канала @{channel_name}: {callback_error}")
                    break
    
    async def _summarize_batch(
        self, 
        batch_posts: List[Dict[str, Any]], 
        channel_name: str, 
        keywords: str,
        batch_number: int,
        total_batches: int
    ) -> str:
        """
        Создает саммари для одного батча постов из одного канала
        
        Args:
            batch_posts: Посты для саммаризации в этом батче
            channel_name: Название канала
            keywords: Ключевые слова фильтрации
            batch_number: Номер текущего батча
            total_batches: Общее количество батчей для этого канала
            
        Returns:
            Саммари батча
        """
        try:
            # Подготавливаем текст постов батча
            posts_text = self._prepare_batch_posts_text(batch_posts, channel_name)
            
            # Создаем промпт для саммаризации батча
            prompt = self._create_batch_prompt(
                posts_text, 
                keywords, 
                len(batch_posts),
                channel_name,
                batch_number,
                total_batches
            )
            
            # Отправляем запрос к OpenAI
            logger.info(f"Отправляем батч {batch_number} канала @{channel_name} ({len(batch_posts)} постов) на саммаризацию в OpenAI")
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "Ты - эксперт по анализу и саммаризации контента из Telegram каналов. Твоя задача создавать подробные и структурированные саммари на русском языке для батча постов из одного канала. Не используй жирный шрифт или курсив."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=4000,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content.strip()
            logger.info(f"Саммаризация батча {batch_number} канала @{channel_name} завершена успешно")
            
            return summary
            
        except Exception as e:
            logger.error(f"Ошибка при саммаризации батча {batch_number} канала @{channel_name}: {e}")
            return f"❌ Ошибка при создании саммари батча {batch_number} для канала @{channel_name}: {str(e)}"
    
    def _prepare_batch_posts_text(self, batch_posts: List[Dict[str, Any]], channel_name: str) -> str:
        """Подготавливает текст постов батча для отправки в OpenAI"""
        prepared_text = [f"📢 КАНАЛ: @{channel_name}"]
        prepared_text.append("=" * 50)
        
        for i, post in enumerate(batch_posts, 1):
            date_str = post['date'].strftime('%d.%m.%Y %H:%M')
            text = post['text'][:3000]  # Ограничиваем длину текста поста
            
            post_text = f"ПОСТ {i}:\nДата: {date_str}\nТекст: {text}\n"
            prepared_text.append(post_text)
        
        prepared_text.append("=" * 50)
        
        return "\n".join(prepared_text)
    
    def _create_batch_prompt(
        self, 
        posts_text: str, 
        keywords: str, 
        posts_count: int,
        channel_name: str,
        batch_number: int,
        total_batches: int
    ) -> str:
        """Создает промпт для саммаризации батча"""
        keywords_info = f"\nКлючевые слова фильтрации: {keywords}" if keywords else ""
        
        batch_info = ""
        if total_batches > 1:
            batch_info = f"\nЭто батч {batch_number} из {total_batches} для канала @{channel_name}."
        
        prompt = f"""Проанализируй {posts_count} постов из Telegram канала @{channel_name} и создай подробное структурированное саммари на русском языке.{keywords_info}{batch_info}

ТРЕБОВАНИЯ К САММАРИ:
1. Создай заголовок с указанием канала и номера батча (если батчей больше одного)
2. Для каждого поста создавай подробное саммари с сохранением всех важных деталей
3. Включи все важные детали, цифры, ссылки, действия из оригинальных постов
4. Сохрани структуру и логику оригинальных постов
5. Не используй жирный шрифт или курсив
6. Используй эмодзи для структурирования и разделения
7. Обязательно сохраняй ссылки, номера телефонов, даты, время, и т.д.
8. Делай саммари подробным, минимум 40% от всего текста постов.
9. У тебя нет лимита слов, ты можешь писать столько, сколько нужно.

ФОРМАТ ВЫВОДА:
📢 Канал: @{channel_name}{' (батч ' + str(batch_number) + '/' + str(total_batches) + ')' if total_batches > 1 else ''}

📄 Пост 1: [подробное саммари]
📄 Пост 2: [подробное саммари]
...

ПОСТЫ ДЛЯ АНАЛИЗА:
{posts_text}

Создай подробное и структурированное саммари:"""
        
        return prompt 