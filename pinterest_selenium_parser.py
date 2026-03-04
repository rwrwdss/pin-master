"""
Парсер Pinterest с использованием Selenium для динамической загрузки контента.
Pinterest использует JavaScript для загрузки данных, поэтому нужен браузер.
"""

import time
import json
import os
import uuid
import requests
import platform
import subprocess
from urllib.parse import urlparse
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from chromedriver_helper import get_chromedriver_path
from bs4 import BeautifulSoup

from pinterest_selectors import PinterestSelectors, PinterestURLs, PinterestConfig
from cookies_manager import load_cookies_from_file, CookiesManager
from pinterest_auth import PinterestAuth

try:
    from path_utils import get_cookies_path, get_images_dir
    USE_PATH_UTILS = True
except ImportError:
    USE_PATH_UTILS = False


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
        self.login_successful = False
        if self.auto_login:
            print(f"\n🔐 Авторизация включена (auto_login={self.auto_login})")
            self.login_successful = self._ensure_authentication()
        else:
            print(f"\nℹ Авторизация отключена (auto_login={self.auto_login})")
        
        # Создаем папку для изображений если нужно
        if self.download_images:
            self._create_images_directory()
    
    def _close_existing_browsers(self):
        """Закрывает существующие окна браузера от парсера"""
        try:
            # Закрываем текущий драйвер если он существует
            if self.driver:
                try:
                    print("  Закрываю существующий браузер...")
                    self.driver.quit()
                    print("  ✓ Существующий браузер закрыт")
                except:
                    pass
                finally:
                    self.driver = None
            
            # Закрываем процессы Chrome, связанные с Selenium/chromedriver
            if platform.system() == 'Darwin':  # macOS
                try:
                    import subprocess
                    closed_count = 0
                    
                    # Метод 1: Ищем процессы Chrome с remote-debugging-port (признак Selenium)
                    try:
                        result = subprocess.run(
                            ['pgrep', '-f', 'remote-debugging-port'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            pids = [p for p in result.stdout.strip().split('\n') if p]
                            for pid in pids:
                                try:
                                    # Проверяем что это действительно Chrome процесс
                                    ps_result = subprocess.run(
                                        ['ps', '-p', pid, '-o', 'comm='],
                                        capture_output=True,
                                        text=True,
                                        timeout=2
                                    )
                                    if 'Chrome' in ps_result.stdout or 'Google Chrome' in ps_result.stdout:
                                        subprocess.run(['kill', '-9', pid], timeout=2, 
                                                     stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                                        closed_count += 1
                                except:
                                    pass
                    except:
                        pass
                    
                    # Метод 2: Ищем процессы Chrome с аргументами Selenium
                    try:
                        result = subprocess.run(
                            ['pgrep', '-f', '--disable-blink-features=AutomationControlled'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            pids = [p for p in result.stdout.strip().split('\n') if p]
                            for pid in pids:
                                try:
                                    # Проверяем что это Chrome и еще не закрыт
                                    ps_result = subprocess.run(
                                        ['ps', '-p', pid, '-o', 'comm='],
                                        capture_output=True,
                                        text=True,
                                        timeout=2
                                    )
                                    if 'Chrome' in ps_result.stdout or 'Google Chrome' in ps_result.stdout:
                                        subprocess.run(['kill', '-9', pid], timeout=2, 
                                                     stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                                        closed_count += 1
                                except:
                                    pass
                    except:
                        pass
                    
                    if closed_count > 0:
                        print(f"  ✓ Закрыто {closed_count} старых процессов Chrome от парсера")
                        time.sleep(1)  # Даем время для закрытия процессов
                    
                except Exception as e:
                    print(f"  ⚠ Ошибка при закрытии процессов Chrome: {e}")
        except Exception as e:
            print(f"  ⚠ Ошибка при закрытии старых браузеров: {e}")
    
    def close_browser(self):
        """Закрывает только окно браузера парсера (cookies уже сохранены)."""
        try:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
        except Exception:
            pass
    
    def _setup_driver(self):
        """Настраивает и запускает Chrome драйвер"""
        print("\n" + "=" * 80)
        print("НАСТРОЙКА CHROME ДРАЙВЕРА")
        print("=" * 80)
        
        # Закрываем старые окна браузера перед открытием нового
        self._close_existing_browsers()
        
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
            print("✓ Режим: headless (фоновый)")
        else:
            print("✓ Режим: обычный (браузер виден)")
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(f'user-agent={PinterestConfig.USER_AGENT}')
        chrome_options.add_argument('--window-size=1200,1080')
        
        # Дополнительные аргументы для стабильности
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-ipc-flooding-protection')
        chrome_options.add_argument('--disable-hang-monitor')
        chrome_options.add_argument('--disable-prompt-on-repost')
        chrome_options.add_argument('--disable-sync')
        chrome_options.add_argument('--disable-translate')
        chrome_options.add_argument('--disable-features=TranslateUI')
        chrome_options.add_argument('--disable-component-extensions-with-background-page')
        chrome_options.add_argument('--disable-browser-side-navigation')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('--disable-notifications')
        
        # Дополнительные аргументы для macOS
        if platform.system() == 'Darwin':
            print("✓ Платформа: macOS (Darwin)")
            chrome_options.add_argument('--disable-gpu')
            # Используем случайный порт для избежания конфликтов
            import random
            debug_port = random.randint(9223, 9999)
            chrome_options.add_argument(f'--remote-debugging-port={debug_port}')
            print(f"✓ Remote debugging port: {debug_port}")
            # Для macOS может потребоваться явное указание пути к Chrome
            chrome_paths = [
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary'
            ]
            chrome_found = False
            for chrome_path in chrome_paths:
                if os.path.exists(chrome_path):
                    chrome_options.binary_location = chrome_path
                    print(f"✓ Найден Chrome: {chrome_path}")
                    chrome_found = True
                    break
            
            if not chrome_found:
                print("⚠ Chrome не найден в стандартных местах")
        
        # Отключаем логи
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            print("\n📥 Установка/получение Chrome драйвера...")
            driver_path = get_chromedriver_path()
            print(f"✓ Путь к драйверу: {driver_path}")
            
            # Для macOS: убираем карантин и проверяем кодовую подпись
            if platform.system() == 'Darwin':
                # Множественные попытки удаления карантина
                quarantine_removed = False
                for attempt in range(3):
                    try:
                        # Способ 1: Удаляем конкретный атрибут карантина
                        result = subprocess.run(
                            ['xattr', '-d', 'com.apple.quarantine', driver_path],
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            timeout=10
                        )
                        if result.returncode == 0:
                            quarantine_removed = True
                            print(f"✓ Карантин удален (попытка {attempt + 1})")
                            break
                    except Exception as e:
                        pass
                    
                    try:
                        # Способ 2: Удаляем все расширенные атрибуты
                        result = subprocess.run(
                            ['xattr', '-c', driver_path],
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            timeout=10
                        )
                        if result.returncode == 0:
                            quarantine_removed = True
                            print(f"✓ Все расширенные атрибуты удалены (попытка {attempt + 1})")
                            break
                    except Exception as e:
                        pass
                    
                    if attempt < 2:
                        time.sleep(0.5)
                
                # Проверяем права доступа на файл
                if os.path.exists(driver_path):
                    # Делаем файл исполняемым
                    try:
                        os.chmod(driver_path, 0o755)
                        print("✓ Права доступа установлены на драйвер")
                    except Exception as e:
                        print(f"⚠ Не удалось установить права: {e}")
                
                # Дополнительная проверка: пробуем запустить драйвер напрямую для проверки
                if not quarantine_removed:
                    print("⚠ Не удалось автоматически удалить карантин")
                    print(f"  Путь к драйверу: {driver_path}")
                    print("  Попробуйте выполнить вручную в терминале:")
                    print(f"  xattr -d com.apple.quarantine '{driver_path}'")
                    print(f"  или")
                    print(f"  xattr -c '{driver_path}'")
            
            # Дополнительные настройки для Service в macOS
            if platform.system() == 'Darwin':
                # Убеждаемся, что путь к драйверу абсолютный
                driver_path = os.path.abspath(driver_path)
                print(f"✓ Абсолютный путь к драйверу: {driver_path}")
                # Подпись ad-hoc — без неё macOS может убивать процесс (SIGKILL -9)
                try:
                    subprocess.run(
                        ['codesign', '--force', '--sign', '-', driver_path],
                        stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=10
                    )
                    print("✓ Chrome драйвер подписан (ad-hoc) для macOS")
                except Exception:
                    pass
            
            print("\n🚀 Запуск Chrome драйвера...")
            service = Service(driver_path)
            
            # Пробуем запустить с несколькими попытками
            max_attempts = 3
            driver_created = False
            
            for attempt in range(max_attempts):
                try:
                    if attempt > 0:
                        print(f"Попытка {attempt + 1}/{max_attempts}...")
                        time.sleep(2)  # Небольшая задержка между попытками
                    
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    driver_created = True
                    print("✓ Chrome драйвер успешно запущен!")
                    print("=" * 80 + "\n")
                    break
                except Exception as e:
                    error_str = str(e)
                    if "unable to connect to renderer" in error_str.lower() or "session not created" in error_str.lower():
                        if attempt < max_attempts - 1:
                            print(f"⚠ Попытка {attempt + 1} не удалась: {error_str[:100]}")
                            print("Пробую с дополнительными флагами...")
                            # Добавляем дополнительные флаги для следующей попытки
                            chrome_options.add_argument('--single-process')
                            chrome_options.add_argument('--disable-software-rasterizer')
                            continue
                        else:
                            raise
                    else:
                        raise
            
            if not driver_created:
                raise RuntimeError("Не удалось запустить Chrome драйвер после всех попыток")
                
        except Exception as e:
            error_msg = f"Ошибка при запуске Chrome драйвера: {e}"
            print(error_msg)
            print("Убедитесь, что Chrome установлен на системе")
            
            # Дополнительная информация для macOS
            if platform.system() == 'Darwin':
                print("\nДля macOS:")
                print("1. Убедитесь, что Google Chrome установлен в /Applications/")
                
                # Пробуем найти точный путь к драйверу
                try:
                    driver_path = get_chromedriver_path()
                    print(f"2. Путь к драйверу: {driver_path}")
                    print("3. Если драйвер заблокирован, выполните в терминале:")
                    print(f"   xattr -d com.apple.quarantine '{driver_path}'")
                    print("   или")
                    print(f"   xattr -c '{driver_path}'")
                    print("   или")
                    print(f"   chmod +x '{driver_path}'")
                    
                    # Проверяем наличие карантина
                    try:
                        result = subprocess.run(
                            ['xattr', '-l', driver_path],
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            timeout=5
                        )
                        if result.returncode == 0 and b'quarantine' in result.stdout:
                            print(f"\n⚠ Обнаружен карантин на драйвере!")
                            print(f"   Выполните: xattr -d com.apple.quarantine '{driver_path}'")
                    except:
                        pass
                except:
                    print("2. Не удалось определить путь к драйверу")
                    print("   Попробуйте найти драйвер вручную:")
                    print("   find ~/.wdm -name chromedriver -type f")
            
            print("=" * 80 + "\n")
            self.driver = None
            raise RuntimeError(f"Не удалось инициализировать Chrome драйвер. Убедитесь, что Chrome установлен. Детали: {e}")
    
    def _ensure_authentication(self) -> bool:
        """
        Проверяет авторизацию и выполняет логин если нужно
        
        Returns:
            True если авторизация успешна, False иначе
        """
        try:
            print("\n" + "=" * 80)
            print("ПРОВЕРКА АВТОРИЗАЦИИ")
            print("=" * 80)
            
            # Проверяем наличие cookies файла
            if USE_PATH_UTILS and not self.cookies_file:
                cookies_file = str(get_cookies_path())
            else:
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
                        return True
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
                    if '/login' not in current_url.lower() and '/signup' not in current_url.lower():
                        # Проверяем признаки авторизации (быстро, без долгого ожидания)
                        try:
                            page_source = self.driver.page_source.lower()
                            current_url_lower = current_url.lower()
                            
                            # Проверяем различные признаки авторизации:
                            # 1. URL профиля пользователя (например, /uazis1/, /username/)
                            # 2. Наличие кнопок/элементов авторизованного пользователя
                            # 3. Отсутствие формы логина
                            
                            # Проверка URL профиля (паттерн: /username/ или /u/username/)
                            url_parts = [x for x in current_url_lower.split('/') if x and x not in ['https:', '', 'www.', 'ru.', 'pinterest.com', 'pinterest']]
                            is_profile_url = (
                                len(url_parts) > 0 and 
                                (url_parts[0] not in ['login', 'signup', 'business', 'help', 'about', 'terms', 'privacy']) and
                                ('pinterest.com' in current_url_lower)
                            )
                            
                            # Проверка содержимого страницы
                            has_auth_indicators = (
                                'create' in page_source or 
                                'saved' in page_source or 
                                'profile' in page_source or
                                'follow' in page_source or
                                'boards' in page_source or
                                'pins' in page_source
                            )
                            
                            # Проверка отсутствия формы логина
                            no_login_form = (
                                'log in' not in page_source and 
                                'войти' not in page_source and 
                                'sign up' not in page_source and
                                'signup' not in current_url_lower
                            )
                            
                            is_authorized = (is_profile_url or has_auth_indicators) and no_login_form
                            
                            if is_authorized:
                                print("\n✓ Обнаружен успешный вход!")
                                print(f"   URL: {current_url}")
                                time.sleep(2)  # Даем время для полной загрузки страницы
                                
                                # Сохраняем cookies (быстро)
                                try:
                                    cookies = self.driver.get_cookies()
                                    cookies_dict = {}
                                    for cookie in cookies:
                                        if 'pinterest.com' in cookie.get('domain', ''):
                                            cookies_dict[cookie['name']] = cookie['value']
                                    
                                    if cookies_dict:
                                        if USE_PATH_UTILS and not self.cookies_file:
                                            cookies_file = str(get_cookies_path())
                                        else:
                                            cookies_file = self.cookies_file or "pinterest_cookies.json"
                                        from cookies_manager import CookiesManager
                                        CookiesManager.save_to_json(cookies_dict, cookies_file)
                                        print(f"✓ Сессия сохранена: {len(cookies_dict)} cookies в {cookies_file}")
                                except Exception as e:
                                    print(f"⚠ Ошибка при сохранении cookies: {e}")
                                
                                # Закрываем браузер после сохранения cookies
                                print("✓ Закрываю браузер...")
                                try:
                                    self.driver.quit()
                                    print("✓ Браузер закрыт")
                                except Exception as e:
                                    print(f"⚠ Ошибка при закрытии браузера: {e}")
                                
                                # Если был headless режим, перезапускаем в headless
                                if was_headless:
                                    print("🔄 Перезапускаю браузер в headless режиме...")
                                    self.headless = True
                                    self._setup_driver()
                                    # Загружаем сохраненные cookies в новый браузер
                                    if cookies_dict:
                                        print("  Загружаю сохраненные cookies...")
                                        self.driver.get("https://www.pinterest.com")
                                        time.sleep(2)
                                        for name, value in cookies_dict.items():
                                            try:
                                                self.driver.add_cookie({
                                                    'name': name,
                                                    'value': value,
                                                    'domain': '.pinterest.com',
                                                    'path': '/'
                                                })
                                            except:
                                                pass
                                        self.driver.refresh()
                                        time.sleep(2)
                                        print("✓ Cookies загружены в headless браузер")
                                else:
                                    # Если не был headless, просто создаем новый драйвер для дальнейшей работы
                                    print("🔄 Перезапускаю браузер для работы...")
                                    self._setup_driver()
                                    # Загружаем сохраненные cookies
                                    if cookies_dict:
                                        print("  Загружаю сохраненные cookies...")
                                        self.driver.get("https://www.pinterest.com")
                                        time.sleep(2)
                                        for name, value in cookies_dict.items():
                                            try:
                                                self.driver.add_cookie({
                                                    'name': name,
                                                    'value': value,
                                                    'domain': '.pinterest.com',
                                                    'path': '/'
                                                })
                                            except:
                                                pass
                                        self.driver.refresh()
                                        time.sleep(2)
                                        print("✓ Cookies загружены")
                                
                                print("=" * 80 + "\n")
                                return True
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
            
            # Закрываем браузер если авторизация не удалась
            try:
                self.driver.quit()
                print("✓ Браузер закрыт")
            except:
                pass
            
            # Возвращаем headless режим если был
            if was_headless:
                self.headless = True
                self._setup_driver()
            
            return False
        except Exception as e:
            print(f"\n⚠ Ошибка при проверке авторизации: {e}")
            import traceback
            traceback.print_exc()
            print("=" * 80 + "\n")
            return False
    
    def _create_images_directory(self):
        """Создает папку с рандомным названием для сохранения изображений"""
        random_name = str(uuid.uuid4())[:8]
        if USE_PATH_UTILS:
            images_base = get_images_dir()
            self.images_dir = str(images_base / f"pinterest_images_{random_name}")
        else:
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
    
    def _get_pin_via_api(self, pin_id: str, pin_url: str) -> Optional[Dict[str, str]]:
        """
        Получает название и описание пина через внутренний API Pinterest (PinResource/get).
        Параметры и заголовки как в DevTools → Network. При ошибке возвращает None.
        """
        try:
            selenium_cookies = self.driver.get_cookies()
            cookies_dict = {c['name']: c['value'] for c in selenium_cookies}
            if not cookies_dict or '_pinterest_sess' not in cookies_dict:
                file_cookies = load_cookies_from_file(self.cookies_file or "pinterest_cookies.json") if (self.cookies_file or os.path.exists("pinterest_cookies.json")) else {}
                if file_cookies:
                    cookies_dict = file_cookies
            if not cookies_dict:
                return None
            
            source_url = f"/pin/{pin_id}/"
            api_url = "https://ru.pinterest.com/resource/PinResource/get/"
            # data как в DevTools: options с add_fields, noCache, fetch_visual_search_objects, get_page_metadata
            params = {
                "source_url": source_url,
                "data": json.dumps({
                    "options": {
                        "id": pin_id,
                        "field_set_key": "auth_web_main_pin",
                        "add_fields": "pin.gen_ai_topics",
                        "noCache": True,
                        "fetch_visual_search_objects": True,
                        "get_page_metadata": False,
                    },
                    "context": {}
                })
            }
            headers = {
                "User-Agent": PinterestConfig.USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": "https://ru.pinterest.com/",
                "X-Requested-With": "XMLHttpRequest",
                "X-Pinterest-AppState": "active",
                "X-Pinterest-Source-Url": source_url,
                "X-Pinterest-PWS-Handler": "www/pin/[id].js",
                "X-App-Version": "53c3e54",
            }
            r = requests.get(api_url, params=params, headers=headers, cookies=cookies_dict, timeout=15)
            r.raise_for_status()
            data = r.json()
            res = data.get("resource_response") or {}
            pin_data = res.get("data")
            if not isinstance(pin_data, dict):
                return None
            
            # Заголовок пина: title (как на странице пина)
            title = (pin_data.get("title") or pin_data.get("grid_title") or pin_data.get("name") or "").strip()
            # Описание: description или seo_alt_text (Pinterest иногда кладёт текст в seo_alt_text)
            desc = (pin_data.get("description") or pin_data.get("seo_alt_text") or pin_data.get("description_html") or "").strip()
            if desc and desc.startswith("<"):
                try:
                    desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ", strip=True)
                except Exception:
                    pass
            
            image_url = ""
            images = pin_data.get("images") or {}
            if isinstance(images, dict):
                orig = images.get("orig") or images.get("736x") or images.get("564x")
                if isinstance(orig, dict) and orig.get("url"):
                    image_url = orig["url"]
            
            # Аналитика из ответа API
            repin_count = pin_data.get("repin_count")
            if repin_count is None:
                repin_count = ""
            comments_disabled = pin_data.get("comments_disabled")
            if comments_disabled is None:
                comments_disabled = ""
            else:
                comments_disabled = "true" if comments_disabled else "false"
            agg = pin_data.get("aggregated_pin_data") or {}
            agg_stats = agg.get("aggregated_stats") or {} if isinstance(agg, dict) else {}
            saves = agg_stats.get("saves") if isinstance(agg_stats, dict) else ""
            done = agg_stats.get("done") if isinstance(agg_stats, dict) else ""
            comment_count = agg.get("comment_count") if isinstance(agg, dict) else ""
            reaction_counts = pin_data.get("reaction_counts") or {}
            if isinstance(reaction_counts, dict):
                try:
                    likes = sum(int(v) for v in reaction_counts.values())
                except (TypeError, ValueError):
                    likes = ""
            else:
                likes = ""
            created_at = (pin_data.get("created_at") or "").strip()
            user_obj = pin_data.get("user") or pin_data.get("creator") or {}
            share_count = user_obj.get("share_count") if isinstance(user_obj, dict) else ""
            if share_count is None:
                share_count = pin_data.get("share_count", "")
            if share_count is None:
                share_count = ""
            
            return {
                "pin_link": pin_url,
                "title": title,
                "description": desc,
                "image_url": image_url,
                "media_type": pin_data.get("media", {}).get("type", "image") if isinstance(pin_data.get("media"), dict) else "image",
                "author": (pin_data.get("creator", {}) or {}).get("username", "") if isinstance(pin_data.get("creator"), dict) else "",
                "repin_count": repin_count,
                "comments_disabled": comments_disabled,
                "saves": saves,
                "done": done,
                "comment_count": comment_count,
                "likes": likes,
                "created_at": created_at,
                "share_count": share_count,
            }
        except Exception as e:
            return None
    
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
    
    def is_driver_alive(self) -> bool:
        """Проверяет, что сессия драйвера ещё жива (браузер не закрыт)."""
        if not getattr(self, 'driver', None):
            return False
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False
    
    def load_cookies_from_file_path(self, file_path: str) -> bool:
        """Загружает cookies из указанного файла в текущий драйвер (для переключения аккаунта)."""
        if not os.path.exists(file_path):
            return False
        if not self.is_driver_alive():
            return False
        try:
            self.driver.get("https://www.pinterest.com")
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                )
            except Exception:
                time.sleep(1)
            self.driver.delete_all_cookies()
            cookies = load_cookies_from_file(file_path)
            if not cookies:
                return False
            for name, value in cookies.items():
                try:
                    self.driver.add_cookie({
                        'name': name, 'value': value,
                        'domain': '.pinterest.com', 'path': '/'
                    })
                except Exception:
                    continue
            self.driver.refresh()
            time.sleep(2)
            return True
        except Exception as e:
            print(f"⚠ Ошибка load_cookies_from_file_path: {e}")
            return False
    
    def login_with_credentials(self, email: str, password: str, save_cookies_to: Optional[str] = None) -> bool:
        """
        Вход по логину и паролю: заполняет форму на странице Pinterest и сохраняет cookies.
        save_cookies_to: путь к файлу для сохранения cookies (если None — основной файл).
        """
        if not self.driver or not email or not password:
            return False
        login_url = "https://ru.pinterest.com/login/"
        try:
            self.driver.get(login_url)
            time.sleep(3)
            email_field = None
            for sel in ('input[type="email"]', 'input[name="email"]', 'input[id*="email"]', 'input[placeholder*="email" i]', 'input[placeholder*="почт" i]'):
                try:
                    email_field = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    if email_field and email_field.is_displayed():
                        break
                except Exception:
                    continue
            if not email_field:
                print("⚠ Не найдено поле email")
                return False
            email_field.clear()
            email_field.send_keys(email)
            time.sleep(0.5)
            pwd_field = None
            for sel in ('input[type="password"]', 'input[name="password"]', 'input[id*="password"]'):
                try:
                    pwd_field = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if pwd_field and pwd_field.is_displayed():
                        break
                except Exception:
                    continue
            if not pwd_field:
                print("⚠ Не найдено поле пароля")
                return False
            pwd_field.clear()
            pwd_field.send_keys(password)
            time.sleep(0.5)
            login_btn = None
            try:
                login_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Войти') or contains(text(), 'Log in') or @type='submit']")
            except Exception:
                pass
            if not login_btn:
                try:
                    login_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                except Exception:
                    pass
            if not login_btn or not login_btn.is_displayed():
                print("⚠ Не найдена кнопка входа")
                return False
            login_btn.click()
            time.sleep(5)
            current_url = self.driver.current_url
            if '/login' in current_url.lower():
                print("⚠ Вход не удался (остались на странице логина)")
                return False
            cookies_raw = self.driver.get_cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies_raw if 'pinterest.com' in c.get('domain', '')}
            if not cookies_dict:
                print("⚠ Не удалось получить cookies после входа")
                return False
            out_path = save_cookies_to
            if not out_path and USE_PATH_UTILS:
                out_path = str(get_cookies_path())
            if not out_path:
                out_path = self.cookies_file or "pinterest_cookies.json"
            out_path = str(out_path)
            try:
                d = os.path.dirname(out_path)
                if d:
                    os.makedirs(d, exist_ok=True)
            except Exception:
                pass
            CookiesManager.save_to_json(cookies_dict, out_path)
            print(f"✓ Вход выполнен, cookies сохранены: {out_path}")
            return True
        except Exception as e:
            print(f"⚠ Ошибка при входе по логину/паролю: {e}")
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
            WebDriverWait(self.driver, 5).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
            print("  ✓ Страница загружена")
        except:
            print("  ⚠ Страница загружается, продолжаем...")
            time.sleep(1)
        
        # Динамическая прокрутка: накапливаем уникальные URL пинов по pin_id (один пин = одна запись, без дублей www/ru)
        def _pin_id_from_url(u: str) -> str:
            if not u or "/pin/" not in u:
                return ""
            return u.split("/pin/")[-1].split("/")[0].split("?")[0].strip()
        
        def _canonical_pin_url(u: str) -> str:
            pid = _pin_id_from_url(u)
            return f"https://ru.pinterest.com/pin/{pid}/" if pid else u
        
        print(f"Прокрутка страницы для загрузки контента (цель: {max_pins} пинов)...")
        max_scrolls = min(max(scroll_times * 5, max_pins // 3, 30), 120)  # не более 120 прокруток даже для 1200+ пинов
        seen_pin_ids = set()
        pin_urls_ordered = []  # порядок первого появления, без дублей по pin_id
        last_count = 0
        no_progress_count = 0
        
        for i in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.2 if i < 5 else 1.0)
            
            try:
                pin_elements = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/pin/"]')
                for elem in pin_elements:
                    try:
                        href = elem.get_attribute('href')
                    except StaleElementReferenceException:
                        continue
                    if not href:
                        continue
                    href = href.split('?')[0].rstrip('/')
                    if not href.startswith('http'):
                        href = ('https://www.pinterest.com' + href) if href.startswith('/') else ('https://www.pinterest.com/' + href)
                    pin_id = _pin_id_from_url(href)
                    if not pin_id or pin_id in seen_pin_ids:
                        continue
                    seen_pin_ids.add(pin_id)
                    pin_urls_ordered.append(_canonical_pin_url(href))
                
                pins_found = len(pin_urls_ordered)
                print(f"  Прокрутка {i+1}/{max_scrolls}: найдено {pins_found} уникальных пинов")
                
                if pins_found >= max_pins:
                    print(f"  ✓ Найдено достаточно пинов ({pins_found} >= {max_pins})")
                    break
                
                if pins_found == last_count:
                    no_progress_count += 1
                    if no_progress_count >= 5:
                        print(f"  ⚠ Нет прогресса после {no_progress_count} прокруток, останавливаемся")
                        break
                else:
                    no_progress_count = 0
                    last_count = pins_found
            except Exception as e:
                print(f"  ⚠ Ошибка при проверке количества пинов: {e}")
                time.sleep(1)
        
        # Собираем пины: либо из накопленных URL (надёжно при виртуализации), либо из HTML
        pins_data = []
        if pin_urls_ordered:
            pins_data = [{"pin_link": url} for url in pin_urls_ordered[:max_pins]]
            print(f"Используем {len(pins_data)} пинов из накопленных при прокрутке")
        if not pins_data:
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            pins_data = self._extract_from_html(soup)
        if not pins_data:
            pins_data = self._extract_from_js_data()
        
        # Название и описание — только через API Pinterest (PinResource/get). Картинку при отсутствии в API — со страницы пина.
        if pins_data:
            to_fetch = pins_data[:max_pins]
            print(f"Получение данных о пинах ({len(to_fetch)} шт., API для названия/описания)...")
            for i, pin in enumerate(to_fetch):
                if (i + 1) % 50 == 0 or i == 0:
                    print(f"  Обработано пинов: {i+1}/{len(to_fetch)}")
                pin_link = pin.get('pin_link')
                if not pin_link:
                    continue
                pin_id = pin_link.split('/pin/')[-1].split('/')[0].strip()
                if not pin_id:
                    continue
                
                # Title и description только из API — без fallback на разбор HTML
                detail_api = self._get_pin_via_api(pin_id, pin_link)
                if detail_api:
                    pins_data[i]['title'] = (detail_api.get('title') or '').strip()
                    pins_data[i]['description'] = (detail_api.get('description') or '').strip()
                    pins_data[i]['image_url'] = (detail_api.get('image_url') or '').strip()
                    pins_data[i]['media_type'] = detail_api.get('media_type', 'image') or 'image'
                    if detail_api.get('author'):
                        pins_data[i]['author'] = detail_api['author']
                    pins_data[i]['repin_count'] = detail_api.get('repin_count', '')
                    pins_data[i]['comments_disabled'] = detail_api.get('comments_disabled', '')
                    pins_data[i]['saves'] = detail_api.get('saves', '')
                    pins_data[i]['done'] = detail_api.get('done', '')
                    pins_data[i]['comment_count'] = detail_api.get('comment_count', '')
                    pins_data[i]['likes'] = detail_api.get('likes', '')
                    pins_data[i]['created_at'] = detail_api.get('created_at', '')
                    pins_data[i]['share_count'] = detail_api.get('share_count', '')
                else:
                    pins_data[i]['title'] = ''
                    pins_data[i]['description'] = ''
                    pins_data[i]['image_url'] = ''
                    pins_data[i]['repin_count'] = ''
                    pins_data[i]['comments_disabled'] = ''
                    pins_data[i]['saves'] = ''
                    pins_data[i]['done'] = ''
                    pins_data[i]['comment_count'] = ''
                    pins_data[i]['likes'] = ''
                    pins_data[i]['created_at'] = ''
                    pins_data[i]['share_count'] = ''
                
                # Если API не отдал картинку — открываем страницу пина только ради image_url (title/description не берём)
                if not pins_data[i].get('image_url'):
                    detail = self.parse_pin_detail(pin_link)
                    if detail and detail.get('image_url'):
                        pins_data[i]['image_url'] = detail.get('image_url', '') or ''
                        pins_data[i]['media_type'] = detail.get('media_type', 'image') or 'image'
                    time.sleep(0.3)
                
                if self.download_images and pins_data[i].get('image_url'):
                    local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                    if local_path:
                        pins_data[i]['image_url'] = local_path
                    else:
                        pins_data[i]['image_url'] = ''
                
                time.sleep(0.25)
        
        # Оставляем только пины с изображением и убираем дубли по pin_id (один пин — одна строка в результате)
        pins_with_image = [p for p in pins_data if (p.get('image_url') or p.get('image_path') or '').strip()]
        seen_ids = set()
        unique_pins = []
        for p in pins_with_image:
            link = p.get('pin_link') or ''
            pid = link.split('/pin/')[-1].split('/')[0].split('?')[0].strip() if '/pin/' in link else ''
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                unique_pins.append(p)
        print(f"Найдено пинов: {len(unique_pins)} (только с изображением, без дублей)")
        return unique_pins[:max_pins]
    
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
            # Ждём появления контента пина (Pinterest подгружает его через JS)
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-test-id="pin-detail"], [data-test-id="pin-title"], .pinDetail, .PinDetail, h1'))
                )
            except Exception:
                pass
            
            pin_data = {
                'author': '',
                'pin_link': pin_url,
                'image_url': '',
                'media_type': 'image',  # image, video, gif
                'title': '',
                'description': ''
            }
            
            # Слова из навигации/интерфейса — не брать как название пина
            title_exclude = [
                'Pinterest', 'Save', 'Сохранить', 'Главная', 'Home', 'Main', 'Explore',
                'Search', 'Поиск', 'Войти', 'Login', 'Sign up', 'Регистрация', 'Create',
                'Создать', 'Messages', 'Сообщения', 'Notifications', 'Уведомления',
                'Profile', 'Профиль', 'Settings', 'Настройки', 'Ideas', 'Идеи'
            ]
            
            # Сначала пытаемся развернуть описание, нажав на кнопку "больше"
            expanded = self._expand_description()
            if expanded:
                time.sleep(0.8)
            
            # Ищем контейнер контента пина (чтобы не брать текст из шапки/сайдбара)
            pin_container = None
            for container_sel in ['[data-test-id="pin-detail"]', '[data-test-id="closeup-detail-container"]', 'div[class*="PinDetail"]', 'div[class*="pinDetail"]', 'main[role="main"]']:
                try:
                    els = self.driver.find_elements(By.CSS_SELECTOR, container_sel)
                    for el in els:
                        if el.is_displayed() and el.size.get('height', 0) > 100:
                            pin_container = el
                            break
                    if pin_container:
                        break
                except Exception:
                    continue
            
            def _find_in_container(container, selectors):
                """Ищет текст по селекторам внутри контейнера или по всей странице."""
                scope = container if container else self.driver
                for sel in selectors:
                    try:
                        elems = scope.find_elements(By.CSS_SELECTOR, sel)
                        for elem in elems:
                            try:
                                if not elem.is_displayed():
                                    continue
                            except Exception:
                                continue
                            text = elem.text.strip()
                            if text:
                                return text
                    except Exception:
                        continue
                return ''
            
            # Название — только из контейнера пина или по приоритетным селекторам
            title_selectors = [
                '[data-test-id="pin-title"]',
                'h1',
                '.pinTitle',
                'div[class*="title"] h1',
                'div[class*="Title"] h1',
            ]
            raw_title = _find_in_container(pin_container, title_selectors)
            if not raw_title:
                raw_title = _find_in_container(None, title_selectors)
            if raw_title and len(raw_title) < 200 and not raw_title.startswith('http'):
                if raw_title not in title_exclude and not any(raw_title == x or raw_title.lower() == x.lower() for x in title_exclude):
                    pin_data['title'] = raw_title
            
            # Fallback: og:title из meta (часто совпадает с названием пина)
            if not pin_data['title']:
                try:
                    og_title = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
                    t = (og_title.get_attribute('content') or '').strip()
                    if '|' in t:
                        t = t.split('|')[0].strip()
                    if t and len(t) < 200 and t not in title_exclude:
                        pin_data['title'] = t
                except Exception:
                    pass
            
            # Описание — сначала из контейнера пина, с прокруткой к блоку описания
            exclude_keywords = [
                'Просмотреть', 'View', 'See more', 'Больше', 'Сохранить', 'Save',
                'Войти', 'Login', 'Регистрация', 'Sign up', 'Поиск', 'Search',
                'Комментарии', 'Comments', 'Ингредиенты', 'Ingredients',
                'Другие интересные пины', 'More ideas', 'Подробнее об этом пине',
                'Вы вышли из системы', "You've been logged out", 'меньше', 'less',
                'Repin', 'Send', 'Share', 'Download', 'Скачать', 'Отправить', 'Поделиться',
                'Follow', 'Подписаться', 'Like', 'Нравится', 'Ideas for you', 'Вам может понравиться'
            ]
            
            def _is_valid_description(text):
                if not text or text == pin_data['title'] or text.startswith('http'):
                    return False
                if len(text) < 15 or len(text) > 5000:
                    return False
                if any(kw in text for kw in exclude_keywords):
                    return False
                return True
            
            try:
                desc_selectors = [
                    '[data-test-id="pin-description"]',
                    '.pinDescription',
                    'div[class*="description"]',
                    'div[class*="Description"]',
                    'p[class*="description"]',
                    'span[class*="description"]',
                    'div[class*="richPin"] p', 'div[class*="RichPin"] p',
                    'div[class*="PinDetail"] p', 'div[class*="pinDetail"] p',
                ]
                for selector in desc_selectors:
                    scope = pin_container if pin_container else self.driver
                    try:
                        elems = scope.find_elements(By.CSS_SELECTOR, selector)
                        for elem in elems:
                            try:
                                if not elem.is_displayed():
                                    continue
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                time.sleep(0.2)
                            except Exception:
                                continue
                            text = elem.text.strip()
                            if _is_valid_description(text):
                                pin_data['description'] = text
                                break
                        if pin_data['description']:
                            break
                    except Exception:
                        continue
                
                # Fallback: og:description из meta
                if not pin_data['description']:
                    try:
                        og_desc = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:description"]')
                        d = (og_desc.get_attribute('content') or '').strip()
                        if _is_valid_description(d):
                            pin_data['description'] = d
                    except Exception:
                        pass
                
                # Fallback: подходящая строка из body (исключаем UI и счётчики типа "1.2K")
                if not pin_data['description']:
                    try:
                        import re
                        main_content = self.driver.find_element(By.TAG_NAME, 'body')
                        all_text = main_content.text
                        lines = all_text.split('\n')
                        description_candidates = []
                        like_count_re = re.compile(r'^\d+\.?\d*[KkMm]?\s*$')
                        for line in lines:
                            line = line.strip()
                            if not line or line == pin_data['title'] or line.startswith('http'):
                                continue
                            if len(line) < 15 or len(line) > 2000:
                                continue
                            if any(kw in line for kw in exclude_keywords):
                                continue
                            if any(line == x or line.lower() == x.lower() for x in title_exclude):
                                continue
                            if like_count_re.match(line):
                                continue
                            description_candidates.append(line)
                        if description_candidates:
                            best_desc = max(description_candidates, key=len)
                            pin_data['description'] = best_desc
                    except Exception:
                        pass
            except Exception as e:
                print(f"Ошибка при поиске описания: {e}")
            
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
            
            # Ждем загрузки и редиректа (таймаут 5 сек — не блокировать надолго при незалогиненном)
            try:
                WebDriverWait(self.driver, 5).until(
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
        
        # Получаем полную информацию о пинах — только из страницы пина, чтобы ссылка и карточка совпадали
        if pins_data:
            print("Получение полной информации о пинах...")
            for i, pin in enumerate(pins_data[:max_pins]):
                if pin.get('pin_link'):
                    detail = self.parse_pin_detail(pin['pin_link'])
                    if detail:
                        pins_data[i]['pin_link'] = detail.get('pin_link') or pins_data[i]['pin_link']
                        pins_data[i]['title'] = detail.get('title', '') or ''
                        pins_data[i]['description'] = detail.get('description', '') or ''
                        pins_data[i]['image_url'] = detail.get('image_url', '') or ''
                        pins_data[i]['media_type'] = detail.get('media_type', 'image') or 'image'
                        if detail.get('author'):
                            pins_data[i]['author'] = detail['author']
                    else:
                        pins_data[i]['title'] = ''
                        pins_data[i]['description'] = ''
                        pins_data[i]['image_url'] = ''
                    
                    # Скачиваем изображение если нужно; без картинки пин не включаем
                    if self.download_images and pins_data[i].get('image_url'):
                        pin_id = pin['pin_link'].split('/pin/')[-1].rstrip('/')
                        local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                        if local_path:
                            pins_data[i]['image_url'] = local_path
                        else:
                            pins_data[i]['image_url'] = ''
                    
                    time.sleep(1)
        
        pins_data = [p for p in pins_data if (p.get('image_url') or p.get('image_path') or '').strip()]
        print(f"Найдено пинов: {len(pins_data)} (только с изображением)")
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
        
        # Получаем полную информацию о пинах — только из страницы пина, чтобы ссылка и карточка совпадали
        if pins_data:
            print("Получение полной информации о пинах...")
            for i, pin in enumerate(pins_data[:max_pins]):
                if pin.get('pin_link'):
                    detail = self.parse_pin_detail(pin['pin_link'])
                    if detail:
                        pins_data[i]['pin_link'] = detail.get('pin_link') or pins_data[i]['pin_link']
                        pins_data[i]['title'] = detail.get('title', '') or ''
                        pins_data[i]['description'] = detail.get('description', '') or ''
                        pins_data[i]['image_url'] = detail.get('image_url', '') or ''
                        pins_data[i]['media_type'] = detail.get('media_type', 'image') or 'image'
                        if detail.get('author'):
                            pins_data[i]['author'] = detail['author']
                    else:
                        pins_data[i]['title'] = ''
                        pins_data[i]['description'] = ''
                        pins_data[i]['image_url'] = ''
                    
                    # Скачиваем изображение если нужно; без картинки пин не включаем
                    if self.download_images and pins_data[i].get('image_url'):
                        pin_id = pin['pin_link'].split('/pin/')[-1].rstrip('/')
                        local_path = self._download_image(pins_data[i]['image_url'], pin_id)
                        if local_path:
                            pins_data[i]['image_url'] = local_path
                        else:
                            pins_data[i]['image_url'] = ''
                    
                    time.sleep(1)
        
        pins_data = [p for p in pins_data if (p.get('image_url') or p.get('image_path') or '').strip()]
        print(f"Найдено пинов в доске: {len(pins_data)} (только с изображением)")
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
            import csv
            filename = f"pinterest_pins_{query.replace(' ', '_').replace('/', '_')[:50]}.csv"
            if pins:
                fieldnames = ['title', 'description', 'pin_link', 'image_url', 'author', 'board_name', 'board_url',
                    'repin_count', 'comments_disabled', 'saves', 'done', 'comment_count', 'likes', 'created_at', 'share_count']
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(pins)
            print(f"\n✓ Данные сохранены в файл: {filename}")
        else:
            print("\n⚠ Пины не найдены. Попробуйте:")
            print("  - Включить авторизацию в config.json (enable_login: true)")
            print("  - Добавить cookies для авторизации")
            print("  - Изменить поисковый запрос")
            print("  - Проверить интернет-соединение")
    finally:
        parser.close()
