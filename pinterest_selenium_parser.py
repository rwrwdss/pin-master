"""
Парсер Pinterest с использованием Selenium для динамической загрузки контента.
Pinterest использует JavaScript для загрузки данных, поэтому нужен браузер.
"""

import time
import json
import os
import uuid
import requests
from urllib.parse import urlparse
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

from pinterest_selectors import PinterestSelectors, PinterestURLs, PinterestConfig
from cookies_manager import load_cookies_from_file


class PinterestSeleniumParser:
    """Парсер Pinterest с использованием Selenium"""
    
    def __init__(self, cookies_file: Optional[str] = None, headless: bool = True, download_images: bool = True):
        """
        Инициализирует парсер с Selenium.
        
        Args:
            cookies_file: Путь к файлу с cookies
            headless: Запускать браузер в фоновом режиме
            download_images: Скачивать изображения в локальную папку
        """
        self.cookies_file = cookies_file
        self.headless = headless
        self.download_images = download_images
        self.images_dir = None
        self.driver = None
        self._setup_driver()
        
        # Создаем папку для изображений если нужно
        if self.download_images:
            self._create_images_directory()
    
    def _setup_driver(self):
        """Настраивает и запускает Chrome драйвер"""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(f'user-agent={PinterestConfig.USER_AGENT}')
        chrome_options.add_argument('--window-size=1920,1080')
        
        # Отключаем логи
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✓ Chrome драйвер запущен")
        except Exception as e:
            print(f"Ошибка при запуске Chrome драйвера: {e}")
            print("Убедитесь, что Chrome установлен на системе")
            raise
    
    def _create_images_directory(self):
        """Создает папку с рандомным названием для сохранения изображений"""
        random_name = str(uuid.uuid4())[:8]
        self.images_dir = f"pinterest_images_{random_name}"
        os.makedirs(self.images_dir, exist_ok=True)
        print(f"✓ Создана папка для изображений: {self.images_dir}")
    
    def _download_image(self, image_url: str, pin_id: str) -> Optional[str]:
        """
        Скачивает изображение через Selenium и возвращает относительный путь к файлу.
        
        Args:
            image_url: URL изображения
            pin_id: ID пина для имени файла
            
        Returns:
            Относительный путь к скачанному файлу или None
        """
        if not self.download_images or not self.images_dir:
            return image_url
        
        try:
            # Получаем расширение файла из URL
            parsed_url = urlparse(image_url)
            path = parsed_url.path
            ext = os.path.splitext(path)[1] or '.jpg'
            
            # Создаем имя файла
            filename = f"{pin_id}{ext}"
            filepath = os.path.join(self.images_dir, filename)
            
            # Если файл уже существует, возвращаем путь
            if os.path.exists(filepath):
                return os.path.join(self.images_dir, filename)
            
            # Используем cookies из Selenium браузера
            selenium_cookies = self.driver.get_cookies()
            cookies_dict = {cookie['name']: cookie['value'] for cookie in selenium_cookies}
            
            # Также загружаем cookies из файла если есть
            if self.cookies_file or os.path.exists("pinterest_cookies.json"):
                file_cookies = load_cookies_from_file(self.cookies_file or "pinterest_cookies.json")
                if file_cookies:
                    cookies_dict.update(file_cookies)
            
            # Скачиваем через requests с cookies
            headers = {
                'User-Agent': PinterestConfig.USER_AGENT,
                'Referer': 'https://www.pinterest.com/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            response = requests.get(image_url, headers=headers, cookies=cookies_dict, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # Сохраняем файл
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Возвращаем относительный путь
            return os.path.join(self.images_dir, filename)
            
        except Exception as e:
            print(f"⚠ Ошибка при скачивании изображения {image_url}: {e}")
            return image_url  # Возвращаем оригинальный URL если не удалось скачать
    
    def _load_cookies(self):
        """Загружает cookies в браузер"""
        if not self.cookies_file:
            if not load_cookies_from_file("pinterest_cookies.json"):
                return False
        
        cookies = load_cookies_from_file(self.cookies_file or "pinterest_cookies.json")
        if not cookies:
            return False
        
        # Переходим на Pinterest для установки cookies
        self.driver.get("https://www.pinterest.com")
        time.sleep(2)
        
        # Устанавливаем cookies
        for name, value in cookies.items():
            try:
                self.driver.add_cookie({
                    'name': name,
                    'value': value,
                    'domain': '.pinterest.com',
                    'path': '/'
                })
            except Exception as e:
                print(f"Ошибка при установке cookie {name}: {e}")
        
        print(f"✓ Загружено {len(cookies)} cookies")
        return True
    
    def parse_search_page(self, query: str, max_pins: int = None, scroll_times: int = 3) -> List[Dict[str, str]]:
        """
        Парсит страницу поиска Pinterest.
        
        Args:
            query: Поисковый запрос
            max_pins: Максимальное количество пинов
            scroll_times: Количество прокруток страницы для загрузки контента
            
        Returns:
            Список словарей с данными о пинах
        """
        if max_pins is None:
            max_pins = PinterestConfig.MAX_PINS
        
        url = PinterestURLs.SEARCH_URL.format(query=query)
        print(f"Загрузка страницы: {url}")
        
        # Загружаем cookies если есть
        if self.cookies_file or load_cookies_from_file("pinterest_cookies.json"):
            self._load_cookies()
        
        # Переходим на страницу поиска
        self.driver.get(url)
        time.sleep(PinterestConfig.PAGE_LOAD_DELAY)
        
        # Прокручиваем страницу для загрузки контента
        print("Прокрутка страницы для загрузки контента...")
        for i in range(scroll_times):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            print(f"  Прокрутка {i+1}/{scroll_times}")
        
        # Получаем HTML после загрузки JavaScript
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Парсим HTML (JS данные требуют дополнительной обработки)
        pins_data = self._extract_from_html(soup)
        
        # Если не нашли через HTML, пробуем JS данные
        if not pins_data:
            pins_data = self._extract_from_js_data()
        
        # Парсим детальные страницы для получения полной информации
        if pins_data:
            print("Получение полной информации о пинах...")
            for i, pin in enumerate(pins_data[:max_pins]):
                if pin.get('pin_link'):
                    detail = self.parse_pin_detail(pin['pin_link'])
                    if detail:
                        # Обновляем данные, сохраняя то что уже есть
                        for key, value in detail.items():
                            if value or not pins_data[i].get(key):
                                pins_data[i][key] = value
                    
                    # Скачиваем изображение если нужно
                    if self.download_images and pins_data[i].get('image_url'):
                        pin_id = pin['pin_link'].split('/pin/')[-1].rstrip('/')
                        local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                        if local_path:
                            pins_data[i]['image_url'] = local_path
                    
                    time.sleep(1)  # Задержка между запросами
        
        print(f"Найдено пинов: {len(pins_data)}")
        return pins_data[:max_pins]
    
    def _extract_from_js_data(self) -> List[Dict[str, str]]:
        """Извлекает данные из JavaScript переменных на странице"""
        pins_data = []
        
        try:
            # Пробуем получить данные из window.__PWS_INITIAL_STATE__ или подобных
            js_data = self.driver.execute_script("""
                if (window.__PWS_INITIAL_STATE__) {
                    return JSON.stringify(window.__PWS_INITIAL_STATE__);
                }
                if (window.__PWS_RESOURCE_DATA_BEFORE_INIT__) {
                    return JSON.stringify(window.__PWS_RESOURCE_DATA_BEFORE_INIT__);
                }
                return null;
            """)
            
            if js_data:
                data = json.loads(js_data)
                # TODO: Парсинг структуры данных Pinterest
                print("✓ Найдены данные в JavaScript переменных")
        except Exception as e:
            print(f"Ошибка при извлечении JS данных: {e}")
        
        return pins_data
    
    def _extract_from_html(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Извлекает данные из HTML структуры используя Selenium"""
        pins_data = []
        
        try:
            # Используем Selenium для поиска элементов пинов
            # Pinterest использует различные селекторы, пробуем несколько вариантов
            pin_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/pin/"]')
            
            seen_pins = set()
            
            for element in pin_elements:
                try:
                    href = element.get_attribute('href')
                    if not href or href in seen_pins:
                        continue
                    
                    seen_pins.add(href)
                    
                    # Получаем полный URL
                    if not href.startswith('http'):
                        pin_url = f"https://www.pinterest.com{href}"
                    else:
                        pin_url = href
                    
                    # Ищем родительский контейнер пина
                    try:
                        # Пробуем найти родительский элемент с данными
                        parent = element.find_element(By.XPATH, './ancestor::div[contains(@class, "pin") or contains(@class, "item") or contains(@class, "card")][1]')
                    except:
                        try:
                            parent = element.find_element(By.XPATH, './..')
                        except:
                            parent = element
                    
                    # Извлекаем данные
                    image_url = ""
                    title = ""
                    description = ""
                    author = ""
                    
                    # Ищем изображение
                    try:
                        img = parent.find_element(By.TAG_NAME, 'img')
                        image_url = img.get_attribute('src') or img.get_attribute('data-src') or img.get_attribute('data-lazy-src')
                        if not image_url:
                            # Пробуем через style background-image
                            style = img.get_attribute('style') or parent.get_attribute('style')
                            if style and 'background-image' in style:
                                import re
                                match = re.search(r'url\(["\']?([^"\']+)["\']?\)', style)
                                if match:
                                    image_url = match.group(1)
                    except:
                        pass
                    
                    # Ищем название/описание
                    try:
                        # Пробуем найти текст в различных элементах
                        text_elements = parent.find_elements(By.CSS_SELECTOR, 'div, span, p, h1, h2, h3')
                        for text_elem in text_elements:
                            text = text_elem.text.strip()
                            if text and len(text) > 10 and len(text) < 500:
                                if not title:
                                    title = text
                                elif not description and text != title:
                                    description = text
                                    break
                    except:
                        pass
                    
                    # Ищем автора
                    try:
                        author_elements = parent.find_elements(By.CSS_SELECTOR, 'a[href^="/"][href*="/"]')
                        for auth_elem in author_elements:
                            auth_href = auth_elem.get_attribute('href')
                            if auth_href and '/pin/' not in auth_href and auth_elem.text.strip():
                                author = auth_elem.text.strip()
                                break
                    except:
                        pass
                    
                    # Если нашли хотя бы URL и изображение, добавляем
                    if pin_url:
                        # Преобразуем URL изображения в прямую ссылку
                        if image_url and 'pinimg.com' in image_url:
                            # Заменяем размеры на originals для полного размера
                            if '/564x/' in image_url:
                                image_url = image_url.replace('/564x/', '/originals/')
                            elif '/236x/' in image_url:
                                image_url = image_url.replace('/236x/', '/originals/')
                        
                        pins_data.append({
                            'author': author,
                            'pin_link': pin_url,
                            'image_url': image_url,
                            'title': title,
                            'description': description
                        })
                
                except Exception as e:
                    # Пропускаем элемент при ошибке
                    continue
        
        except Exception as e:
            print(f"Ошибка при извлечении данных из HTML: {e}")
        
        return pins_data
    
    def _expand_description(self):
        """Находит и нажимает кнопку 'больше'/'See more' для разворачивания полного описания"""
        try:
            # Сначала ищем все кликабельные элементы с текстом "больше", "more", "..."
            all_clickable = self.driver.find_elements(By.XPATH, "//*[self::button or self::a or self::span][contains(text(), 'больше') or contains(text(), 'Больше') or contains(text(), 'See more') or contains(text(), 'see more') or contains(text(), '...')]")
            
            for element in all_clickable:
                try:
                    text = element.text.strip().lower()
                    # Проверяем, что это действительно кнопка разворачивания
                    if (('больше' in text or 'more' in text or '...' in text) and
                        element.is_displayed() and element.is_enabled()):
                        # Прокручиваем к элементу
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                        time.sleep(0.3)
                        
                        # Пробуем кликнуть через JavaScript (более надежно)
                        try:
                            self.driver.execute_script("arguments[0].click();", element)
                            time.sleep(1.5)  # Ждем разворачивания
                            print("  ✓ Нажата кнопка 'больше' для разворачивания описания")
                            return True
                        except:
                            # Если не получилось через JS, пробуем обычный клик
                            element.click()
                            time.sleep(1.5)
                            print("  ✓ Нажата кнопка 'больше' для разворачивания описания")
                            return True
                except:
                    continue
            
            # Также ищем по атрибутам
            try:
                # Ищем элементы с aria-label или data-test-id
                expand_elements = self.driver.find_elements(By.XPATH, 
                    "//*[contains(@aria-label, 'more') or contains(@aria-label, 'expand') or contains(@data-test-id, 'expand')]")
                for elem in expand_elements:
                    try:
                        if elem.is_displayed() and elem.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", elem)
                            time.sleep(1.5)
                            print("  ✓ Нажата кнопка 'больше' для разворачивания описания")
                            return True
                    except:
                        continue
            except:
                pass
            
            return False
        except Exception as e:
            print(f"  ⚠ Ошибка при поиске кнопки 'больше': {e}")
            return False
    
    def parse_pin_detail(self, pin_url: str) -> Optional[Dict[str, str]]:
        """Парсит детальную страницу пина для получения полной информации"""
        try:
            self.driver.get(pin_url)
            time.sleep(PinterestConfig.PAGE_LOAD_DELAY)
            
            pin_data = {
                'author': '',
                'pin_link': pin_url,
                'image_url': '',
                'title': '',
                'description': ''
            }
            
            # Сначала пытаемся развернуть описание, нажав на кнопку "больше"
            expanded = self._expand_description()
            if not expanded:
                # Если кнопка не найдена, возможно описание уже развернуто
                pass
            
            # Ищем название - более тщательный поиск
            try:
                title_selectors = [
                    'h1',
                    '[data-test-id="pin-title"]',
                    '.pinTitle',
                    'div[class*="title"] h1',
                    'div[class*="Title"] h1',
                    'h1[class*="title"]',
                    'h1[class*="Title"]',
                ]
                
                for selector in title_selectors:
                    try:
                        title_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for elem in title_elements:
                            text = elem.text.strip()
                            # Название обычно короткое и не содержит URL
                            if (text and len(text) < 200 and 
                                not text.startswith('http') and
                                text not in ['Pinterest', 'Save', 'Сохранить']):
                                pin_data['title'] = text
                                break
                        if pin_data['title']:
                            break
                    except:
                        continue
            except Exception as e:
                print(f"Ошибка при поиске названия: {e}")
                pass
            
            # Ищем описание - более тщательный поиск с фильтрацией (после разворачивания)
            try:
                # Пробуем разные селекторы для описания
                desc_selectors = [
                    '[data-test-id="pin-description"]',
                    '.pinDescription',
                    'div[class*="description"]',
                    'div[class*="Description"]',
                    'p[class*="description"]',
                    'span[class*="description"]',
                    # Ищем большие блоки текста
                    'div[class*="richPin"] p',
                    'div[class*="RichPin"] p',
                    # Ищем в основном контенте
                    'div[class*="PinDetail"] p',
                    'div[class*="pinDetail"] p',
                ]
                
                # Слова для фильтрации (исключаем элементы навигации)
                exclude_keywords = [
                    'Просмотреть', 'View', 'See more', 'Больше', 'Сохранить', 'Save',
                    'Войти', 'Login', 'Регистрация', 'Sign up', 'Поиск', 'Search',
                    'Комментарии', 'Comments', 'Ингредиенты', 'Ingredients',
                    'Другие интересные пины', 'More ideas', 'Подробнее об этом пине',
                    'Вы вышли из системы', 'You\'ve been logged out', 'меньше', 'less'
                ]
                
                for selector in desc_selectors:
                    try:
                        desc_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for elem in desc_elements:
                            text = elem.text.strip()
                            # Фильтруем описание - теперь берем полное описание
                            if (text and len(text) > 50 and 
                                text != pin_data['title'] and 
                                not text.startswith('http') and
                                not any(keyword in text for keyword in exclude_keywords)):
                                # Берем полное описание (не обрезаем)
                                pin_data['description'] = text
                                break
                        if pin_data['description']:
                            break
                    except:
                        continue
                
                # Если не нашли через селекторы, ищем текст с ключевыми словами
                if not pin_data['description']:
                    # Ищем в основном контенте страницы
                    try:
                        # Пробуем найти основной контент
                        main_content = self.driver.find_element(By.TAG_NAME, 'body')
                        all_text = main_content.text
                        
                        # Разбиваем на строки и ищем описание
                        lines = all_text.split('\n')
                        description_candidates = []
                        
                        for line in lines:
                            line = line.strip()
                            if (line and len(line) > 50 and len(line) < 2000 and
                                line != pin_data['title'] and
                                not line.startswith('http') and
                                not any(keyword in line for keyword in exclude_keywords) and
                                ('Want' in line or 'Discover' in line or 'recipe' in line.lower() or 
                                 'flavor' in line.lower() or 'delightful' in line.lower() or
                                 'perfect' in line.lower() or 'delicious' in line.lower() or
                                 'savory' in line.lower() or 'tantalize' in line.lower() or
                                 'tasty' in line.lower() or 'easy' in line.lower())):
                                description_candidates.append(line)
                        
                        # Берем первое подходящее описание (полное, не обрезаем)
                        if description_candidates:
                            # Берем самое длинное и подходящее
                            best_desc = max(description_candidates, key=len)
                            pin_data['description'] = best_desc
                    except:
                        pass
            except Exception as e:
                print(f"Ошибка при поиске описания: {e}")
                pass
            
            # Ищем автора (избегаем кнопок типа "Просмотреть")
            try:
                author_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href^="/"][href*="/"]')
                for elem in author_elements:
                    href = elem.get_attribute('href')
                    text = elem.text.strip()
                    # Пропускаем кнопки и системные ссылки
                    if (href and '/pin/' not in href and '/search/' not in href and 
                        text and text not in ['Просмотреть', 'View', 'See more', 'Больше', 'Сохранить', 'Save'] and
                        len(text) < 50):  # Имя пользователя обычно короткое
                        pin_data['author'] = text
                        break
            except:
                pass
            
            # Ищем изображение
            try:
                img_elements = self.driver.find_elements(By.CSS_SELECTOR, 'img[src*="pinimg.com"]')
                for img in img_elements:
                    src = img.get_attribute('src') or img.get_attribute('data-src')
                    if src and 'pinimg.com' in src:
                        # Преобразуем в оригинал (полный размер)
                        if '/736x/' in src:
                            src = src.replace('/736x/', '/originals/')
                        elif '/564x/' in src:
                            src = src.replace('/564x/', '/originals/')
                        elif '/236x/' in src:
                            src = src.replace('/236x/', '/originals/')
                        pin_data['image_url'] = src
                        break
            except:
                pass
            
            return pin_data if pin_data['pin_link'] else None
            
        except Exception as e:
            print(f"Ошибка при парсинге пина {pin_url}: {e}")
            return None
    
    def close(self):
        """Закрывает браузер"""
        if self.driver:
            self.driver.quit()
            print("✓ Браузер закрыт")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    import sys
    from pinterest_parser import PinterestParser
    
    print("=" * 80)
    print("ПАРСЕР PINTEREST")
    print("=" * 80)
    print()
    
    # Интерактивный ввод тематики
    if len(sys.argv) > 1:
        # Если передан аргумент, используем его
        query = sys.argv[1]
        max_pins = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    else:
        # Интерактивный режим
        print("Введите тематику для парсинга:")
        print("(например: python programming, cooking recipes, interior design)")
        print()
        query = input("Тематика: ").strip()
        
        if not query:
            print("⚠ Тематика не введена. Используется пример: 'python programming'")
            query = "python programming"
        
        print()
        max_pins_input = input("Количество пинов для парсинга (по умолчанию 10): ").strip()
        try:
            max_pins = int(max_pins_input) if max_pins_input else 10
        except ValueError:
            print("⚠ Неверное значение. Используется 10")
            max_pins = 10
    
    print()
    print(f"Начинаем парсинг тематики: '{query}'")
    print(f"Количество пинов: {max_pins}")
    print()
    
    # Создаем парсер
    parser = PinterestSeleniumParser(headless=True)
    
    try:
        pins = parser.parse_search_page(query, max_pins=max_pins)
        
        if pins:
            print(f"\n✓ Найдено {len(pins)} пинов")
            
            # Показываем первые 3 примера
            print("\nПримеры найденных пинов:")
            for i, pin in enumerate(pins[:3], 1):
                print(f"\n{i}. {pin.get('title', 'Без названия') or 'Без названия'}")
                print(f"   Автор: {pin.get('author', 'Неизвестно') or 'Неизвестно'}")
                print(f"   Ссылка: {pin.get('pin_link', '')}")
                if pin.get('image_url'):
                    print(f"   Изображение: {pin.get('image_url', '')[:80]}...")
            
            # Сохраняем в CSV
            csv_parser = PinterestParser()
            filename = f"pinterest_pins_{query.replace(' ', '_').replace('/', '_')[:50]}.csv"
            csv_parser.save_to_csv(pins, filename)
            print(f"\n✓ Данные сохранены в файл: {filename}")
        else:
            print("\n⚠ Пины не найдены. Попробуйте:")
            print("  - Добавить cookies для авторизации")
            print("  - Изменить поисковый запрос")
            print("  - Проверить интернет-соединение")
    finally:
        parser.close()
