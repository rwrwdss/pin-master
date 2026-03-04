"""
Утилита для управления cookies для авторизации в Pinterest.
Поддерживает загрузку cookies из различных форматов.
"""

import json
import os
from typing import Dict, Optional
from http.cookiejar import MozillaCookieJar
import requests


class CookiesManager:
    """Класс для управления cookies авторизации"""
    
    @staticmethod
    def load_from_netscape_file(filepath: str) -> Dict[str, str]:
        """
        Загружает cookies из файла в формате Netscape (экспорт из браузера).
        
        Args:
            filepath: Путь к файлу с cookies
            
        Returns:
            Словарь с cookies
        """
        cookies = {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '\t' in line:
                        parts = line.split('\t')
                        if len(parts) >= 7:
                            domain = parts[0]
                            if 'pinterest.com' in domain:
                                name = parts[5]
                                value = parts[6]
                                cookies[name] = value
            print(f"Загружено {len(cookies)} cookies из {filepath}")
            return cookies
        except Exception as e:
            print(f"Ошибка при загрузке cookies из {filepath}: {e}")
            return {}
    
    @staticmethod
    def load_from_json_file(filepath: str) -> Dict[str, str]:
        """
        Загружает cookies из JSON файла.
        Формат: {"cookie_name": "cookie_value", ...}
        или [{"name": "...", "value": "...", "domain": "..."}, ...]
        
        Args:
            filepath: Путь к JSON файлу с cookies
            
        Returns:
            Словарь с cookies
        """
        cookies = {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                if isinstance(data, dict):
                    # Простой формат: {"name": "value"}
                    cookies = data
                elif isinstance(data, list):
                    # Формат массива объектов
                    for item in data:
                        if isinstance(item, dict):
                            name = item.get('name', '')
                            value = item.get('value', '')
                            domain = item.get('domain', '')
                            if name and value and ('pinterest.com' in domain or not domain):
                                cookies[name] = value
                
            print(f"Загружено {len(cookies)} cookies из {filepath}")
            return cookies
        except Exception as e:
            print(f"Ошибка при загрузке cookies из {filepath}: {e}")
            return {}
    
    @staticmethod
    def load_from_browser_string(cookie_string: str) -> Dict[str, str]:
        """
        Загружает cookies из строки формата браузера.
        Формат: "name1=value1; name2=value2; ..."
        
        Args:
            cookie_string: Строка с cookies из браузера
            
        Returns:
            Словарь с cookies
        """
        cookies = {}
        try:
            pairs = cookie_string.split(';')
            for pair in pairs:
                pair = pair.strip()
                if '=' in pair:
                    name, value = pair.split('=', 1)
                    cookies[name.strip()] = value.strip()
            print(f"Загружено {len(cookies)} cookies из строки")
            return cookies
        except Exception as e:
            print(f"Ошибка при парсинге cookies из строки: {e}")
            return {}
    
    @staticmethod
    def save_to_json(cookies: Dict[str, str], filepath: str = "pinterest_cookies.json"):
        """
        Сохраняет cookies в JSON файл.
        
        Args:
            cookies: Словарь с cookies
            filepath: Путь для сохранения
        """
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)
            print(f"Cookies сохранены в {filepath}")
        except Exception as e:
            print(f"Ошибка при сохранении cookies: {e}")
    
    @staticmethod
    def check_authorization(session: requests.Session) -> bool:
        """
        Проверяет, авторизован ли пользователь.
        
        Args:
            session: Сессия requests с cookies
            
        Returns:
            True если авторизован, False иначе
        """
        try:
            # Проверяем наличие важных cookies авторизации
            important_cookies = ['_auth', '_pinterest_sess', 'csrftoken', '_routing_id']
            has_auth = any(cookie.name in important_cookies for cookie in session.cookies)
            
            if has_auth:
                # Делаем тестовый запрос на главную страницу
                response = session.get('https://www.pinterest.com', timeout=10)
                # Проверяем наличие элементов, которые есть только у авторизованных пользователей
                if response.status_code == 200:
                    content = response.text.lower()
                    # Ищем признаки авторизованного пользователя
                    if 'create' in content or 'saved' in content or 'profile' in content:
                        return True
            return False
        except Exception as e:
            print(f"Ошибка при проверке авторизации: {e}")
            return False


def load_cookies_from_file(filepath: str) -> Optional[Dict[str, str]]:
    """
    Автоматически определяет формат файла и загружает cookies.
    
    Args:
        filepath: Путь к файлу с cookies
        
    Returns:
        Словарь с cookies или None
    """
    if not os.path.exists(filepath):
        print(f"Файл {filepath} не найден")
        return None
    
    _, ext = os.path.splitext(filepath.lower())
    
    if ext == '.json':
        return CookiesManager.load_from_json_file(filepath)
    elif ext in ['.txt', '.cookies']:
        # Пробуем как Netscape формат
        cookies = CookiesManager.load_from_netscape_file(filepath)
        if cookies:
            return cookies
        # Если не получилось, пробуем как простой текст
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if '=' in content and ';' in content:
                return CookiesManager.load_from_browser_string(content)
    else:
        # Пробуем все форматы
        cookies = CookiesManager.load_from_json_file(filepath)
        if cookies:
            return cookies
        cookies = CookiesManager.load_from_netscape_file(filepath)
        if cookies:
            return cookies
    
    return None


if __name__ == "__main__":
    """
    Интерактивная утилита для работы с cookies.
    """
    print("=" * 80)
    print("УТИЛИТА ДЛЯ РАБОТЫ С COOKIES PINTEREST")
    print("=" * 80)
    print("\nВыберите способ загрузки cookies:")
    print("1. Из JSON файла")
    print("2. Из файла Netscape формата")
    print("3. Из строки браузера (скопировать из DevTools)")
    print("4. Проверить существующий файл cookies")
    print()
    
    choice = input("Ваш выбор (1-4): ").strip()
    
    if choice == "1":
        filepath = input("Путь к JSON файлу: ").strip()
        cookies = CookiesManager.load_from_json_file(filepath)
        if cookies:
            CookiesManager.save_to_json(cookies, "pinterest_cookies.json")
            print(f"\n✓ Cookies сохранены в pinterest_cookies.json")
    
    elif choice == "2":
        filepath = input("Путь к файлу Netscape формата: ").strip()
        cookies = CookiesManager.load_from_netscape_file(filepath)
        if cookies:
            CookiesManager.save_to_json(cookies, "pinterest_cookies.json")
            print(f"\n✓ Cookies сохранены в pinterest_cookies.json")
    
    elif choice == "3":
        print("\nИнструкция:")
        print("1. Откройте Pinterest в браузере и войдите в аккаунт")
        print("2. Откройте DevTools (F12 или Cmd+Option+I)")
        print("3. Перейдите на вкладку Application/Storage -> Cookies -> https://www.pinterest.com")
        print("4. Скопируйте все cookies в формате: name1=value1; name2=value2; ...")
        print()
        cookie_string = input("Вставьте строку с cookies: ").strip()
        cookies = CookiesManager.load_from_browser_string(cookie_string)
        if cookies:
            CookiesManager.save_to_json(cookies, "pinterest_cookies.json")
            print(f"\n✓ Cookies сохранены в pinterest_cookies.json")
    
    elif choice == "4":
        filepath = input("Путь к файлу cookies: ").strip() or "pinterest_cookies.json"
        cookies = load_cookies_from_file(filepath)
        if cookies:
            print(f"\nНайдено cookies: {len(cookies)}")
            print("Важные cookies:")
            important = ['_auth', '_pinterest_sess', 'csrftoken', '_routing_id', 'sessionFingerprint']
            for key in important:
                if key in cookies:
                    value = cookies[key]
                    print(f"  {key}: {value[:50]}..." if len(value) > 50 else f"  {key}: {value}")
        else:
            print("Cookies не найдены или файл не существует")
    
    else:
        print("Неверный выбор")
