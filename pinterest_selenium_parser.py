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
from pinterest_auth import PinterestAuth


class PinterestSeleniumParser:
    """Парсер Pinterest с использованием Selenium"""
    
    def __init__(self, cookies_file: Optional[str] = None, headless: bool = True, 
                 download_images: bool = True, auto_login: bool = False):
        """
        Инициализирует парсер с Selenium.
        
        Args:
            cookies_file: Путь к файлу с cookies
            headless: Запускать браузер в фоновом режиме
            download_images: Скачивать изображения в локальную папку
            auto_login: Автоматически выполнять логин если cookies нет
        """
        self.cookies_file = cookies_file
        self.headless = headless
        self.download_images = download_images
        self.auto_login = auto_login
        self.images_dir = None
        self.driver = None
        self._setup_driver()
        
        # Проверяем авторизацию и логинимся если нужно
        if self.auto_login:
            print(f"\n🔐 Авторизация включена (auto_login={self.auto_login})")
            self._ensure_authentication()
        else:
            print(f"\nℹ Авторизация отключена (auto_login={self.auto_login})")
        
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
    
    def _ensure_authentication(self):
        """Проверяет авторизацию и выполняет логин если нужно"""
        try:
            print("\n" + "=" * 80)
            print("ПРОВЕРКА АВТОРИЗАЦИИ")
            print("=" * 80)
            
            # Проверяем наличие cookies файла
            cookies_file = self.cookies_file or "pinterest_cookies.json"
            if os.path.exists(cookies_file):
                print(f"✓ Найден файл cookies: {cookies_file}")
                # Пробуем загрузить cookies
                cookies = load_cookies_from_file(cookies_file)
                if cookies:
                    print(f"✓ Загружено {len(cookies)} cookies из файла")
                    
                    # Проверяем что окно браузера открыто
                    try:
                        self.driver.current_url
                    except:
                        print("⚠ Окно браузера закрыто, перезапускаю...")
                        self._setup_driver()
                    
                    # Загружаем cookies в браузер
                    print("  Загрузка cookies в браузер...")
                    self.driver.get("https://www.pinterest.com")
                    
                    # Ждем загрузки страницы (оптимизированно)
                    try:
                        # Ждем только базовую загрузку, не полную
                        WebDriverWait(self.driver, 5).until(
                            lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                        )
                    except:
                        time.sleep(1)  # Минимальная задержка
                    
                    # Устанавливаем cookies с проверкой
                    cookies_set = 0
                    for name, value in cookies.items():
                        try:
                            # Проверяем что окно еще открыто
                            self.driver.current_url
                            
                            self.driver.add_cookie({
                                'name': name,
                                'value': value,
                                'domain': '.pinterest.com',
                                'path': '/'
                            })
                            cookies_set += 1
                        except Exception as e:
                            # Игнорируем ошибки установки отдельных cookies
                            continue
                    
                    print(f"  ✓ Установлено {cookies_set} из {len(cookies)} cookies")
                    
                    # Перезагружаем страницу с cookies
                    self.driver.refresh()
                    
                    # Ждем базовой загрузки (не ждем полной загрузки всех ресурсов)
                    try:
                        WebDriverWait(self.driver, 8).until(
                            lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                        )
                    except:
                        time.sleep(2)  # Минимальная задержка
                    
                    # Проверяем авторизацию
                    page_source = self.driver.page_source.lower()
                    current_url = self.driver.current_url
                    
                    # Проверяем признаки авторизации (более тщательно)
                    is_authorized = (
                        'create' in page_source or 
                        'saved' in page_source or 
                        'profile' in page_source or
                        ('pinterest.com' in current_url and '/login' not in current_url.lower() and '/business' not in current_url.lower())
                    )
                    
                    if is_authorized:
                        print("✓ Используется существующая валидная сессия")
                        print("=" * 80 + "\n")
                        return
                    else:
                        print(f"⚠ Сессия невалидна или истекла (URL: {current_url[:80]})")
                        # Проверяем есть ли кнопка "Войти" на странице
                        if 'войти' in page_source or 'log in' in page_source or 'login' in current_url.lower():
                            print("  На странице обнаружена форма входа - требуется авторизация")
            else:
                print(f"⚠ Файл cookies не найден: {cookies_file}")
            
            # Если cookies нет или невалидны, выполняем логин
            print("\n⚠ Сессия не найдена или невалидна. Выполняется авторизация...")
            print("=" * 80 + "\n")
            
            # Используем текущий браузер для логина (не создаем новый)
            # Для логина нужен видимый браузер
            was_headless = self.headless
            if was_headless:
                print("⚠ Внимание: headless режим временно отключен для логина")
                print("   Браузер будет видимым для ручного входа\n")
                # Перезапускаем драйвер в видимом режиме
                self.driver.quit()
                self.headless = False
                self._setup_driver()
            
            # Выполняем логин в текущем браузере
            login_url = "https://ru.pinterest.com/login/"
            print(f"🌐 Открываю страницу логина: {login_url}")
            self.driver.get(login_url)
            time.sleep(3)
            
            print("\n" + "=" * 80)
            print("🔐 ОЖИДАНИЕ РУЧНОГО ЛОГИНА")
            print("=" * 80)
            print("📌 ВАЖНО: Войдите в свой аккаунт Pinterest в открывшемся браузере!")
            print("   1. Введите ваш email и пароль")
            print("   2. Нажмите кнопку 'Войти' или 'Log in'")
            print("   3. Дождитесь загрузки главной страницы Pinterest")
            print("   4. Сессия будет автоматически сохранена")
            print()
            print(f"⏱ Ожидание: 300 секунд (5 минут)")
            print("=" * 80)
            print()
            
            # Ждем пока пользователь залогинится
            timeout = 300
            start_time = time.time()
            check_interval = 3  # Уменьшаем интервал для более быстрой реакции
            
            while time.time() - start_time < timeout:
                try:
                    # Проверяем доступность драйвера
                    try:
                        current_url = self.driver.current_url
                    except Exception as e:
                        print(f"⚠ Ошибка доступа к драйверу: {e}")
                        time.sleep(check_interval)
                        continue
                    
                    # Если мы не на странице логина, возможно пользователь залогинился
                    if '/login' not in current_url.lower():
                        # Проверяем признаки авторизации (быстро, без долгого ожидания)
                        try:
                            page_source = self.driver.page_source.lower()
                            if 'create' in page_source or 'saved' in page_source or 'profile' in page_source:
                                print("\n✓ Обнаружен успешный вход!")
                                time.sleep(1)  # Минимальная задержка
                                
                                # Сохраняем cookies (быстро)
                                try:
                                    cookies = self.driver.get_cookies()
                                    cookies_dict = {}
                                    for cookie in cookies:
                                        if 'pinterest.com' in cookie.get('domain', ''):
                                            cookies_dict[cookie['name']] = cookie['value']
                                    
                                    if cookies_dict:
                                        cookies_file = self.cookies_file or "pinterest_cookies.json"
                                        from cookies_manager import CookiesManager
                                        CookiesManager.save_to_json(cookies_dict, cookies_file)
                                        print(f"✓ Сессия сохранена: {len(cookies_dict)} cookies")
                                except Exception as e:
                                    print(f"⚠ Ошибка при сохранении cookies: {e}")
                                
                                print("=" * 80 + "\n")
                                return
                        except Exception as e:
                            # Если не удалось проверить, продолжаем ожидание
                            print(f"⚠ Ошибка при проверке авторизации: {e}")
                    
                    # Показываем прогресс (реже, чтобы не спамить)
                    elapsed = int(time.time() - start_time)
                    if elapsed % 30 == 0 and elapsed > 0:
                        remaining = timeout - elapsed
                        minutes = remaining // 60
                        seconds = remaining % 60
                        print(f"⏳ Ожидание входа... Осталось ~{minutes} мин {seconds} сек")
                    
                    time.sleep(check_interval)
                    
                except Exception as e:
                    print(f"⚠ Ошибка при проверке статуса: {e}")
                    time.sleep(check_interval)
            
            print("\n⚠ Время ожидания истекло")
            print("=" * 80 + "\n")
            
            # Возвращаем headless режим если был
            if was_headless:
                self.driver.quit()
                self.headless = True
                self._setup_driver()
        except Exception as e:
            print(f"\n⚠ Ошибка при проверке авторизации: {e}")
            import traceback
            traceback.print_exc()
            print("=" * 80 + "\n")
    
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
        try:
            # Проверяем что окно браузера открыто
            try:
                self.driver.current_url
            except:
                print("⚠ Окно браузера закрыто, перезапускаю...")
                self._setup_driver()
            
            if not self.cookies_file:
                if not load_cookies_from_file("pinterest_cookies.json"):
                    return False
            
            cookies = load_cookies_from_file(self.cookies_file or "pinterest_cookies.json")
            if not cookies:
                return False
            
            # Переходим на Pinterest для установки cookies
            self.driver.get("https://www.pinterest.com")
            
            # Ждем базовой загрузки страницы (оптимизированно)
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                )
            except:
                time.sleep(1)  # Минимальная задержка
            
            # Устанавливаем cookies с проверкой
            cookies_set = 0
            for name, value in cookies.items():
                try:
                    # Проверяем что окно еще открыто
                    self.driver.current_url
                    
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.pinterest.com',
                        'path': '/'
                    })
                    cookies_set += 1
                except Exception as e:
                    # Игнорируем ошибки установки отдельных cookies
                    continue
            
            if cookies_set > 0:
                print(f"✓ Загружено {cookies_set} cookies в браузер")
                # Перезагружаем страницу чтобы применить cookies
                self.driver.refresh()
                time.sleep(2)
                return True
            else:
                print("⚠ Не удалось установить cookies")
                return False
        except Exception as e:
            print(f"⚠ Ошибка при загрузке cookies: {e}")
            return False
    
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
        
        # Проверяем что окно браузера открыто
        try:
            self.driver.current_url
        except:
            print("⚠ Окно браузера закрыто, перезапускаю...")
            self._setup_driver()
        
        # Загружаем cookies если есть (только если еще не загружены)
        if self.cookies_file or os.path.exists("pinterest_cookies.json"):
            if not hasattr(self, '_cookies_loaded') or not self._cookies_loaded:
                self._load_cookies()
                self._cookies_loaded = True
        
        # Переходим на страницу поиска
        print(f"  Переход на страницу поиска...")
        self.driver.get(url)
        
        # Ждем базовой загрузки страницы (не ждем полной загрузки всех ресурсов)
        try:
            WebDriverWait(self.driver, 8).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
            print("  ✓ Страница загружена")
        except:
            print("  ⚠ Страница загружается, продолжаем...")
            time.sleep(2)  # Минимальная задержка вместо долгого ожидания
        
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
                    media_type = "image"  # image, video, gif
                    title = ""
                    description = ""
                    author = ""
                    
                    # Ищем медиа-контент (изображение, видео, GIF)
                    try:
                        # Сначала проверяем, есть ли видео
                        try:
                            video = parent.find_element(By.TAG_NAME, 'video')
                            # Для видео берем постер (превью) или источник
                            image_url = (video.get_attribute('poster') or 
                                        video.get_attribute('src') or
                                        video.get_attribute('data-src'))
                            if image_url:
                                media_type = "video"
                        except:
                            # Если видео нет, ищем изображение
                            try:
                                img = parent.find_element(By.TAG_NAME, 'img')
                                image_url = (img.get_attribute('src') or 
                                           img.get_attribute('data-src') or 
                                           img.get_attribute('data-lazy-src'))
                                
                                # Фильтруем аватары и служебные изображения
                                if image_url:
                                    img_src_lower = image_url.lower()
                                    
                                    # Исключаем аватары и служебные изображения
                                    exclude_patterns = [
                                        '/users/', '/user/', '/avatars/', '/avatar/',
                                        '/profiles/', '/profile/', '/account/',
                                        'avatar', 'profile-pic', 'user-pic',
                                        '/50x50/', '/100x100/', '/75x75/', '/60x60/',
                                        '/32x32/', '/40x40/', '/24x24/',
                                        'logo', 'icon', 'badge', 'button'
                                    ]
                                    
                                    # Проверяем размеры изображения (аватары обычно маленькие)
                                    try:
                                        width = img.get_attribute('width')
                                        height = img.get_attribute('height')
                                        if width and height:
                                            try:
                                                w, h = int(width), int(height)
                                                # Аватары обычно меньше 150x150
                                                if w < 150 and h < 150:
                                                    image_url = ''  # Пропускаем маленькие изображения
                                            except:
                                                pass
                                    except:
                                        pass
                                    
                                    # Проверяем URL на наличие паттернов аватаров
                                    if any(pattern in img_src_lower for pattern in exclude_patterns):
                                        image_url = ''  # Пропускаем аватары
                                    
                                    # Проверяем классы элемента (аватары часто имеют специфические классы)
                                    if image_url:
                                        try:
                                            img_classes = img.get_attribute('class') or ''
                                            parent_classes = parent.get_attribute('class') or ''
                                            all_classes = (img_classes + ' ' + parent_classes).lower()
                                            
                                            avatar_keywords = ['avatar', 'profile', 'user-pic', 'userpic', 'headshot']
                                            if any(keyword in all_classes for keyword in avatar_keywords):
                                                image_url = ''  # Пропускаем аватары
                                        except:
                                            pass
                                
                                # Проверяем, не GIF ли это (только если это не аватар)
                                if image_url:
                                    # Проверяем по URL или атрибутам
                                    img_src_lower = image_url.lower()
                                    if '.gif' in img_src_lower or 'gif' in img.get_attribute('alt', '').lower():
                                        media_type = "gif"
                                    
                                    # Проверяем наличие индикатора GIF/Video на странице
                                    try:
                                        # Ищем элементы с текстом "GIF" или "Video"
                                        indicators = parent.find_elements(By.XPATH, 
                                            ".//*[contains(text(), 'GIF') or contains(text(), 'Video') or contains(text(), 'VIDEO')]")
                                        if indicators:
                                            indicator_text = indicators[0].text.strip().upper()
                                            if 'GIF' in indicator_text:
                                                media_type = "gif"
                                            elif 'VIDEO' in indicator_text or 'VIDEO' in indicator_text:
                                                media_type = "video"
                                    except:
                                        pass
                                
                                if not image_url:
                                    # Пробуем через style background-image
                                    style = img.get_attribute('style') or parent.get_attribute('style')
                                    if style and 'background-image' in style:
                                        import re
                                        match = re.search(r'url\(["\']?([^"\']+)["\']?\)', style)
                                        if match:
                                            bg_url = match.group(1)
                                            # Проверяем, не аватар ли это
                                            bg_url_lower = bg_url.lower()
                                            if not any(pattern in bg_url_lower for pattern in exclude_patterns):
                                                image_url = bg_url
                            except:
                                pass
                        
                        # Если не нашли через теги, пробуем найти через data-атрибуты
                        if not image_url:
                            try:
                                # Ищем элементы с data-video-url или data-gif-url
                                video_url = parent.get_attribute('data-video-url') or parent.get_attribute('data-video-src')
                                gif_url = parent.get_attribute('data-gif-url') or parent.get_attribute('data-gif-src')
                                
                                if video_url:
                                    image_url = video_url
                                    media_type = "video"
                                elif gif_url:
                                    image_url = gif_url
                                    media_type = "gif"
                            except:
                                pass
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
                    
                    # Добавляем пин если есть URL (даже без изображения, т.к. может быть видео/GIF)
                    if pin_url:
                        # Преобразуем URL изображения в прямую ссылку
                        if image_url and 'pinimg.com' in image_url:
                            # Заменяем размеры на originals для полного размера
                            if '/564x/' in image_url:
                                image_url = image_url.replace('/564x/', '/originals/')
                            elif '/236x/' in image_url:
                                image_url = image_url.replace('/236x/', '/originals/')
                        
                        # Для видео и GIF, если нет image_url, оставляем пустым
                        # (ссылка на пин все равно будет работать)
                        pins_data.append({
                            'author': author,
                            'pin_link': pin_url,
                            'image_url': image_url or '',  # Может быть пустым для видео/GIF
                            'media_type': media_type,  # image, video, gif
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
                'media_type': 'image',  # image, video, gif
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
            
            # Ищем медиа-контент (изображение, видео, GIF)
            try:
                # Сначала проверяем наличие видео
                try:
                    video_elements = self.driver.find_elements(By.TAG_NAME, 'video')
                    for video in video_elements:
                        # Для видео берем постер (превью) или источник
                        video_src = (video.get_attribute('poster') or 
                                    video.get_attribute('src') or
                                    video.get_attribute('data-src'))
                        if video_src:
                            pin_data['image_url'] = video_src
                            pin_data['media_type'] = 'video'
                            break
                except:
                    pass
                
                # Если видео не найдено, ищем изображение
                if not pin_data['image_url']:
                    # Паттерны для исключения аватаров
                    exclude_patterns = [
                        '/users/', '/user/', '/avatars/', '/avatar/',
                        '/profiles/', '/profile/', '/account/',
                        'avatar', 'profile-pic', 'user-pic',
                        '/50x50/', '/100x100/', '/75x75/', '/60x60/',
                        '/32x32/', '/40x40/', '/24x24/',
                        'logo', 'icon', 'badge', 'button'
                    ]
                    
                    img_elements = self.driver.find_elements(By.CSS_SELECTOR, 'img[src*="pinimg.com"]')
                    for img in img_elements:
                        src = img.get_attribute('src') or img.get_attribute('data-src')
                        if src and 'pinimg.com' in src:
                            src_lower = src.lower()
                            
                            # Пропускаем аватары и служебные изображения
                            if any(pattern in src_lower for pattern in exclude_patterns):
                                continue
                            
                            # Проверяем размеры (аватары обычно маленькие)
                            try:
                                width = img.get_attribute('width')
                                height = img.get_attribute('height')
                                if width and height:
                                    try:
                                        w, h = int(width), int(height)
                                        if w < 150 and h < 150:
                                            continue  # Пропускаем маленькие изображения
                                    except:
                                        pass
                            except:
                                pass
                            
                            # Преобразуем в оригинал (полный размер)
                            if '/736x/' in src:
                                src = src.replace('/736x/', '/originals/')
                            elif '/564x/' in src:
                                src = src.replace('/564x/', '/originals/')
                            elif '/236x/' in src:
                                src = src.replace('/236x/', '/originals/')
                            
                            pin_data['image_url'] = src
                            
                            # Проверяем, не GIF ли это
                            if '.gif' in src.lower() or 'gif' in img.get_attribute('alt', '').lower():
                                pin_data['media_type'] = 'gif'
                            
                            break
                
                # Если не нашли через теги, пробуем найти через data-атрибуты
                if not pin_data['image_url']:
                    try:
                        # Ищем элементы с data-video-url или data-gif-url
                        main_content = self.driver.find_element(By.TAG_NAME, 'body')
                        video_url = main_content.get_attribute('data-video-url') or main_content.get_attribute('data-video-src')
                        gif_url = main_content.get_attribute('data-gif-url') or main_content.get_attribute('data-gif-src')
                        
                        if video_url:
                            pin_data['image_url'] = video_url
                            pin_data['media_type'] = 'video'
                        elif gif_url:
                            pin_data['image_url'] = gif_url
                            pin_data['media_type'] = 'gif'
                    except:
                        pass
            except:
                pass
            
            return pin_data if pin_data['pin_link'] else None
            
        except Exception as e:
            print(f"Ошибка при парсинге пина {pin_url}: {e}")
            return None
    
    def get_account_info(self) -> Optional[Dict[str, str]]:
        """
        Получает информацию об аккаунте пользователя.
        Переходит на /me и извлекает имя пользователя и другую информацию.
        
        Returns:
            Словарь с информацией об аккаунте или None
        """
        try:
            print("\n" + "=" * 80)
            print("ПОЛУЧЕНИЕ ИНФОРМАЦИИ ОБ АККАУНТЕ")
            print("=" * 80)
            
            # Проверяем что драйвер доступен
            try:
                self.driver.current_url
            except Exception as e:
                print(f"⚠ Ошибка доступа к драйверу: {e}")
                return None
            
            # Переходим на /me
            try:
                self.driver.get(PinterestURLs.USER_ME)
            except Exception as e:
                print(f"⚠ Ошибка при переходе на /me: {e}")
                return None
            
            # Ждем загрузки и редиректа (с таймаутом)
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: '/me' not in d.current_url or 'pinterest.com' in d.current_url
                )
            except Exception as e:
                print(f"⚠ Таймаут ожидания редиректа: {e}")
                time.sleep(2)  # Минимальная задержка вместо долгого ожидания
            
            # URL должен измениться на /username/
            try:
                current_url = self.driver.current_url
            except Exception as e:
                print(f"⚠ Ошибка получения URL: {e}")
                return None
                
            print(f"Текущий URL: {current_url}")
            
            # Извлекаем имя пользователя из URL
            username = None
            if '/me' not in current_url:
                # URL вида: https://ru.pinterest.com/username/ или /username/_pins/
                try:
                    parts = current_url.replace('https://ru.pinterest.com/', '').replace('https://www.pinterest.com/', '').split('/')
                    if parts and parts[0] and parts[0] not in ['', 'login', 'business']:
                        username = parts[0]
                except Exception as e:
                    print(f"⚠ Ошибка извлечения username из URL: {e}")
            
            account_info = {
                'username': username or '',
                'profile_url': current_url,
                'pins_url': f"https://ru.pinterest.com/{username}/_pins/" if username else '',
                'boards_url': f"https://ru.pinterest.com/{username}/_boards/" if username else ''
            }
            
            # Пробуем извлечь дополнительную информацию со страницы (быстро, без долгого ожидания)
            try:
                # Получаем page_source с таймаутом
                page_source = None
                try:
                    page_source = self.driver.page_source
                except Exception as e:
                    print(f"⚠ Не удалось получить page_source: {e}")
                
                if page_source:
                    # Ищем имя пользователя на странице (быстро, без долгого ожидания)
                    if not username:
                        try:
                            # Используем find_elements без ожидания для быстроты
                            username_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                                'h1, [data-test-id="user-name"], [class*="username"], [class*="UserName"]')[:5]
                            for elem in username_elements:
                                try:
                                    text = elem.text.strip()
                                    if text and len(text) < 50 and not text.startswith('http'):
                                        account_info['display_name'] = text
                                        break
                                except:
                                    continue
                        except:
                            pass
                    
                    # Ищем количество пинов и досок (быстро, без долгого ожидания)
                    try:
                        stats_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                            '[class*="stat"], [class*="count"], [class*="Stat"]')[:10]
                        for elem in stats_elements:
                            try:
                                text = elem.text.strip()
                                if 'пин' in text.lower() or 'pin' in text.lower():
                                    account_info['pins_count'] = text
                                elif 'доск' in text.lower() or 'board' in text.lower():
                                    account_info['boards_count'] = text
                            except:
                                continue
                    except:
                        pass
            except Exception as e:
                print(f"⚠ Ошибка при извлечении дополнительной информации: {e}")
                # Продолжаем даже если не удалось получить дополнительную информацию
            
            if username:
                print(f"✓ Имя пользователя: {username}")
                print(f"✓ URL профиля: {account_info['profile_url']}")
                print(f"✓ URL пинов: {account_info['pins_url']}")
                print(f"✓ URL досок: {account_info['boards_url']}")
            else:
                print("⚠ Не удалось определить имя пользователя")
            
            print("=" * 80 + "\n")
            return account_info if username else None
            
        except Exception as e:
            print(f"⚠ Ошибка при получении информации об аккаунте: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def parse_user_pins(self, username: str = None, max_pins: int = None, scroll_times: int = 3) -> List[Dict[str, str]]:
        """
        Парсит пины пользователя.
        
        Args:
            username: Имя пользователя (если None, получает из /me)
            max_pins: Максимальное количество пинов
            scroll_times: Количество прокруток для загрузки контента
            
        Returns:
            Список словарей с данными о пинах
        """
        if max_pins is None:
            max_pins = PinterestConfig.MAX_PINS
        
        # Если username не указан, получаем из /me
        if not username:
            account_info = self.get_account_info()
            if account_info and account_info.get('username'):
                username = account_info['username']
            else:
                print("⚠ Не удалось определить имя пользователя")
                return []
        
        url = PinterestURLs.USER_PINS.format(username=username)
        print(f"Парсинг пинов пользователя: {username}")
        print(f"URL: {url}")
        
        # Переходим на страницу пинов
        self.driver.get(url)
        
        # Ждем загрузки
        try:
            WebDriverWait(self.driver, 8).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
        except:
            time.sleep(2)
        
        # Прокручиваем для загрузки контента
        print("Прокрутка страницы для загрузки контента...")
        for i in range(scroll_times):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            print(f"  Прокрутка {i+1}/{scroll_times}")
        
        # Извлекаем данные
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        pins_data = self._extract_from_html(soup)
        
        # Если пины не найдены, пробуем альтернативный метод
        if not pins_data:
            print("Пины не найдены стандартным методом, пробуем альтернативный...")
            try:
                # Дополнительное ожидание
                time.sleep(2)
                
                # Ищем все ссылки на пины более широким поиском
                all_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="pin"], a[href*="/pin/"]')
                seen_urls = set()
                
                print(f"Найдено потенциальных ссылок: {len(all_links)}")
                
                for link in all_links:
                    try:
                        href = link.get_attribute('href')
                        if not href or '/pin/' not in href:
                            continue
                        
                        # Нормализуем URL
                        if href not in seen_urls:
                            seen_urls.add(href)
                            
                            # Получаем базовую информацию
                            pin_id = href.split('/pin/')[-1].rstrip('/')
                            if not pin_id:
                                continue
                            
                            # Ищем медиа-контент рядом со ссылкой
                            image_url = ''
                            media_type = 'image'
                            try:
                                parent = link.find_element(By.XPATH, './ancestor::div[1]')
                                
                                # Пробуем найти видео
                                try:
                                    video = parent.find_element(By.TAG_NAME, 'video')
                                    image_url = (video.get_attribute('poster') or 
                                               video.get_attribute('src') or
                                               video.get_attribute('data-src'))
                                    if image_url:
                                        media_type = 'video'
                                except:
                                    # Если видео нет, ищем изображение
                                    try:
                                        img = parent.find_element(By.TAG_NAME, 'img')
                                        image_url = img.get_attribute('src') or img.get_attribute('data-src')
                                        
                                        # Фильтруем аватары
                                        if image_url:
                                            img_src_lower = image_url.lower()
                                            exclude_patterns = [
                                                '/users/', '/user/', '/avatars/', '/avatar/',
                                                '/profiles/', '/profile/', '/account/',
                                                'avatar', 'profile-pic', 'user-pic',
                                                '/50x50/', '/100x100/', '/75x75/', '/60x60/',
                                                '/32x32/', '/40x40/', '/24x24/',
                                                'logo', 'icon', 'badge', 'button'
                                            ]
                                            
                                            # Пропускаем аватары
                                            if any(pattern in img_src_lower for pattern in exclude_patterns):
                                                image_url = ''
                                            
                                            # Проверяем размеры
                                            if image_url:
                                                try:
                                                    width = img.get_attribute('width')
                                                    height = img.get_attribute('height')
                                                    if width and height:
                                                        try:
                                                            w, h = int(width), int(height)
                                                            if w < 150 and h < 150:
                                                                image_url = ''  # Пропускаем маленькие изображения
                                                        except:
                                                            pass
                                                except:
                                                    pass
                                        
                                        # Проверяем на GIF
                                        if image_url and ('.gif' in image_url.lower() or 
                                                         'gif' in img.get_attribute('alt', '').lower()):
                                            media_type = 'gif'
                                    except:
                                        pass
                            except:
                                pass
                            
                            pins_data.append({
                                'author': username,
                                'pin_link': href,
                                'image_url': image_url,
                                'media_type': media_type,
                                'title': '',
                                'description': ''
                            })
                    except:
                        continue
                
                print(f"Найдено пинов альтернативным методом: {len(pins_data)}")
            except Exception as e:
                print(f"Ошибка альтернативного метода: {e}")
        
        # Получаем полную информацию о пинах
        if pins_data:
            print("Получение полной информации о пинах...")
            for i, pin in enumerate(pins_data[:max_pins]):
                if pin.get('pin_link') and not pin.get('title'):
                    detail = self.parse_pin_detail(pin['pin_link'])
                    if detail:
                        pins_data[i].update(detail)
                    
                    # Скачиваем изображение если нужно
                    if self.download_images and pins_data[i].get('image_url'):
                        pin_id = pin['pin_link'].split('/pin/')[-1].rstrip('/')
                        local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                        if local_path:
                            pins_data[i]['image_url'] = local_path
                    
                    time.sleep(1)
        
        print(f"Найдено пинов: {len(pins_data)}")
        return pins_data[:max_pins]
    
    def parse_user_boards(self, username: str = None) -> List[Dict[str, str]]:
        """
        Парсит доски пользователя.
        
        Args:
            username: Имя пользователя (если None, получает из /me)
            
        Returns:
            Список словарей с информацией о досках
        """
        # Если username не указан, получаем из /me
        if not username:
            account_info = self.get_account_info()
            if account_info and account_info.get('username'):
                username = account_info['username']
            else:
                print("⚠ Не удалось определить имя пользователя")
                return []
        
        url = PinterestURLs.USER_BOARDS.format(username=username)
        print(f"\nПарсинг досок пользователя: {username}")
        print(f"URL: {url}")
        
        # Переходим на страницу досок
        self.driver.get(url)
        
        # Ждем загрузки
        try:
            WebDriverWait(self.driver, 8).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
        except:
            time.sleep(2)
        
        # Прокручиваем для загрузки всех досок
        print("Прокрутка для загрузки досок...")
        for i in range(3):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        # Дополнительное ожидание для загрузки контента
        time.sleep(3)
        
        boards_data = []
        
        try:
            # Ищем ссылки на доски - более широкий поиск
            board_links = self.driver.find_elements(By.CSS_SELECTOR, f'a[href*="/{username}/"]')
            seen_boards = set()
            
            for link in board_links:
                try:
                    href = link.get_attribute('href')
                    if not href or href in seen_boards:
                        continue
                    
                    # Доски имеют формат: /username/board-name/
                    # Исключаем служебные страницы
                    excluded_paths = ['/_pins/', '/_boards/', '/_created/', '/_saved/', '/pin/', '/settings/', '/account/']
                    is_excluded = any(excluded in href for excluded in excluded_paths)
                    
                    # Исключаем если это просто профиль пользователя
                    is_profile = href.rstrip('/').endswith(f'/{username}')
                    
                    if (f'/{username}/' in href and 
                        not is_excluded and
                        not is_profile and
                        '/pin/' not in href and
                        href.count('/') >= 3):
                        
                        seen_boards.add(href)
                        
                        # Извлекаем название доски
                        board_name = href.rstrip('/').split('/')[-1]
                        
                        # Ищем изображение доски
                        try:
                            parent = link.find_element(By.XPATH, './ancestor::div[1]')
                            img = parent.find_element(By.TAG_NAME, 'img')
                            board_image = img.get_attribute('src') or img.get_attribute('data-src')
                        except:
                            board_image = ''
                        
                        # Ищем описание/количество пинов
                        try:
                            parent = link.find_element(By.XPATH, './ancestor::div[1]')
                            text_elements = parent.find_elements(By.CSS_SELECTOR, 'div, span')
                            board_description = ''
                            pins_count = ''
                            
                            for elem in text_elements:
                                text = elem.text.strip()
                                if text and ('пин' in text.lower() or 'pin' in text.lower()):
                                    pins_count = text
                                elif text and len(text) > 5 and len(text) < 100:
                                    if not board_description:
                                        board_description = text
                        except:
                            board_description = ''
                            pins_count = ''
                        
                        boards_data.append({
                            'board_name': board_name,
                            'board_url': href,
                            'board_image': board_image or '',
                            'description': board_description,
                            'pins_count': pins_count,
                            'username': username
                        })
                except:
                    continue
        
        except Exception as e:
            print(f"⚠ Ошибка при парсинге досок: {e}")
        
        print(f"Найдено досок: {len(boards_data)}")
        return boards_data
    
    def parse_board_pins(self, username: str, board_name: str, max_pins: int = None, scroll_times: int = 3) -> List[Dict[str, str]]:
        """
        Парсит пины из конкретной доски пользователя.
        
        Args:
            username: Имя пользователя
            board_name: Название доски
            max_pins: Максимальное количество пинов
            scroll_times: Количество прокруток
            
        Returns:
            Список словарей с данными о пинах
        """
        if max_pins is None:
            max_pins = PinterestConfig.MAX_PINS
        
        url = PinterestURLs.BOARD_PINS.format(username=username, board_name=board_name)
        print(f"\nПарсинг пинов из доски: {board_name}")
        print(f"URL: {url}")
        
        # Переходим на страницу доски
        self.driver.get(url)
        
        # Ждем загрузки
        try:
            WebDriverWait(self.driver, 8).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
        except:
            time.sleep(2)
        
        # Прокручиваем для загрузки контента
        print("Прокрутка страницы для загрузки контента...")
        for i in range(scroll_times):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            print(f"  Прокрутка {i+1}/{scroll_times}")
        
        # Извлекаем данные
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        pins_data = self._extract_from_html(soup)
        
        # Добавляем информацию о доске к каждому пину
        for pin in pins_data:
            pin['board_name'] = board_name
            pin['board_url'] = url
        
        # Получаем полную информацию о пинах
        if pins_data:
            print("Получение полной информации о пинах...")
            for i, pin in enumerate(pins_data[:max_pins]):
                if pin.get('pin_link') and not pin.get('title'):
                    detail = self.parse_pin_detail(pin['pin_link'])
                    if detail:
                        pins_data[i].update(detail)
                    
                    # Скачиваем изображение если нужно
                    if self.download_images and pins_data[i].get('image_url'):
                        pin_id = pin['pin_link'].split('/pin/')[-1].rstrip('/')
                        local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                        if local_path:
                            pins_data[i]['image_url'] = local_path
                    
                    time.sleep(1)
        
        print(f"Найдено пинов в доске: {len(pins_data)}")
        return pins_data[:max_pins]
    
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
    import json
    from pinterest_parser import PinterestParser
    
    print("=" * 80)
    print("ПАРСЕР PINTEREST")
    print("=" * 80)
    print()
    
    # Загружаем конфиг
    config = {}
    if os.path.exists("config.json"):
        try:
            with open("config.json", 'r', encoding='utf-8') as f:
                config = json.load(f)
        except:
            pass
    
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
    
    # Создаем парсер с автологином если включено в конфиге
    enable_login = config.get("enable_login", False)
    headless = config.get("headless", True)
    download_images = config.get("download_images", True)
    
    # Если включен логин, headless должен быть False для видимости браузера
    if enable_login:
        headless = False
        print("\n" + "=" * 80)
        print("🔐 АВТОРИЗАЦИЯ ВКЛЮЧЕНА")
        print("=" * 80)
        print("Браузер будет открыт для ручного входа в Pinterest")
        print("После успешного входа сессия сохранится автоматически")
        print("=" * 80 + "\n")
    
    parser = PinterestSeleniumParser(
        headless=headless,
        download_images=download_images,
        auto_login=enable_login
    )
    
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
            print("  - Включить авторизацию в config.json (enable_login: true)")
            print("  - Добавить cookies для авторизации")
            print("  - Изменить поисковый запрос")
            print("  - Проверить интернет-соединение")
    finally:
        parser.close()
