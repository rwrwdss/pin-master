"""
Вспомогательный скрипт для анализа страницы Pinterest и поиска селекторов.
Помогает определить правильные селекторы для парсинга.
"""

import os
import sys
import argparse
import requests
from bs4 import BeautifulSoup
from pinterest_selectors import PinterestConfig
from cookies_manager import load_cookies_from_file, CookiesManager


def analyze_pinterest_page(url: str, cookies_file: str = None):
    """
    Анализирует HTML страницу Pinterest и выводит потенциальные селекторы.
    
    Args:
        url: URL страницы Pinterest для анализа
        cookies_file: Путь к файлу с cookies для авторизации
    """
    session = requests.Session()
    headers = {
        'User-Agent': PinterestConfig.USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.pinterest.com/',
    }
    session.headers.update(headers)
    
    # Загружаем cookies если указан файл или существует файл по умолчанию
    if cookies_file:
        cookies = load_cookies_from_file(cookies_file)
        if cookies:
            for name, value in cookies.items():
                session.cookies.set(name, value, domain='.pinterest.com')
            print(f"✓ Cookies загружены из {cookies_file}")
    elif os.path.exists("pinterest_cookies.json"):
        cookies = load_cookies_from_file("pinterest_cookies.json")
        if cookies:
            for name, value in cookies.items():
                session.cookies.set(name, value, domain='.pinterest.com')
            print("✓ Cookies загружены из pinterest_cookies.json")
    
    # Проверяем авторизацию
    if session.cookies:
        is_authorized = CookiesManager.check_authorization(session)
        if is_authorized:
            print("✓ Авторизация подтверждена\n")
        else:
            print("⚠ Авторизация не подтверждена, но cookies установлены\n")
    
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print("=" * 80)
        print("АНАЛИЗ СТРАНИЦЫ PINTEREST")
        print("=" * 80)
        print(f"\nURL: {url}\n")
        
        # Поиск потенциальных контейнеров пинов
        print("\n1. ПОТЕНЦИАЛЬНЫЕ КОНТЕЙНЕРЫ ПИНОВ:")
        print("-" * 80)
        
        # Ищем элементы с классами, содержащими 'pin', 'card', 'item'
        potential_containers = soup.find_all(attrs={'class': lambda x: x and any(
            keyword in str(x).lower() for keyword in ['pin', 'card', 'item', 'tile']
        )})
        
        for i, container in enumerate(potential_containers[:5], 1):
            classes = container.get('class', [])
            print(f"\nКонтейнер {i}:")
            print(f"  Тег: {container.name}")
            print(f"  Классы: {classes}")
            print(f"  ID: {container.get('id', 'нет')}")
            print(f"  Содержимое (первые 100 символов): {container.get_text()[:100]}")
        
        # Поиск ссылок на пины
        print("\n\n2. ССЫЛКИ НА ПИНЫ:")
        print("-" * 80)
        pin_links = soup.find_all('a', href=lambda x: x and '/pin/' in str(x))
        for i, link in enumerate(pin_links[:5], 1):
            print(f"\nСсылка {i}:")
            print(f"  URL: {link.get('href', 'нет')}")
            print(f"  Текст: {link.get_text()[:50]}")
            print(f"  Классы: {link.get('class', [])}")
        
        # Поиск изображений
        print("\n\n3. ИЗОБРАЖЕНИЯ:")
        print("-" * 80)
        images = soup.find_all('img', src=lambda x: x and x)
        pinimg_images = [img for img in images if 'pinimg.com' in str(img.get('src', ''))]
        
        for i, img in enumerate(pinimg_images[:5], 1):
            print(f"\nИзображение {i}:")
            print(f"  src: {img.get('src', 'нет')}")
            print(f"  data-src: {img.get('data-src', 'нет')}")
            print(f"  data-lazy-src: {img.get('data-lazy-src', 'нет')}")
            print(f"  alt: {img.get('alt', 'нет')}")
            print(f"  Классы: {img.get('class', [])}")
        
        # Поиск текстовых элементов (названия, описания)
        print("\n\n4. ТЕКСТОВЫЕ ЭЛЕМЕНТЫ (потенциальные названия/описания):")
        print("-" * 80)
        
        # Ищем элементы с классами, содержащими 'title', 'description', 'text'
        text_elements = soup.find_all(attrs={'class': lambda x: x and any(
            keyword in str(x).lower() for keyword in ['title', 'description', 'text', 'name']
        )})
        
        for i, elem in enumerate(text_elements[:10], 1):
            text = elem.get_text().strip()
            if text and len(text) > 10:  # Пропускаем очень короткие тексты
                print(f"\nЭлемент {i}:")
                print(f"  Тег: {elem.name}")
                print(f"  Классы: {elem.get('class', [])}")
                print(f"  Текст: {text[:100]}")
        
        # Поиск информации об авторе
        print("\n\n5. ИНФОРМАЦИЯ ОБ АВТОРЕ:")
        print("-" * 80)
        author_links = soup.find_all('a', href=lambda x: x and '/pin/' not in str(x) and x.startswith('/'))
        for i, link in enumerate(author_links[:5], 1):
            text = link.get_text().strip()
            if text:
                print(f"\nАвтор {i}:")
                print(f"  URL: {link.get('href', 'нет')}")
                print(f"  Текст: {text}")
                print(f"  Классы: {link.get('class', [])}")
        
        # Сохранение HTML для ручного анализа
        html_filename = "pinterest_page_source.html"
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        print(f"\n\nПолный HTML сохранен в {html_filename} для ручного анализа")
        
        print("\n" + "=" * 80)
        print("АНАЛИЗ ЗАВЕРШЕН")
        print("=" * 80)
        
    except requests.RequestException as e:
        print(f"Ошибка при запросе: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Анализатор селекторов Pinterest',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python selector_helper.py --url "https://www.pinterest.com/search/pins/?q=python"
  python selector_helper.py --url "https://www.pinterest.com/pin/123456789/" --cookies my_cookies.json
  python selector_helper.py  # Интерактивный режим
        """
    )
    
    parser.add_argument(
        '--url',
        type=str,
        help='URL страницы Pinterest для анализа'
    )
    parser.add_argument(
        '--cookies',
        type=str,
        help='Путь к файлу с cookies (по умолчанию: pinterest_cookies.json)'
    )
    parser.add_argument(
        '--no-cookies',
        action='store_true',
        help='Не использовать cookies даже если файл существует'
    )
    
    args = parser.parse_args()
    
    # Если URL не указан как аргумент, используем интерактивный режим
    if args.url:
        url = args.url
        cookies_file = args.cookies if args.cookies else None
        
        if not args.no_cookies and not cookies_file and os.path.exists("pinterest_cookies.json"):
            cookies_file = "pinterest_cookies.json"
        
        analyze_pinterest_page(url, cookies_file)
    else:
        # Интерактивный режим
        print("=" * 80)
        print("АНАЛИЗАТОР СЕЛЕКТОРОВ PINTEREST")
        print("=" * 80)
        print("\nВведите URL страницы Pinterest для анализа")
        print("Примеры:")
        print("  - Поиск: https://www.pinterest.com/search/pins/?q=python")
        print("  - Пин: https://www.pinterest.com/pin/123456789/")
        print("  - Профиль: https://www.pinterest.com/username/")
        print()
        
        try:
            url = input("URL: ").strip()
            if not url:
                url = "https://www.pinterest.com/search/pins/?q=python"
            
            # Проверяем наличие файла cookies
            cookies_file = None
            if os.path.exists("pinterest_cookies.json") and not args.no_cookies:
                use_cookies = input("\nИспользовать cookies из pinterest_cookies.json? (y/n, по умолчанию y): ").strip().lower()
                if use_cookies != 'n':
                    cookies_file = "pinterest_cookies.json"
            elif not args.no_cookies:
                use_cookies = input("\nУказать файл с cookies? (y/n, по умолчанию n): ").strip().lower()
                if use_cookies == 'y':
                    cookies_file = input("Путь к файлу с cookies: ").strip()
            
            print()
            analyze_pinterest_page(url, cookies_file)
        except (EOFError, KeyboardInterrupt):
            print("\n\nПрервано пользователем")
            sys.exit(0)
