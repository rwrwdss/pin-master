"""
Скрипт для анализа страницы логина Pinterest.
Помогает понять структуру формы логина и процесс авторизации.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

def analyze_login_page():
    """Анализирует страницу логина Pinterest"""
    
    # Настройка браузера
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        print("=" * 80)
        print("АНАЛИЗ СТРАНИЦЫ ЛОГИНА PINTEREST")
        print("=" * 80)
        print()
        
        # Переходим на страницу логина
        login_url = "https://ru.pinterest.com/login/"
        print(f"Загрузка страницы: {login_url}")
        driver.get(login_url)
        time.sleep(5)
        
        print(f"Текущий URL: {driver.current_url}")
        print()
        
        # Ищем поля формы
        print("1. ПОЛЯ ФОРМЫ ЛОГИНА:")
        print("-" * 80)
        
        # Email поле
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id*="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="почт" i]',
        ]
        
        for selector in email_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    elem = elements[0]
                    print(f"\n✓ Найдено поле Email:")
                    print(f"  Селектор: {selector}")
                    print(f"  Type: {elem.get_attribute('type')}")
                    print(f"  Name: {elem.get_attribute('name')}")
                    print(f"  ID: {elem.get_attribute('id')}")
                    print(f"  Placeholder: {elem.get_attribute('placeholder')}")
                    print(f"  Class: {elem.get_attribute('class')}")
                    break
            except:
                continue
        
        # Password поле
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="password"]',
        ]
        
        for selector in password_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    elem = elements[0]
                    print(f"\n✓ Найдено поле Password:")
                    print(f"  Селектор: {selector}")
                    print(f"  Type: {elem.get_attribute('type')}")
                    print(f"  Name: {elem.get_attribute('name')}")
                    print(f"  ID: {elem.get_attribute('id')}")
                    print(f"  Class: {elem.get_attribute('class')}")
                    break
            except:
                continue
        
        # Кнопка входа
        print("\n\n2. КНОПКИ ВХОДА:")
        print("-" * 80)
        
        button_selectors = [
            'button[type="submit"]',
            'button[class*="login"]',
            'button[class*="submit"]',
            'button:contains("Войти")',
            'button:contains("Log in")',
        ]
        
        for selector in button_selectors:
            try:
                if ':contains' in selector:
                    buttons = driver.find_elements(By.XPATH, 
                        "//button[contains(text(), 'Войти') or contains(text(), 'Log in')]")
                else:
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                
                if buttons:
                    for i, button in enumerate(buttons[:3], 1):
                        print(f"\n✓ Кнопка {i}:")
                        print(f"  Селектор: {selector}")
                        print(f"  Text: {button.text}")
                        print(f"  Type: {button.get_attribute('type')}")
                        print(f"  Class: {button.get_attribute('class')}")
                        print(f"  ID: {button.get_attribute('id')}")
            except:
                continue
        
        # Анализ cookies до логина
        print("\n\n3. COOKIES ДО ЛОГИНА:")
        print("-" * 80)
        cookies_before = driver.get_cookies()
        print(f"Найдено cookies: {len(cookies_before)}")
        for cookie in cookies_before[:5]:
            print(f"  {cookie['name']}: {cookie['value'][:50]}...")
        
        # Анализ JavaScript переменных
        print("\n\n4. JAVASCRIPT ПЕРЕМЕННЫЕ:")
        print("-" * 80)
        try:
            js_vars = driver.execute_script("""
                return {
                    'window.location': window.location.href,
                    'document.title': document.title,
                    'hasPWS': typeof window.__PWS_INITIAL_STATE__ !== 'undefined',
                    'hasCSRF': document.querySelector('meta[name="csrf-token"]')?.content || 'нет'
                };
            """)
            print(json.dumps(js_vars, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Ошибка: {e}")
        
        # Сохраняем HTML для анализа
        html_filename = "pinterest_login_page.html"
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"\n\n✓ HTML страницы сохранен в {html_filename}")
        
        print("\n" + "=" * 80)
        print("АНАЛИЗ ЗАВЕРШЕН")
        print("=" * 80)
        print("\nДля тестирования авторизации запустите:")
        print("  python pinterest_auth.py")
        
        # Ждем для ручного просмотра
        print("\nБраузер останется открытым 10 секунд для просмотра...")
        time.sleep(10)
        
    finally:
        driver.quit()


if __name__ == "__main__":
    analyze_login_page()
