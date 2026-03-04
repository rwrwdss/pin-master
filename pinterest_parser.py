"""
Парсер Pinterest для извлечения данных о пинах.
"""

import time
import csv
import json
import os
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

from pinterest_selectors import PinterestSelectors, PinterestURLs, PinterestConfig
from cookies_manager import CookiesManager, load_cookies_from_file


class PinterestParser:
    """Класс для парсинга данных с Pinterest"""
    
    def __init__(self, cookies_file: Optional[str] = None):
        """
        Инициализирует парсер с опциональной загрузкой cookies.
        
        Args:
            cookies_file: Путь к файлу с cookies (JSON, Netscape или строка)
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': PinterestConfig.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': 'https://www.pinterest.com/',
        })
        self.base_url = PinterestURLs.BASE_URL
        
        # Загружаем cookies если указан файл
        if cookies_file:
            self.load_cookies(cookies_file)
        elif os.path.exists("pinterest_cookies.json"):
            # Автоматически загружаем cookies если файл существует
            self.load_cookies("pinterest_cookies.json")
    
    def load_cookies(self, filepath: str):
        """
        Загружает cookies из файла в сессию.
        
        Args:
            filepath: Путь к файлу с cookies
        """
        cookies = load_cookies_from_file(filepath)
        if cookies:
            # Устанавливаем cookies для домена pinterest.com
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain='.pinterest.com')
            
            # Проверяем авторизацию
            is_authorized = CookiesManager.check_authorization(self.session)
            if is_authorized:
                print("✓ Авторизация успешна")
            else:
                print("⚠ Авторизация не подтверждена, но cookies загружены")
        else:
            print(f"⚠ Не удалось загрузить cookies из {filepath}")
    
    def set_cookies(self, cookies: Dict[str, str]):
        """
        Устанавливает cookies напрямую.
        
        Args:
            cookies: Словарь с cookies
        """
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain='.pinterest.com')
        
    def _make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Выполняет HTTP запрос и возвращает BeautifulSoup объект"""
        try:
            time.sleep(PinterestConfig.REQUEST_DELAY)
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Ошибка при запросе {url}: {e}")
            return None
    
    def _extract_pin_data(self, pin_element) -> Optional[Dict[str, str]]:
        """
        Извлекает данные из элемента пина.
        Этот метод будет обновлен после определения селекторов.
        """
        # TODO: Реализовать после определения селекторов
        return None
    
    def _get_direct_image_url(self, image_url: str) -> str:
        """
        Преобразует URL изображения в прямую ссылку для скачивания.
        Pinterest использует специальные URL для изображений.
        """
        # Pinterest обычно использует формат: https://i.pinimg.com/originals/...
        # или https://i.pinimg.com/564x/...
        if 'pinimg.com' in image_url:
            # Убираем параметры размера для получения оригинала
            parsed = urlparse(image_url)
            if '/564x/' in parsed.path or '/236x/' in parsed.path:
                # Заменяем на originals для получения полного размера
                path = parsed.path.replace('/564x/', '/originals/')
                path = path.replace('/236x/', '/originals/')
                return f"{parsed.scheme}://{parsed.netloc}{path}"
        return image_url
    
    def parse_search(self, query: str, max_pins: int = None) -> List[Dict[str, str]]:
        """
        Парсит результаты поиска Pinterest.
        
        Args:
            query: Поисковый запрос
            max_pins: Максимальное количество пинов для парсинга
            
        Returns:
            Список словарей с данными о пинах
        """
        if max_pins is None:
            max_pins = PinterestConfig.MAX_PINS
            
        url = PinterestURLs.SEARCH_URL.format(query=query)
        print(f"Парсинг поиска: {query}")
        
        soup = self._make_request(url)
        if not soup:
            return []
        
        pins_data = []
        
        # TODO: Реализовать парсинг после определения селекторов
        # Пример структуры данных:
        # pin_data = {
        #     'author': '...',
        #     'pin_link': '...',
        #     'image_url': '...',
        #     'title': '...',
        #     'description': '...'
        # }
        
        print(f"Найдено пинов: {len(pins_data)}")
        return pins_data[:max_pins]
    
    def parse_pin_page(self, pin_url: str) -> Optional[Dict[str, str]]:
        """
        Парсит детальную страницу пина.
        
        Args:
            pin_url: URL пина
            
        Returns:
            Словарь с данными о пине или None
        """
        soup = self._make_request(pin_url)
        if not soup:
            return None
        
        # TODO: Реализовать парсинг после определения селекторов
        return None
    
    def save_to_csv(self, pins_data: List[Dict[str, str]], filename: str = "pinterest_pins.csv"):
        """
        Сохраняет данные о пинах в CSV файл.
        
        Args:
            pins_data: Список словарей с данными о пинах
            filename: Имя файла для сохранения
        """
        if not pins_data:
            print("Нет данных для сохранения")
            return
        
        fieldnames = ['author', 'pin_link', 'image_url', 'title', 'description']
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for pin in pins_data:
                # Обеспечиваем наличие всех полей
                row = {
                    'author': pin.get('author', ''),
                    'pin_link': pin.get('pin_link', ''),
                    'image_url': pin.get('image_url', ''),
                    'title': pin.get('title', ''),
                    'description': pin.get('description', '')
                }
                writer.writerow(row)
        
        print(f"Данные сохранены в {filename}")
    
    def save_selectors_to_file(self, filename: str = "selectors_backup.json"):
        """Сохраняет текущие селекторы в JSON файл для резервного копирования"""
        selectors_dict = {
            'PIN_CARD': PinterestSelectors.PIN_CARD,
            'PIN_LINK': PinterestSelectors.PIN_LINK,
            'PIN_IMAGE': PinterestSelectors.PIN_IMAGE,
            'PIN_TITLE': PinterestSelectors.PIN_TITLE,
            'PIN_DESCRIPTION': PinterestSelectors.PIN_DESCRIPTION,
            'PIN_AUTHOR': PinterestSelectors.PIN_AUTHOR,
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(selectors_dict, f, indent=2, ensure_ascii=False)
        
        print(f"Селекторы сохранены в {filename}")


def main():
    """Основная функция для тестирования парсера"""
    # Автоматически загружает cookies если файл существует
    parser = PinterestParser()
    
    # Пример использования
    query = "python programming"
    pins = parser.parse_search(query, max_pins=10)
    
    if pins:
        parser.save_to_csv(pins)
    else:
        print("Пины не найдены. Необходимо настроить селекторы.")
        print("Также убедитесь, что cookies загружены (см. COOKIES_INSTRUCTIONS.md)")


if __name__ == "__main__":
    main()
