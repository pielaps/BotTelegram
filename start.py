#!/usr/bin/env python3
"""
Скрипт запуска телеграм бота для мониторинга каналов
"""

import os
import sys
import subprocess
from pathlib import Path

def check_python_version():
    """Проверка версии Python"""
    if sys.version_info < (3, 8):
        print("❌ Требуется Python 3.8 или выше")
        print(f"Текущая версия: {sys.version}")
        return False
    return True

def check_env_file():
    """Проверка наличия .env файла"""
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ Файл .env не найден!")
        print("📝 Создайте файл .env на основе .env.example:")
        print("   cp .env.example .env")
        print("   nano .env")
        return False
    
    # Проверяем, что файл не пустой
    with open(env_file, 'r') as f:
        content = f.read().strip()
        if not content or all(line.split('=')[1].strip() == '' for line in content.split('\n') if '=' in line):
            print("⚠️  Файл .env пустой или не заполнен!")
            print("📝 Заполните переменные окружения в файле .env")
            return False
    
    return True

def install_dependencies():
    """Установка зависимостей"""
    try:
        print("📦 Проверка зависимостей...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ Зависимости установлены")
        return True
    except subprocess.CalledProcessError:
        print("❌ Ошибка при установке зависимостей")
        print("💡 Попробуйте выполнить вручную:")
        print("   pip install -r requirements.txt")
        return False

def main():
    """Главная функция"""
    print("🤖 Запуск телеграм бота мониторинга каналов")
    print("=" * 50)
    
    # Проверка Python
    if not check_python_version():
        sys.exit(1)
    
    # Проверка .env файла
    if not check_env_file():
        sys.exit(1)
    
    # Установка зависимостей
    if not install_dependencies():
        sys.exit(1)
    
    print("🚀 Запуск бота...")
    print("=" * 50)
    
    try:
        # Запуск бота
        subprocess.run([sys.executable, "bot.py"])
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка запуска: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 