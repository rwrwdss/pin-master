"""
Модуль авторизации в Pinterest через браузер.
Автоматически логинится и сохраняет cookies сессии.
"""

import time
import json
import os
from typing import Optional, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from pinterest_selectors import PinterestConfig
from cookies_manager import CookiesManager


class PinterestAuth:
    """Класс для авторизации в Pinterest"""
    
    def __init__(self, headless: bool = False, config_file: str = "config.json"):
        """
        Инициализирует авторизацию.
        
        Args:
            headless: Запускать браузер в фоновом режиме
            config_file: Путь к файлу конфигурации
        """
        self.headless = headless
        self.config = self._load_config(config_file)
        self.driver = None
        self._setup_driver()
    
    def _load_config(self, config_file: str) -> Dict:
        """Загружает конфигурацию из файла"""
        default_config = {
            "enable_login": False,
            "login_url": "https://ru.pinterest.com/login/",
            "cookies_file": "pinterest_cookies.json",
            "headless": True,
            "download_images": True,
            "wait_for_manual_login": True,
            "login_timeout": 300
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                print(f"⚠ Ошибка при загрузке конфига: {e}. Используются настройки по умолчанию.")
        else:
            # Создаем файл конфига с настройками по умолчанию
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"✓ Создан файл конфигурации: {config_file}")
        
        return default_config
    
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
            print("✓ Chrome драйвер запущен для авторизации")
        except Exception as e:
            print(f"Ошибка при запуске Chrome драйвера: {e}")
            raise
    
    def check_existing_session(self) -> bool:
        """
        Проверяет, есть ли уже сохраненная сессия.
        
        Returns:
            True если сессия валидна, False иначе
        """
        cookies_file = self.config.get("cookies_file", "pinterest_cookies.json")
        if not os.path.exists(cookies_file):
            return False
        
        cookies = CookiesManager.load_from_json_file(cookies_file)
        if not cookies:
            return False
        
        # Проверяем наличие важных cookies
        important_cookies = ['_auth', '_pinterest_sess', 'csrftoken']
        has_important = any(key in cookies for key in important_cookies)
        
        if has_important:
            # Проверяем валидность сессии
            try:
                self.driver.get("https://www.pinterest.com")
                time.sleep(2)
                
                # Загружаем cookies
                for name, value in cookies.items():
                    try:
                        self.driver.add_cookie({
                            'name': name,
                            'value': value,
                            'domain': '.pinterest.com',
                            'path': '/'
                        })
                    except:
                        pass
                
                # Проверяем авторизацию
                self.driver.get("https://www.pinterest.com")
                time.sleep(2)
                
                # Ищем признаки авторизованного пользователя
                page_source = self.driver.page_source.lower()
                if 'create' in page_source or 'saved' in page_source or 'profile' in page_source:
                    print("✓ Найдена валидная сессия")
                    return True
            except Exception as e:
                print(f"⚠ Ошибка при проверке сессии: {e}")
        
        return False
    
    def login_manual(self) -> bool:
        """
        Открывает страницу логина и ждет ручного входа пользователя.
        
        Returns:
            True если авторизация успешна, False иначе
        """
        login_url = self.config.get("login_url", "https://ru.pinterest.com/login/")
        timeout = self.config.get("login_timeout", 300)
        
        print(f"Открываю страницу логина: {login_url}")
        self.driver.get(login_url)
        time.sleep(3)
        
        print("\n" + "=" * 80)
        print("ОЖИДАНИЕ РУЧНОГО ЛОГИНА")
        print("=" * 80)
        print("Пожалуйста, войдите в свой аккаунт Pinterest в открывшемся браузере.")
        print("После успешного входа сессия будет автоматически сохранена.")
        print(f"Ожидание: {timeout} секунд")
        print("=" * 80 + "\n")
        
        # Ждем пока пользователь залогинится
        start_time = time.time()
        check_interval = 5  # Проверяем каждые 5 секунд
        
        while time.time() - start_time < timeout:
            try:
                current_url = self.driver.current_url
                
                # Если мы не на странице логина, возможно пользователь залогинился
                if '/login' not in current_url.lower():
                    # Проверяем признаки авторизации
                    page_source = self.driver.page_source.lower()
                    if 'create' in page_source or 'saved' in page_source or 'profile' in page_source:
                        print("\n✓ Обнаружен успешный вход!")
                        time.sleep(2)  # Даем время для полной загрузки
                        return True
                
                # Показываем прогресс
                elapsed = int(time.time() - start_time)
                if elapsed % 30 == 0:  # Каждые 30 секунд
                    remaining = timeout - elapsed
                    print(f"⏳ Ожидание... Осталось ~{remaining} секунд")
                
                time.sleep(check_interval)
                
            except Exception as e:
                print(f"⚠ Ошибка при проверке статуса: {e}")
                time.sleep(check_interval)
        
        print("\n⚠ Время ожидания истекло")
        return False
    
    def login_automated(self, email: str, password: str) -> bool:
        """
        Автоматический логин (экспериментальная функция).
        Pinterest может блокировать автоматический вход.
        
        Args:
            email: Email для входа
            password: Пароль
            
        Returns:
            True если авторизация успешна, False иначе
        """
        login_url = self.config.get("login_url", "https://ru.pinterest.com/login/")
        
        print(f"Попытка автоматического входа: {login_url}")
        self.driver.get(login_url)
        time.sleep(3)
        
        try:
            # Ищем поле email
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[id*="email"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="почт" i]',
            ]
            
            email_field = None
            for selector in email_selectors:
                try:
                    email_field = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if email_field:
                        break
                except:
                    continue
            
            if not email_field:
                print("⚠ Не найдено поле email")
                return False
            
            # Вводим email
            email_field.clear()
            email_field.send_keys(email)
            time.sleep(1)
            
            # Ищем поле пароля
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[id*="password"]',
            ]
            
            password_field = None
            for selector in password_selectors:
                try:
                    password_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if password_field:
                        break
                except:
                    continue
            
            if not password_field:
                print("⚠ Не найдено поле пароля")
                return False
            
            # Вводим пароль
            password_field.clear()
            password_field.send_keys(password)
            time.sleep(1)
            
            # Ищем кнопку входа
            login_button_selectors = [
                'button[type="submit"]',
                'button[class*="login"]',
                'button[class*="submit"]',
                'button:contains("Войти")',
                'button:contains("Log in")',
            ]
            
            login_button = None
            for selector in login_button_selectors:
                try:
                    if ':contains' in selector:
                        # XPath для текста
                        login_button = self.driver.find_element(By.XPATH, 
                            "//button[contains(text(), 'Войти') or contains(text(), 'Log in')]")
                    else:
                        login_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if login_button and login_button.is_displayed():
                        break
                except:
                    continue
            
            if not login_button:
                print("⚠ Не найдена кнопка входа")
                return False
            
            # Нажимаем кнопку входа
            login_button.click()
            time.sleep(5)
            
            # Проверяем успешность входа
            current_url = self.driver.current_url
            if '/login' not in current_url.lower():
                page_source = self.driver.page_source.lower()
                if 'create' in page_source or 'saved' in page_source:
                    print("✓ Автоматический вход успешен!")
                    return True
            
            print("⚠ Автоматический вход не удался")
            return False
            
        except Exception as e:
            print(f"⚠ Ошибка при автоматическом входе: {e}")
            return False
    
    def save_session(self) -> bool:
        """
        Сохраняет cookies текущей сессии в файл.
        
        Returns:
            True если сохранение успешно, False иначе
        """
        try:
            cookies = self.driver.get_cookies()
            cookies_dict = {}
            
            for cookie in cookies:
                if 'pinterest.com' in cookie.get('domain', ''):
                    cookies_dict[cookie['name']] = cookie['value']
            
            if not cookies_dict:
                print("⚠ Cookies не найдены")
                return False
            
            cookies_file = self.config.get("cookies_file", "pinterest_cookies.json")
            CookiesManager.save_to_json(cookies_dict, cookies_file)
            
            print(f"✓ Сессия сохранена: {len(cookies_dict)} cookies в {cookies_file}")
            return True
            
        except Exception as e:
            print(f"⚠ Ошибка при сохранении сессии: {e}")
            return False
    
    def authenticate(self, email: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Выполняет авторизацию в Pinterest.
        
        Args:
            email: Email для автоматического входа (опционально)
            password: Пароль для автоматического входа (опционально)
            
        Returns:
            True если авторизация успешна, False иначе
        """
        # Проверяем существующую сессию
        if self.check_existing_session():
            return True
        
        # Если включен автоматический логин и есть credentials
        if email and password:
            if self.login_automated(email, password):
                return self.save_session()
        
        # Ручной логин
        if self.login_manual():
            return self.save_session()
        
        return False
    
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
    # Пример использования
    import sys
    
    auth = PinterestAuth(headless=False)
    
    try:
        # Проверяем конфиг
        if auth.config.get("enable_login", False):
            print("Авторизация включена в конфиге")
            
            # Пробуем авторизоваться
            if auth.authenticate():
                print("\n✓ Авторизация успешна!")
            else:
                print("\n⚠ Авторизация не удалась")
        else:
            print("Авторизация отключена в конфиге (enable_login: false)")
            print("Измените config.json чтобы включить авторизацию")
    finally:
        auth.close()
