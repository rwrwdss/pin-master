"""
Модуль для публикации пинов на Pinterest.
Тестовый консольный модуль для проверки функционала публикации.
"""

import time
import os
from typing import Optional, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

from pinterest_selectors import PinterestConfig
from cookies_manager import load_cookies_from_file
from pinterest_selenium_parser import PinterestSeleniumParser


class PinterestPublisher:
    """Класс для публикации пинов на Pinterest"""
    
    PIN_CREATION_URL = "https://ru.pinterest.com/pin-creation-tool/"
    
    def __init__(self, parser: Optional[PinterestSeleniumParser] = None):
        """
        Инициализирует публикатор.
        
        Args:
            parser: Существующий парсер с инициализированным браузером (опционально)
        """
        if parser and parser.driver:
            self.driver = parser.driver
            self.own_driver = False
        else:
            self.own_driver = True
            self._setup_driver()
    
    def _setup_driver(self):
        """Настраивает Chrome драйвер"""
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(f'user-agent={PinterestConfig.USER_AGENT}')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✓ Chrome драйвер запущен для публикации")
            
            # Загружаем cookies если есть
            cookies = load_cookies_from_file("pinterest_cookies.json")
            if cookies:
                self.driver.get("https://www.pinterest.com")
                time.sleep(2)
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
                self.driver.refresh()
                time.sleep(2)
        except Exception as e:
            print(f"Ошибка при запуске Chrome драйвера: {e}")
            raise
    
    def get_user_boards(self) -> List[Dict[str, str]]:
        """
        Получает список досок пользователя.
        
        Returns:
            Список словарей с информацией о досках
        """
        try:
            # Используем парсер для получения досок
            if hasattr(self, 'parser') and self.parser:
                account_info = self.parser.get_account_info()
                if account_info:
                    username = account_info.get('username')
                    if username:
                        boards = self.parser.parse_user_boards(username=username)
                        return boards
            
            # Если парсера нет, получаем доски напрямую
            # Переходим на страницу досок
            self.driver.get("https://ru.pinterest.com/me")
            time.sleep(3)
            
            # Извлекаем username из URL
            current_url = self.driver.current_url
            if '/me' not in current_url:
                parts = current_url.replace('https://ru.pinterest.com/', '').split('/')
                if parts and parts[0]:
                    username = parts[0]
                    boards_url = f"https://ru.pinterest.com/{username}/_boards/"
                    self.driver.get(boards_url)
                    time.sleep(3)
                    
                    # Парсим доски
                    boards = []
                    board_links = self.driver.find_elements(By.CSS_SELECTOR, f'a[href*="/{username}/"]')
                    seen_boards = set()
                    
                    for link in board_links:
                        try:
                            href = link.get_attribute('href')
                            if not href or href in seen_boards:
                                continue
                            
                            excluded_paths = ['/_pins/', '/_boards/', '/_created/', '/_saved/', '/pin/', '/settings/', '/account/']
                            is_excluded = any(excluded in href for excluded in excluded_paths)
                            is_profile = href.rstrip('/').endswith(f'/{username}')
                            
                            if (f'/{username}/' in href and 
                                not is_excluded and
                                not is_profile and
                                '/pin/' not in href and
                                href.count('/') >= 3):
                                
                                seen_boards.add(href)
                                board_name = href.rstrip('/').split('/')[-1]
                                boards.append({
                                    'board_name': board_name,
                                    'board_url': href
                                })
                        except:
                            continue
                    
                    return boards
            
            return []
        except Exception as e:
            print(f"Ошибка при получении досок: {e}")
            return []
    
    def create_pin(self, image_path: str, title: str, description: str, 
                   link: str, board_name: str) -> bool:
        """
        Создает и публикует пин на Pinterest.
        
        Args:
            image_path: Путь к изображению для загрузки
            title: Название пина
            description: Описание пина
            link: Ссылка для пина
            board_name: Название доски для публикации
            
        Returns:
            True если публикация успешна, False иначе
        """
        try:
            print("\n" + "=" * 80)
            print("ПУБЛИКАЦИЯ ПИНА")
            print("=" * 80)
            
            # Проверяем существование файла
            if not os.path.exists(image_path):
                print(f"⚠ Файл не найден: {image_path}")
                return False
            
            print(f"Изображение: {image_path}")
            print(f"Название: {title}")
            print(f"Описание: {description}")
            print(f"Ссылка: {link}")
            print(f"Доска: {board_name}")
            
            # Переходим на страницу создания пина
            print(f"\nПереход на страницу создания пина: {self.PIN_CREATION_URL}")
            self.driver.get(self.PIN_CREATION_URL)
            time.sleep(3)
            
            # Ждем загрузки страницы
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                )
            except:
                time.sleep(2)
            
            # Шаг 1: Загружаем изображение
            print("\n1. Загрузка изображения...")
            try:
                # Получаем абсолютный путь к файлу
                abs_image_path = os.path.abspath(image_path)
                print(f"Путь к файлу: {abs_image_path}")
                
                # Ищем поле загрузки по ID (из анализа страницы)
                file_input = None
                
                # Способ 1: Поиск по ID (самый надежный)
                try:
                    file_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.ID, 'storyboard-upload-input'))
                    )
                    print("✓ Найдено поле загрузки по ID")
                except:
                    pass
                
                # Способ 2: Прямой поиск input[type="file"]
                if not file_input:
                    try:
                        file_input = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
                        )
                        print("✓ Найдено поле загрузки (способ 2)")
                    except:
                        pass
                
                if file_input:
                    # Загружаем файл
                    file_input.send_keys(abs_image_path)
                    print(f"✓ Файл выбран: {abs_image_path}")
                    
                    # Ждем загрузки изображения (страница изменится)
                    print("Ожидание загрузки изображения...")
                    time.sleep(5)
                    
                    # Проверяем, что изображение загрузилось и форма появилась
                    try:
                        WebDriverWait(self.driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, 
                                'input[placeholder*="название" i], input[placeholder*="title" i], textarea[placeholder*="описание" i]'))
                        )
                        print("✓ Изображение загружено, форма готова")
                        time.sleep(2)  # Дополнительная задержка для полной загрузки
                    except:
                        print("⚠ Таймаут ожидания загрузки формы, продолжаем...")
                        time.sleep(5)
                else:
                    print("⚠ Поле загрузки файла не найдено")
                    print("Попробуйте загрузить файл вручную в открывшемся браузере")
                    input("Нажмите Enter после ручной загрузки изображения...")
                    time.sleep(2)
            except Exception as e:
                print(f"⚠ Ошибка при загрузке изображения: {e}")
                import traceback
                traceback.print_exc()
                print("\nПопробуйте загрузить файл вручную в открывшемся браузере")
                input("Нажмите Enter после ручной загрузки изображения...")
                time.sleep(2)
            
            # Шаг 2: Сначала выбираем доску
            # ВАЖНО: После выбора доски заполняем все поля заново, так как они могут сброситься
            print(f"\n2. Выбор доски: {board_name}...")
            board_selected = False
            try:
                # Ищем поле выбора доски
                print("  Поиск поля выбора доски...")
                all_board_elements = self.driver.find_elements(By.XPATH,
                    "//*[contains(text(), 'Доска') or contains(text(), 'Board') or contains(@placeholder, 'доск') or contains(@placeholder, 'board')]")
                
                board_field = None
                # Ищем поле через альтернативные методы
                try:
                    all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                    all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                    all_divs = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                    
                    for elem in all_inputs + all_buttons + all_divs:
                        try:
                            if not elem.is_displayed():
                                continue
                            placeholder = elem.get_attribute('placeholder') or ''
                            aria_label = elem.get_attribute('aria-label') or ''
                            text = elem.text.strip() or ''
                            
                            if ('доск' in placeholder.lower() or 'board' in placeholder.lower() or
                                'доск' in aria_label.lower() or 'board' in aria_label.lower() or
                                'доск' in text.lower() or 'board' in text.lower()):
                                is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                                if not is_in_header:
                                    board_field = elem
                                    print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}")
                                    break
                        except:
                            continue
                except:
                    pass
                
                if board_field:
                    # Кликаем на поле выбора доски
                    print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                    time.sleep(1)
                    
                    clicked = False
                    try:
                        board_field.click()
                        clicked = True
                    except:
                        try:
                            self.driver.execute_script("arguments[0].click();", board_field)
                            clicked = True
                        except:
                            pass
                    
                    if clicked:
                        print("✓ Поле выбора доски открыто")
                        # Ждем открытия модального окна
                        print("  Ожидание открытия модального окна...")
                        time.sleep(2)
                        
                        # Ищем модальное окно
                        modal_visible = False
                        for attempt in range(5):
                            try:
                                modals = self.driver.find_elements(By.CSS_SELECTOR,
                                    'div[role="dialog"], div[class*="modal"], div[class*="overlay"]')
                                search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                    'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                                if modals or search_inputs:
                                    visible_modals = [m for m in modals if m.is_displayed()]
                                    visible_search = [s for s in search_inputs if s.is_displayed()]
                                    if visible_modals or visible_search:
                                        modal_visible = True
                                        print(f"  ✓ Модальное окно открыто")
                                        break
                            except:
                                pass
                            if attempt < 4:
                                time.sleep(0.5)
                        
                        if modal_visible:
                            # Ищем доску в модальном окне
                            print("  Поиск доски в модальном окне...")
                            board_options = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[contains(text(), '{board_name}') and not(self::input) and not(self::textarea)]")
                            board_options = [opt for opt in board_options 
                                           if opt.is_displayed() and len(opt.text.strip()) < 100]
                            
                            if not board_options:
                                # Ищем все доски и выбираем первую доступную
                                all_boards = self.driver.find_elements(By.XPATH,
                                    "//div[@role='dialog']//*[text() and not(self::input) and not(self::textarea)]")
                                for elem in all_boards:
                                    try:
                                        text = elem.text.strip()
                                        if text and len(text) < 50 and len(text) > 0:
                                            text_lower = text.lower()
                                            if ('поиск' not in text_lower and 'search' not in text_lower and 
                                                'создать' not in text_lower and 'create' not in text_lower and
                                                'все доски' not in text_lower and 'all boards' not in text_lower and
                                                'найдена доска' not in text_lower):
                                                try:
                                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                                    time.sleep(0.5)
                                                    self.driver.execute_script("arguments[0].click();", elem)
                                                    board_selected = True
                                                    print(f"✓ Доска выбрана: '{text}'")
                                                    time.sleep(2)
                                                    break
                                                except:
                                                    continue
                                    except:
                                        continue
                            else:
                                # Выбираем найденную доску
                                for option in board_options:
                                    try:
                                        if board_name.lower() in option.text.strip().lower():
                                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                            time.sleep(0.5)
                                            self.driver.execute_script("arguments[0].click();", option)
                                            board_selected = True
                                            print(f"✓ Доска выбрана: {board_name}")
                                            time.sleep(2)
                                            break
                                    except:
                                        continue
            except Exception as e:
                print(f"⚠ Ошибка при выборе доски: {e}")
            
            if not board_selected:
                print("⚠ ВНИМАНИЕ: Доска не выбрана! Публикация может не пройти.")
            
            # Шаг 3: Заполняем название
            print("\n3. Заполнение названия...")
            try:
                title_field = None
                
                # Способ 1: Поиск по ID (из анализа страницы)
                try:
                    title_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, 'storyboard-selector-title'))
                    )
                    print("  ✓ Поле названия найдено по ID")
                except:
                    pass
                
                # Способ 2: Поиск по placeholder
                if not title_field:
                    title_selectors = [
                        'input[placeholder*="название" i]',
                        'input[placeholder*="title" i]',
                        'input[placeholder*="Добавить название" i]'
                    ]
                    
                    for selector in title_selectors:
                        try:
                            title_field = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            if title_field:
                                break
                        except:
                            continue
                
                if title_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_field)
                    time.sleep(1)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                    try:
                        title_field.click()
                        time.sleep(0.3)
                        # Очищаем через выделение и удаление
                        from selenium.webdriver.common.keys import Keys
                        title_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                        time.sleep(0.2)
                        title_field.send_keys(Keys.DELETE)  # Удаляем
                        time.sleep(0.3)
                        # Заполняем через send_keys
                        title_field.send_keys(title)
                        time.sleep(1)  # Даем время на обработку
                        # Снимаем фокус для сохранения
                        self.driver.execute_script("arguments[0].blur();", title_field)
                        time.sleep(0.5)
                        # Кликаем вне поля для триггера сохранения
                        self.driver.execute_script("document.body.click();")
                        time.sleep(0.5)
                        print(f"✓ Название заполнено: {title}")
                    except Exception as e:
                        print(f"⚠ Ошибка заполнения названия: {e}")
                else:
                    print("⚠ Поле названия не найдено")
            except Exception as e:
                print(f"⚠ Ошибка при заполнении названия: {e}")
            
            # Шаг 4: Заполняем описание (может загружаться с задержкой)
            print("\n4. Заполнение описания...")
            try:
                # Ждем загрузки поля описания - оно может появиться не сразу
                print("  Ожидание загрузки поля описания...")
                
                # Сначала ждем немного после загрузки изображения
                time.sleep(3)
                
                desc_selectors = [
                    'div[contenteditable="true"]',  # Pinterest использует contenteditable для описания
                    'textarea[placeholder*="описание" i]',
                    'textarea[placeholder*="description" i]',
                    'textarea[placeholder*="подробное" i]',
                    'textarea[placeholder*="Добавьте подробное описание" i]',
                    'textarea[placeholder*="Добавьт" i]',  # Частичный placeholder из скриншота
                    'textarea[name*="description" i]',
                    'textarea[data-test-id*="description" i]',
                    'textarea[aria-label*="описание" i]',
                    'textarea[aria-label*="description" i]',
                    'div[contenteditable="true"][placeholder*="описание" i]',
                    'div[contenteditable="true"][placeholder*="description" i]',
                    'textarea'
                ]
                
                desc_field = None
                max_wait = 15  # Максимальное время ожидания
                wait_interval = 0.5
                waited = 0
                
                while not desc_field and waited < max_wait:
                    for selector in desc_selectors:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            
                            for elem in elements:
                                # Для contenteditable div - проверяем, что это поле описания
                                if elem.tag_name == 'div' and elem.get_attribute('contenteditable') == 'true':
                                    # Проверяем, что это не другое поле (например, заголовок)
                                    parent_text = elem.find_element(By.XPATH, './..').text.lower() if elem.find_elements(By.XPATH, './..') else ''
                                    elem_text = elem.text.lower()
                                    placeholder = elem.get_attribute('placeholder') or ''
                                    
                                    # Если есть placeholder с "описание" или это второй contenteditable
                                    if 'описание' in placeholder.lower() or 'description' in placeholder.lower() or 'подробное' in placeholder.lower():
                                        desc_field = elem
                                        print(f"  ✓ Поле описания найдено (contenteditable) через {waited:.1f}с")
                                        break
                                    # Или если это второй contenteditable div (первый может быть для чего-то другого)
                                    elif selector == 'div[contenteditable="true"]' and len(elements) > 1:
                                        # Берем второй contenteditable
                                        desc_field = elements[1] if len(elements) > 1 else elements[0]
                                        print(f"  ✓ Поле описания найдено (contenteditable, второй) через {waited:.1f}с")
                                        break
                                
                                # Для textarea
                                elif elem.tag_name == 'textarea':
                                    placeholder = elem.get_attribute('placeholder') or ''
                                    if 'описание' in placeholder.lower() or 'description' in placeholder.lower() or 'подробное' in placeholder.lower():
                                        desc_field = elem
                                        print(f"  ✓ Поле описания найдено (textarea) через {waited:.1f}с")
                                        break
                            
                            if desc_field:
                                break
                        except:
                            continue
                    
                    if not desc_field:
                        time.sleep(wait_interval)
                        waited += wait_interval
                
                # Если все еще не нашли, пробуем найти все textarea
                if not desc_field:
                    try:
                        all_textareas = self.driver.find_elements(By.TAG_NAME, 'textarea')
                        if len(all_textareas) > 1:
                            desc_field = all_textareas[1]  # Второй textarea обычно описание
                            print("  ✓ Поле описания найдено (второй textarea из списка)")
                        elif len(all_textareas) == 1:
                            # Проверяем, не название ли это
                            placeholder = all_textareas[0].get_attribute('placeholder') or ''
                            if 'описание' in placeholder.lower() or 'description' in placeholder.lower():
                                desc_field = all_textareas[0]
                                print("  ✓ Поле описания найдено (единственный textarea)")
                    except:
                        pass
                
                if desc_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                    time.sleep(1)
                    
                    # Если это contenteditable div, используем специальный метод
                    if desc_field.tag_name == 'div' and desc_field.get_attribute('contenteditable') == 'true':
                        try:
                            # Фокусируемся на поле
                            self.driver.execute_script("arguments[0].focus();", desc_field)
                            desc_field.click()
                            time.sleep(0.5)
                            
                            # Очищаем содержимое через выделение и удаление (как пользователь)
                            from selenium.webdriver.common.keys import Keys
                            desc_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                            time.sleep(0.2)
                            desc_field.send_keys(Keys.DELETE)  # Удаляем
                            time.sleep(0.3)
                            
                            # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод пользователя)
                            # Это критически важно - Pinterest может проверять, что ввод был реальным
                            desc_field.send_keys(description)
                            time.sleep(1.5)  # Даем время на обработку
                            
                            # Проверяем, что значение установилось
                            verify_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                            if verify_desc.strip() == description.strip():
                                print(f"✓ Описание заполнено (contenteditable): {description}")
                            else:
                                print(f"⚠ Описание не сохранилось, текущее: '{verify_desc[:50]}', ожидалось: '{description[:50]}'")
                                # Пробуем еще раз - выделяем весь текст и заменяем
                                try:
                                    desc_field.click()
                                    time.sleep(0.5)
                                    # Выделяем весь текст через Ctrl+A
                                    from selenium.webdriver.common.keys import Keys
                                    desc_field.send_keys(Keys.COMMAND + 'a')  # Mac
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)
                                    time.sleep(0.3)
                                    # Вводим текст заново
                                    desc_field.send_keys(description)
                                    time.sleep(1)
                                    verify_desc2 = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                                    if verify_desc2.strip() == description.strip():
                                        print(f"✓ Описание заполнено (повторная попытка): {description}")
                                    else:
                                        print(f"⚠ Описание все еще не сохранилось: '{verify_desc2[:50]}'")
                                except Exception as e3:
                                    print(f"⚠ Ошибка при повторной попытке: {e3}")
                        except Exception as e:
                            # Альтернативный способ для contenteditable
                            try:
                                desc_field.click()
                                time.sleep(0.5)
                                desc_field.send_keys(description)
                                time.sleep(1)
                                verify_desc = desc_field.text or desc_field.get_attribute('innerText') or ''
                                if verify_desc.strip() == description.strip():
                                    print(f"✓ Описание заполнено (send_keys): {description}")
                                else:
                                    print(f"⚠ Описание не сохранилось через send_keys: '{verify_desc[:50]}'")
                            except:
                                print(f"⚠ Ошибка заполнения contenteditable: {e}")
                    else:
                        # Для textarea используем стандартный способ
                        try:
                            self.driver.execute_script("arguments[0].value = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", desc_field)
                            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", desc_field)
                            print(f"✓ Описание заполнено через JS: {description}")
                        except:
                            # Если JS не сработал, пробуем обычный способ
                            desc_field.click()
                            time.sleep(0.5)
                            desc_field.clear()
                            desc_field.send_keys(description)
                            print(f"✓ Описание заполнено: {description}")
                else:
                    print("⚠ Поле описания не найдено по селекторам, пробуем альтернативный метод...")
                    # Пробуем найти все textarea и contenteditable и использовать второй как описание
                    try:
                        all_textareas = self.driver.find_elements(By.TAG_NAME, 'textarea')
                        all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                        print(f"  Найдено textarea: {len(all_textareas)}, contenteditable: {len(all_contenteditable)}")
                        
                        # Пробуем использовать contenteditable (приоритет) или textarea как описание
                        if len(all_contenteditable) > 0:
                            # Используем первый contenteditable (обычно это описание)
                            desc_field = all_contenteditable[0]
                            print(f"  Используем contenteditable как описание")
                        elif len(all_textareas) > 1:
                            desc_field = all_textareas[1]
                            print(f"  Используем второй textarea как описание")
                        elif len(all_textareas) == 1:
                            # Проверяем placeholder - если не название, то это описание
                            placeholder = all_textareas[0].get_attribute('placeholder') or ''
                            if 'название' not in placeholder.lower() and 'title' not in placeholder.lower():
                                desc_field = all_textareas[0]
                                print(f"  Используем единственный textarea как описание")
                        
                        # Если нашли поле, заполняем его
                        if desc_field:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                            time.sleep(1)
                            
                            if desc_field.tag_name == 'div' and desc_field.get_attribute('contenteditable') == 'true':
                                try:
                                    # Фокусируемся на поле
                                    self.driver.execute_script("arguments[0].focus();", desc_field)
                                    desc_field.click()
                                    time.sleep(0.5)
                                    
                                    # Очищаем через выделение и удаление (как пользователь)
                                    from selenium.webdriver.common.keys import Keys
                                    desc_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)  # Удаляем
                                    time.sleep(0.3)
                                    
                                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                                    desc_field.send_keys(description)
                                    time.sleep(1.5)  # Даем время на обработку
                                    # Снимаем фокус для сохранения
                                    self.driver.execute_script("arguments[0].blur();", desc_field)
                                    time.sleep(0.5)
                                    # Кликаем вне поля для триггера сохранения
                                    self.driver.execute_script("document.body.click();")
                                    time.sleep(0.5)
                                    print(f"✓ Описание заполнено (contenteditable, альтернативный метод): {description}")
                                except Exception as e:
                                    print(f"⚠ Ошибка заполнения contenteditable: {e}")
                            else:
                                try:
                                    # Для textarea используем send_keys
                                    desc_field.click()
                                    time.sleep(0.3)
                                    from selenium.webdriver.common.keys import Keys
                                    desc_field.send_keys(Keys.COMMAND + 'a')
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)
                                    time.sleep(0.3)
                                    desc_field.send_keys(description)
                                    time.sleep(1.5)
                                    # Снимаем фокус для сохранения
                                    desc_field.send_keys(Keys.TAB)  # Tab для снятия фокуса
                                    time.sleep(0.5)
                                    # Кликаем вне поля для триггера сохранения
                                    self.driver.execute_script("document.body.click();")
                                    time.sleep(0.5)
                                    print(f"✓ Описание заполнено (альтернативный метод): {description}")
                                except Exception as e:
                                    print(f"⚠ Ошибка заполнения textarea: {e}")
                        else:
                            print("  ⚠ Не удалось найти поле описания альтернативным методом")
                    except Exception as e_alt:
                        print(f"  ⚠ Ошибка при альтернативном поиске описания: {e_alt}")
            except Exception as e:
                print(f"⚠ Ошибка при заполнении описания: {e}")
            
            # Шаг 5: Заполняем ссылку
            print("\n5. Заполнение ссылки...")
            try:
                link_field = None
                
                # Способ 1: Поиск по ID (из анализа страницы)
                try:
                    link_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, 'WebsiteField'))
                    )
                    print("  ✓ Поле ссылки найдено по ID")
                except:
                    pass
                
                # Способ 2: Поиск по типу и placeholder
                if not link_field:
                    link_selectors = [
                        'input[type="url"]',
                        'input[placeholder*="ссылк" i]',
                        'input[placeholder*="link" i]',
                        'input[placeholder*="Добавить ссылку" i]'
                    ]
                    
                    for selector in link_selectors:
                        try:
                            link_field = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            # Проверяем, что это поле ссылки (не название)
                            placeholder = link_field.get_attribute('placeholder') or ''
                            if 'ссылк' in placeholder.lower() or 'link' in placeholder.lower() or selector == 'input[type="url"]':
                                break
                        except:
                            continue
                
                if link_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                    time.sleep(1)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод пользователя)
                    try:
                        link_field.click()
                        time.sleep(0.3)
                        
                        # Очищаем поле через выделение и удаление (как пользователь)
                        from selenium.webdriver.common.keys import Keys
                        link_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                        time.sleep(0.2)
                        link_field.send_keys(Keys.DELETE)  # Удаляем
                        time.sleep(0.3)
                        
                        # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                        link_field.send_keys(link)
                        time.sleep(1.5)  # Даем время на обработку
                        
                        # Проверяем, что значение установилось
                        verify_link = link_field.get_attribute('value') or ''
                        if verify_link.strip() == link.strip():
                            print(f"✓ Ссылка заполнена: {link}")
                        else:
                            print(f"⚠ Ссылка не сохранилась, текущее: '{verify_link}'")
                            # Пробуем еще раз
                            try:
                                link_field.click()
                                time.sleep(0.3)
                                link_field.send_keys(Keys.COMMAND + 'a')
                                time.sleep(0.2)
                                link_field.send_keys(Keys.DELETE)
                                time.sleep(0.3)
                                link_field.send_keys(link)
                                time.sleep(1.5)
                                verify_link2 = link_field.get_attribute('value') or ''
                                if verify_link2.strip() == link.strip():
                                    print(f"✓ Ссылка заполнена (повторная попытка): {link}")
                                else:
                                    print(f"⚠ Ссылка все еще не сохранилась: '{verify_link2}'")
                            except Exception as e2:
                                print(f"⚠ Ошибка при повторной попытке: {e2}")
                    except Exception as e:
                        print(f"⚠ Ошибка заполнения ссылки: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print("⚠ Поле ссылки не найдено")
            except Exception as e:
                print(f"⚠ Ошибка при заполнении ссылки: {e}")
            
            # Доска уже выбрана выше (Шаг 2), пропускаем этот шаг
            # После выбора доски проверяем и восстанавливаем значения полей, если они сбросились
            print("\nПроверка и восстановление значений полей после выбора доски...")
            time.sleep(2)  # Даем время на закрытие модального окна
            
            try:
                # Проверяем поле названия
                try:
                    title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                    current_title = title_field.get_attribute('value') or ''
                    print(f"  Текущее значение названия: '{current_title}'")
                    if not current_title or current_title.strip() != title.strip():
                        print("  Восстанавливаем название...")
                        self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", title_field)
                        time.sleep(0.5)
                        # Проверяем, что значение установилось
                        verify_title = title_field.get_attribute('value') or ''
                        print(f"  ✓ Название восстановлено: '{verify_title}'")
                except Exception as e:
                    print(f"  ⚠ Ошибка при проверке названия: {e}")
                
                # Проверяем поле описания
                try:
                    all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                    print(f"  Найдено contenteditable элементов: {len(all_contenteditable)}")
                    if all_contenteditable:
                        desc_field = all_contenteditable[0]
                        current_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        print(f"  Текущее значение описания: '{current_desc[:50]}'")
                        if not current_desc or current_desc.strip() != description.strip():
                            print("  Восстанавливаем описание...")
                            # Прокручиваем к полю
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                            time.sleep(0.5)
                            # Кликаем на поле
                            desc_field.click()
                            time.sleep(0.5)
                            # Очищаем содержимое
                            self.driver.execute_script("arguments[0].innerText = '';", desc_field)
                            self.driver.execute_script("arguments[0].textContent = '';", desc_field)
                            time.sleep(0.3)
                            # Вставляем текст
                            self.driver.execute_script("arguments[0].innerText = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].textContent = arguments[1];", desc_field, description)
                            # Триггерим события
                            self.driver.execute_script("""
                                var event = new Event('input', { bubbles: true });
                                arguments[0].dispatchEvent(event);
                                var changeEvent = new Event('change', { bubbles: true });
                                arguments[0].dispatchEvent(changeEvent);
                            """, desc_field)
                            time.sleep(0.5)
                            # Проверяем, что значение установилось
                            verify_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                            print(f"  ✓ Описание восстановлено: '{verify_desc[:50]}'")
                        else:
                            print(f"  ✓ Описание уже заполнено: '{current_desc[:50]}'")
                except Exception as e:
                    print(f"  ⚠ Ошибка при проверке описания: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Проверяем поле ссылки
                try:
                    link_field = self.driver.find_element(By.ID, 'WebsiteField')
                    current_link = link_field.get_attribute('value') or ''
                    print(f"  Текущее значение ссылки: '{current_link}'")
                    if not current_link or current_link.strip() != link.strip():
                        print("  Восстанавливаем ссылку...")
                        # Прокручиваем к полю
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                        time.sleep(0.5)
                        # Кликаем на поле
                        link_field.click()
                        time.sleep(0.3)
                        # Очищаем поле полностью
                        link_field.clear()
                        time.sleep(0.3)
                        # Также очищаем через JS
                        self.driver.execute_script("arguments[0].value = '';", link_field)
                        time.sleep(0.2)
                        # Заполняем через JS
                        self.driver.execute_script("arguments[0].value = arguments[1];", link_field, link)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", link_field)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", link_field)
                        time.sleep(0.5)
                        # Проверяем, что значение установилось
                        verify_link = link_field.get_attribute('value') or ''
                        if verify_link.strip() != link.strip():
                            # Если не сработало, пробуем через send_keys (только если поле пустое)
                            if not verify_link.strip():
                                link_field.send_keys(link)
                                time.sleep(0.5)
                                verify_link = link_field.get_attribute('value') or ''
                        print(f"  ✓ Ссылка восстановлена: '{verify_link}'")
                    else:
                        print(f"  ✓ Ссылка уже заполнена: '{current_link}'")
                except Exception as e:
                    print(f"  ⚠ Ошибка при проверке ссылки: {e}")
                    import traceback
                    traceback.print_exc()
            except Exception as e:
                print(f"  ⚠ Ошибка при восстановлении полей: {e}")
                import traceback
                traceback.print_exc()
            
            # Старый код выбора доски удален - доска выбирается в Шаге 2
            
            # Шаг 6: Публикуем пин
                if all_board_elements:
                    print(f"  Найдено {len(all_board_elements)} элементов, связанных с досками")
                    for i, elem in enumerate(all_board_elements[:5], 1):
                        try:
                            tag = elem.tag_name
                            placeholder = elem.get_attribute('placeholder') or ''
                            text = elem.text.strip()[:50] or ''
                            print(f"    {i}. {tag}: placeholder='{placeholder[:30]}', text='{text}'")
                        except:
                            pass
                # Пробуем разные селекторы для поля выбора доски
                # ВАЖНО: Ищем поле выбора доски в форме создания пина, НЕ глобальный поиск
                board_selectors = [
                    # По placeholder
                    'input[placeholder*="Выберите доску" i]',
                    'input[placeholder*="Select board" i]',
                    'input[placeholder*="доск" i]',
                    'input[placeholder*="board" i]',
                    # По label и связанному input
                    'label:has-text("Доска") + input',
                    'label:has-text("Board") + input',
                    # По div с текстом "Доска" и связанному input
                    'div:has-text("Доска") input',
                    'div:has-text("Board") input',
                    # По классам
                    'div[class*="board"] input[placeholder*="доск" i]',
                    'div[class*="board"] input[placeholder*="board" i]',
                    'div[class*="Board"] input',
                    # Кнопки и div с role="button"
                    'button[aria-label*="доск" i]',
                    'button[aria-label*="board" i]',
                    'div[role="button"][aria-label*="доск" i]',
                    'div[role="button"][aria-label*="board" i]',
                    # Поиск через XPath по тексту "Доска"
                    None  # Будет обработан отдельно
                ]
                
                board_field = None
                for selector in board_selectors:
                    try:
                        if selector is None:
                            # XPath поиск по тексту "Доска" и связанному элементу
                            try:
                                # Ищем label или div с текстом "Доска"
                                label = self.driver.find_element(By.XPATH,
                                    "//label[contains(text(), 'Доска')] | //div[contains(text(), 'Доска')] | //span[contains(text(), 'Доска')]")
                                # Ищем следующий input или button
                                board_field = label.find_element(By.XPATH,
                                    "./following-sibling::input | ./following-sibling::button | ./following-sibling::div[@role='button'] | ./ancestor::div[1]//input | ./ancestor::div[1]//button")
                                if board_field and board_field.is_displayed():
                                    break
                            except:
                                pass
                        else:
                            board_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                            # Проверяем, что это не глобальный поиск
                            if board_field and board_field.is_displayed():
                                # Проверяем, что это поле в форме создания пина (не в header/sidebar)
                                try:
                                    # Исключаем элементы в header или sidebar
                                    is_in_header = board_field.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav | ./ancestor::*[contains(@class, "header")] | ./ancestor::*[contains(@class, "sidebar")]')
                                    if not is_in_header:
                                        # Проверяем placeholder для уверенности
                                        placeholder = board_field.get_attribute('placeholder') or ''
                                        if 'доск' in placeholder.lower() or 'board' in placeholder.lower() or 'выберите' in placeholder.lower() or 'select' in placeholder.lower():
                                            break
                                except:
                                    # Если не можем проверить, все равно используем
                                    break
                    except:
                        continue
                
                if board_field:
                    # Кликаем на поле выбора доски
                    print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                    time.sleep(1)
                    
                    # Пробуем кликнуть разными способами
                    clicked = False
                    try:
                        board_field.click()
                        clicked = True
                    except:
                        try:
                            self.driver.execute_script("arguments[0].click();", board_field)
                            clicked = True
                        except:
                            pass
                    
                    if clicked:
                        print("✓ Поле выбора доски открыто")
                    else:
                        print("⚠ Не удалось кликнуть на поле выбора доски")
                    
                    # Ждем открытия модального окна с выбором доски
                    print("  Ожидание открытия модального окна...")
                    time.sleep(2)
                    
                    # Пробуем найти модальное окно
                    modal_visible = False
                    for attempt in range(5):  # Проверяем до 5 раз
                        try:
                            # Ищем модальное окно (overlay, dialog, modal)
                            modals = self.driver.find_elements(By.CSS_SELECTOR,
                                'div[role="dialog"], div[class*="modal"], div[class*="overlay"], div[class*="dialog"]')
                            
                            # Также ищем по наличию поисковой строки "Поиск"
                            search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                            
                            if modals or search_inputs:
                                visible_modals = [m for m in modals if m.is_displayed()]
                                visible_search = [s for s in search_inputs if s.is_displayed()]
                                if visible_modals or visible_search:
                                    modal_visible = True
                                    print(f"  ✓ Модальное окно открыто")
                                    break
                        except:
                            pass
                        if attempt < 4:
                            time.sleep(0.5)
                    
                    if not modal_visible:
                        print("  ⚠ Модальное окно не найдено, ждем еще...")
                        time.sleep(2)
                    
                    # Ищем доску в модальном окне
                    print("  Поиск доски в модальном окне...")
                    board_options = []
                    
                    # Ищем доску в модальном окне - пробуем разные способы
                    # ВАЖНО: Ищем в списке досок БЕЗ использования поиска
                    
                    # Способ 1: Ищем список досок в модальном окне (обычно это div с классом или ролью)
                    try:
                        # Ищем контейнер со списком досок (обычно после текста "Все доски" или подобного)
                        list_containers = self.driver.find_elements(By.XPATH,
                            "//div[@role='dialog']//div[contains(text(), 'Все доски') or contains(text(), 'All boards')]/following-sibling::div | //div[@role='dialog']//div[contains(text(), 'Все доски') or contains(text(), 'All boards')]/parent::div//div")
                        
                        board_options = []
                        for container in list_containers:
                            if container.is_displayed():
                                # Ищем все элементы внутри контейнера с текстом доски
                                items = container.find_elements(By.XPATH, f".//*[contains(text(), '{board_name}')]")
                                for item in items:
                                    if item.is_displayed() and len(item.text.strip()) < 100:
                                        # Проверяем, что это не поисковая строка
                                        text = item.text.strip().lower()
                                        if 'поиск' not in text and 'search' not in text:
                                            board_options.append(item)
                        
                        if board_options:
                            print(f"  Найдено {len(board_options)} потенциальных досок в списке")
                    except:
                        pass
                    
                    # Способ 2: Ищем все кликабельные элементы в модальном окне с текстом доски
                    if not board_options:
                        try:
                            # Ищем все элементы в модальном окне с текстом доски
                            all_elements = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[contains(text(), '{board_name}') and not(self::input) and not(self::textarea)]")
                            
                            board_options = []
                            for elem in all_elements:
                                try:
                                    if elem.is_displayed():
                                        text = elem.text.strip()
                                        # Проверяем, что текст содержит название доски и не слишком длинный
                                        if text and len(text) < 100 and board_name.lower() in text.lower():
                                            # Проверяем, что это не поисковая строка или другие элементы
                                            text_lower = text.lower()
                                            if ('поиск' not in text_lower and 'search' not in text_lower and 
                                                'создать' not in text_lower and 'create' not in text_lower):
                                                board_options.append(elem)
                                except:
                                    continue
                            
                            if board_options:
                                print(f"  Найдено {len(board_options)} потенциальных досок в модальном окне")
                        except:
                            pass
                    
                    # Способ 2: Ищем по точному тексту
                    if not board_options:
                        try:
                            board_options = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[normalize-space(text())='{board_name}' and not(self::input)]")
                            board_options = [opt for opt in board_options if opt.is_displayed()]
                            if board_options:
                                print(f"  Найдено {len(board_options)} элементов с точным текстом '{board_name}'")
                        except:
                            pass
                    
                    # Способ 3: Ищем элементы с вхождением названия доски
                    if not board_options:
                        try:
                            board_options = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[contains(normalize-space(text()), '{board_name}') and not(self::input)]")
                            # Фильтруем видимые и короткие (названия досок обычно короткие)
                            board_options = [opt for opt in board_options 
                                           if opt.is_displayed() and len(opt.text.strip()) < 100]
                            if board_options:
                                print(f"  Найдено {len(board_options)} элементов с текстом '{board_name}'")
                        except:
                            pass
                    
                    # Способ 2: Ищем в контейнерах модального окна
                    if not board_options:
                        try:
                            # Ищем контейнеры модального окна
                            modal_containers = self.driver.find_elements(By.CSS_SELECTOR,
                                'div[role="dialog"], div[class*="modal"], div[class*="overlay"], div[class*="dialog"], div[class*="listbox"]')
                            
                            for container in modal_containers:
                                if container.is_displayed():
                                    # Ищем все элементы внутри контейнера с текстом доски
                                    items = container.find_elements(By.XPATH,
                                        f".//*[contains(text(), '{board_name}') and not(self::input)]")
                                    if items:
                                        board_options = [item for item in items if item.is_displayed()]
                                        if board_options:
                                            print(f"  Найдено {len(board_options)} опций в модальном окне")
                                            break
                        except:
                            pass
                    
                    # Способ 3: Ищем кликабельные элементы (div, button) с текстом доски
                    if not board_options:
                        try:
                            clickable_with_text = self.driver.find_elements(By.XPATH,
                                f"//div[contains(text(), '{board_name}')] | //button[contains(text(), '{board_name}')]")
                            board_options = [item for item in clickable_with_text if item.is_displayed()]
                            if board_options:
                                print(f"  Найдено {len(board_options)} кликабельных элементов")
                        except:
                            pass
                    
                    board_found = False
                    print(f"  Проверка {len(board_options)} найденных элементов...")
                    for i, option in enumerate(board_options, 1):
                        try:
                            option_text = option.text.strip()
                            # Выводим для отладки первые несколько
                            if i <= 3:
                                print(f"    Элемент {i}: '{option_text[:50]}'")
                            
                            # Проверяем точное совпадение или вхождение названия доски
                            if option_text and (
                                option_text.lower() == board_name.lower() or
                                option_text.lower().strip() == board_name.lower() or
                                board_name.lower() in option_text.lower() or
                                option_text.lower() in board_name.lower()
                            ):
                                print(f"  ✓ Найдена подходящая доска: '{option_text}'")
                                
                                # Прокручиваем к опции
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                time.sleep(0.5)
                                
                                # Пробуем кликнуть - несколько способов
                                clicked = False
                                
                                # Способ 1: Ищем кликабельный родительский элемент
                                try:
                                    # Ищем родительский div или button, который может быть кликабельным
                                    parent = option.find_element(By.XPATH, 
                                        './ancestor::div[@role="button" or @onclick or contains(@class, "click")][1] | ./ancestor::button[1] | ./parent::div[1]')
                                    if parent:
                                        parent.click()
                                        clicked = True
                                        print(f"  ✓ Клик на родительский элемент")
                                except:
                                    pass
                                
                                # Способ 2: Прямой клик на элемент
                                if not clicked:
                                    try:
                                        option.click()
                                        clicked = True
                                        print(f"  ✓ Прямой клик на элемент")
                                    except:
                                        pass
                                
                                # Способ 3: Клик через JS
                                if not clicked:
                                    try:
                                        self.driver.execute_script("arguments[0].click();", option)
                                        clicked = True
                                        print(f"  ✓ Клик через JS")
                                    except:
                                        pass
                                
                                # Способ 4: Клик на родительский элемент через JS
                                if not clicked:
                                    try:
                                        parent = self.driver.execute_script("return arguments[0].parentElement || arguments[0].closest('div[role=\"button\"]') || arguments[0].closest('button');", option)
                                        if parent:
                                            self.driver.execute_script("arguments[0].click();", parent)
                                            clicked = True
                                            print(f"  ✓ Клик на родитель через JS")
                                    except:
                                        pass
                                
                                if clicked:
                                    print(f"✓ Доска выбрана из модального окна: {board_name}")
                                    board_found = True
                                    board_selected = True
                                    time.sleep(2)  # Ждем закрытия модального окна
                                    break
                                else:
                                    print(f"  ⚠ Не удалось кликнуть на элемент {i}")
                        except Exception as e_opt:
                            if i <= 3:
                                print(f"  ⚠ Ошибка при обработке элемента {i}: {e_opt}")
                            continue
                    
                    # ТОЛЬКО если не нашли в списке, используем поиск ВНУТРИ модального окна
                    if not board_found:
                        print(f"⚠ Доска '{board_name}' не найдена в списке, используем поиск в модальном окне...")
                        try:
                            # ВАЖНО: Ищем поле поиска ТОЛЬКО внутри модального окна (dialog), НЕ глобальный поиск
                            time.sleep(1)
                            
                            # Ищем модальное окно
                            modal = None
                            try:
                                modal = self.driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"]')
                            except:
                                pass
                            
                            if modal:
                                # Ищем поле поиска ВНУТРИ модального окна
                                search_inputs = modal.find_elements(By.CSS_SELECTOR, 
                                    'input[placeholder*="Поиск" i], input[placeholder*="Search" i], input[type="search"], input[type="text"]')
                                
                                # Фильтруем - берем только поле поиска в модальном окне
                                input_field = None
                                for inp in search_inputs:
                                    if inp.is_displayed():
                                        placeholder = inp.get_attribute('placeholder') or ''
                                        # Проверяем, что это поле поиска в модальном окне (не глобальный поиск)
                                        if 'поиск' in placeholder.lower() or 'search' in placeholder.lower():
                                            input_field = inp
                                            break
                                
                                if input_field:
                                    print("  ✓ Найдено поле поиска в модальном окне")
                                    # Очищаем поле
                                    input_field.clear()
                                    time.sleep(0.5)
                                    
                                    # Вводим название доски
                                    input_field.send_keys(board_name)
                                    time.sleep(2)  # Ждем результатов поиска досок
                                    
                                    # Ищем в результатах поиска - пробуем разные селекторы
                                    search_results = []
                                
                                # Способ 1: Стандартные селекторы
                                search_selectors = [
                                    'div[role="option"]',
                                    'li[role="option"]',
                                    'div[class*="option"]',
                                    'li[class*="option"]',
                                    'div[class*="item"]',
                                    'li[class*="item"]',
                                    'div[class*="board"]',
                                    'li[class*="board"]'
                                ]
                                
                                for selector in search_selectors:
                                    try:
                                        results = self.driver.find_elements(By.CSS_SELECTOR, selector)
                                        visible_results = [r for r in results if r.is_displayed()]
                                        if visible_results:
                                            search_results = visible_results
                                            print(f"  Найдено {len(search_results)} результатов поиска через селектор")
                                            break
                                    except:
                                        continue
                                
                                # Способ 2: Поиск по тексту (точное совпадение или вхождение)
                                if not search_results:
                                    try:
                                        # Сначала точное совпадение
                                        search_results = self.driver.find_elements(By.XPATH,
                                            f"//*[normalize-space(text())='{board_name}' and not(self::input)]")
                                        if not search_results:
                                            # Потом вхождение
                                            search_results = self.driver.find_elements(By.XPATH,
                                                f"//*[contains(normalize-space(text()), '{board_name}') and not(self::input)]")
                                        search_results = [r for r in search_results if r.is_displayed() and len(r.text.strip()) < 100]
                                        if search_results:
                                            print(f"  Найдено {len(search_results)} результатов по тексту")
                                    except:
                                        pass
                                
                                # Кликаем на первый подходящий результат
                                print(f"  Обработка {len(search_results)} результатов поиска...")
                                for i, result in enumerate(search_results, 1):
                                    try:
                                        result_text = result.text.strip()
                                        # Выводим информацию для отладки
                                        if i <= 3:  # Показываем первые 3 для отладки
                                            print(f"    Результат {i}: '{result_text[:50]}'")
                                        
                                        # Проверяем, что это действительно доска
                                        # Ищем точное совпадение или вхождение названия доски
                                        text_lower = result_text.lower()
                                        board_lower = board_name.lower()
                                        
                                        if result_text and (
                                            board_lower == text_lower or
                                            board_lower in text_lower or
                                            text_lower.startswith(board_lower) or
                                            f" {board_lower} " in f" {text_lower} " or
                                            f" {board_lower}\n" in f" {text_lower}\n"
                                        ):
                                            print(f"  ✓ Найдена подходящая доска: '{result_text[:50]}'")
                                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", result)
                                            time.sleep(0.5)
                                            
                                            # Пробуем кликнуть - несколько способов
                                            clicked = False
                                            
                                            # Способ 1: Прямой клик
                                            try:
                                                result.click()
                                                clicked = True
                                            except:
                                                pass
                                            
                                            # Способ 2: Через JS
                                            if not clicked:
                                                try:
                                                    self.driver.execute_script("arguments[0].click();", result)
                                                    clicked = True
                                                except:
                                                    pass
                                            
                                            # Способ 3: Клик на родительский элемент
                                            if not clicked:
                                                try:
                                                    parent = self.driver.execute_script("return arguments[0].parentElement;", result)
                                                    if parent:
                                                        self.driver.execute_script("arguments[0].click();", parent)
                                                        clicked = True
                                                except:
                                                    pass
                                            
                                            # Способ 4: Ищем кликабельный родитель
                                            if not clicked:
                                                try:
                                                    clickable_parent = result.find_element(By.XPATH, 
                                                        "./ancestor::div[contains(@class, 'board') or contains(@role, 'option') or @onclick] | ./ancestor::button[1]")
                                                    if clickable_parent:
                                                        clickable_parent.click()
                                                        clicked = True
                                                except:
                                                    pass
                                            
                                            if clicked:
                                                board_selected = True
                                                print(f"✓ Доска выбрана из результатов поиска: {board_name}")
                                                time.sleep(1)  # Ждем закрытия модального окна
                                                break
                                            else:
                                                print(f"  ⚠ Не удалось кликнуть на результат {i}")
                                    except Exception as e_result:
                                        if i <= 3:  # Показываем ошибки для первых 3
                                            print(f"  ⚠ Ошибка при обработке результата {i}: {e_result}")
                                        continue
                                
                                    if not board_selected:
                                        print(f"⚠ Результаты поиска не найдены, пробуем Enter...")
                                        # Если не нашли в результатах, пробуем Enter (но это не идеально)
                                        input_field.send_keys(Keys.ENTER)
                                        board_selected = True
                                        print(f"✓ Доска введена через Enter: {board_name}")
                                else:
                                    print("  ⚠ Поле поиска в модальном окне не найдено")
                            else:
                                print("  ⚠ Модальное окно не найдено для поиска")
                        except Exception as e2:
                            print(f"⚠ Не удалось использовать поиск доски: {e2}")
                            import traceback
                            traceback.print_exc()
                else:
                    print("⚠ Поле выбора доски не найдено, пробуем альтернативные методы...")
                    # Пробуем найти поле через более широкий поиск
                    try:
                        # Ищем все input и button элементы на странице
                        all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                        all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                        all_divs = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                        
                        print(f"  Проверка {len(all_inputs)} input, {len(all_buttons)} button, {len(all_divs)} div[role='button']...")
                        
                        for elem in all_inputs + all_buttons + all_divs:
                            try:
                                if not elem.is_displayed():
                                    continue
                                placeholder = elem.get_attribute('placeholder') or ''
                                aria_label = elem.get_attribute('aria-label') or ''
                                text = elem.text.strip() or ''
                                
                                # Проверяем, что это поле выбора доски
                                if ('доск' in placeholder.lower() or 'board' in placeholder.lower() or
                                    'доск' in aria_label.lower() or 'board' in aria_label.lower() or
                                    'доск' in text.lower() or 'board' in text.lower()):
                                    # Проверяем, что это не глобальный поиск
                                    is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                                    if not is_in_header:
                                        board_field = elem
                                        print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}, placeholder='{placeholder[:30]}'")
                                        break
                            except:
                                continue
                        
                        if board_field:
                            # Используем найденное поле - продолжаем выполнение
                            print(f"  ✓ Поле найдено через альтернативный метод")
                            # Теперь используем найденное поле - переходим к открытию модального окна
                            # Кликаем на поле выбора доски
                            print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                            time.sleep(1)
                            
                            # Пробуем кликнуть разными способами
                            clicked = False
                            try:
                                board_field.click()
                                clicked = True
                            except:
                                try:
                                    self.driver.execute_script("arguments[0].click();", board_field)
                                    clicked = True
                                except:
                                    pass
                            
                            if clicked:
                                print("✓ Поле выбора доски открыто")
                                # Продолжаем с открытием модального окна и выбором доски
                                # Используем ту же логику, что и в основном блоке выше
                                # Ждем открытия модального окна
                                print("  Ожидание открытия модального окна...")
                                time.sleep(2)
                                
                                # Ищем модальное окно и доску (код будет выполнен ниже в основном блоке)
                                # Но так как мы уже кликнули, нужно найти модальное окно здесь
                                modal_visible = False
                                for attempt in range(5):
                                    try:
                                        modals = self.driver.find_elements(By.CSS_SELECTOR,
                                            'div[role="dialog"], div[class*="modal"], div[class*="overlay"]')
                                        search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                            'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                                        if modals or search_inputs:
                                            visible_modals = [m for m in modals if m.is_displayed()]
                                            visible_search = [s for s in search_inputs if s.is_displayed()]
                                            if visible_modals or visible_search:
                                                modal_visible = True
                                                print(f"  ✓ Модальное окно открыто")
                                                break
                                    except:
                                        pass
                                    if attempt < 4:
                                        time.sleep(0.5)
                                
                                if modal_visible:
                                    # Ищем доску в модальном окне
                                    print("  Поиск доски в модальном окне...")
                                    
                                    # Отладка: выводим все элементы в модальном окне
                                    try:
                                        all_modal_elements = self.driver.find_elements(By.XPATH,
                                            "//div[@role='dialog']//*[not(self::input) and not(self::textarea) and text()]")
                                        print(f"  Найдено {len(all_modal_elements)} элементов с текстом в модальном окне")
                                        for i, elem in enumerate(all_modal_elements[:10], 1):  # Первые 10
                                            try:
                                                text = elem.text.strip()[:50]
                                                if text:
                                                    print(f"    {i}. '{text}'")
                                            except:
                                                pass
                                    except:
                                        pass
                                    
                                    board_options = []
                                    
                                    # Способ 1: Точное совпадение
                                    try:
                                        board_options = self.driver.find_elements(By.XPATH,
                                            f"//div[@role='dialog']//*[normalize-space(text())='{board_name}' and not(self::input)]")
                                        board_options = [opt for opt in board_options if opt.is_displayed()]
                                        if board_options:
                                            print(f"  Найдено {len(board_options)} элементов с точным текстом")
                                    except:
                                        pass
                                    
                                    # Способ 2: Вхождение
                                    if not board_options:
                                        try:
                                            board_options = self.driver.find_elements(By.XPATH,
                                                f"//div[@role='dialog']//*[contains(text(), '{board_name}') and not(self::input) and not(self::textarea)]")
                                            board_options = [opt for opt in board_options 
                                                           if opt.is_displayed() and len(opt.text.strip()) < 100]
                                            if board_options:
                                                print(f"  Найдено {len(board_options)} элементов с вхождением текста")
                                        except:
                                            pass
                                    
                                    # Кликаем на найденную доску
                                    if board_options:
                                        print(f"  Проверка {len(board_options)} найденных элементов...")
                                        for i, option in enumerate(board_options, 1):
                                            try:
                                                option_text = option.text.strip()
                                                if i <= 5:  # Показываем больше для отладки
                                                    print(f"    Элемент {i}: '{option_text[:50]}'")
                                                
                                                # Проверяем совпадение (точное или частичное)
                                                text_lower = option_text.lower()
                                                board_lower = board_name.lower()
                                                
                                                # Убираем подчеркивания для сравнения
                                                text_clean = text_lower.replace('_', '').replace('-', '').strip()
                                                board_clean = board_lower.replace('_', '').replace('-', '').strip()
                                                
                                                if (board_lower == text_lower or 
                                                    board_lower in text_lower or 
                                                    text_lower in board_lower or
                                                    board_clean == text_clean or
                                                    board_clean in text_clean):
                                                    print(f"  ✓ Найдена подходящая доска: '{option_text}'")
                                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                                    time.sleep(0.5)
                                                    
                                                    # Пробуем кликнуть
                                                    clicked = False
                                                    try:
                                                        option.click()
                                                        clicked = True
                                                    except:
                                                        try:
                                                            self.driver.execute_script("arguments[0].click();", option)
                                                            clicked = True
                                                        except:
                                                            # Пробуем кликнуть на родителя
                                                            try:
                                                                parent = self.driver.execute_script("return arguments[0].parentElement;", option)
                                                                if parent:
                                                                    self.driver.execute_script("arguments[0].click();", parent)
                                                                    clicked = True
                                                            except:
                                                                pass
                                                    
                                                    if clicked:
                                                        board_selected = True
                                                        print(f"✓ Доска выбрана: {board_name}")
                                                        time.sleep(2)
                                                        break
                                            except Exception as e_opt:
                                                if i <= 3:
                                                    print(f"  ⚠ Ошибка при обработке элемента {i}: {e_opt}")
                                                continue
                                    else:
                                        print("  ⚠ Доска не найдена в модальном окне")
                                        # Пробуем найти все доски в модальном окне и выбрать первую доступную
                                        try:
                                            all_boards = self.driver.find_elements(By.XPATH,
                                                "//div[@role='dialog']//*[text() and not(self::input) and not(self::textarea)]")
                                            print(f"  Всего элементов в модальном окне: {len(all_boards)}")
                                            
                                            # Ищем кликабельные элементы, которые могут быть досками
                                            for i, elem in enumerate(all_boards, 1):
                                                try:
                                                    text = elem.text.strip()
                                                    if text and len(text) < 50 and len(text) > 0:
                                                        print(f"    Элемент {i}: '{text}'")
                                                        
                                                        # Пропускаем служебные элементы
                                                        text_lower = text.lower()
                                                        if ('поиск' not in text_lower and 'search' not in text_lower and 
                                                            'создать' not in text_lower and 'create' not in text_lower and
                                                            'все доски' not in text_lower and 'all boards' not in text_lower and
                                                            'найдена доска' not in text_lower):
                                                            # Пробуем кликнуть на этот элемент
                                                            try:
                                                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                                                time.sleep(0.5)
                                                                self.driver.execute_script("arguments[0].click();", elem)
                                                                board_selected = True
                                                                print(f"✓ Доска выбрана (первая доступная): '{text}'")
                                                                time.sleep(2)
                                                                break
                                                            except:
                                                                continue
                                                except:
                                                    continue
                                        except:
                                            pass
                            else:
                                print("⚠ Не удалось кликнуть на поле выбора доски")
                        else:
                            print("  ⚠ Поле выбора доски не найдено ни одним способом")
                            board_field = None
                    except Exception as e_alt:
                        print(f"  ⚠ Ошибка при альтернативном поиске: {e_alt}")
                
                if not board_selected:
                    print("⚠ ВНИМАНИЕ: Доска не выбрана! Публикация может не пройти.")
                    
            except Exception as e:
                print(f"⚠ Ошибка при выборе доски: {e}")
                import traceback
                traceback.print_exc()
            
            # Финальная проверка всех полей перед публикацией
            print("\nФинальная проверка всех полей перед публикацией...")
            try:
                # Проверяем название
                try:
                    title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                    final_title = title_field.get_attribute('value') or ''
                    if not final_title or final_title.strip() != title.strip():
                        print(f"  ⚠ Название пустое или неверное: '{final_title}', заполняем заново...")
                        self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                        time.sleep(0.5)
                    else:
                        print(f"  ✓ Название заполнено: '{final_title}'")
                except:
                    print("  ⚠ Не удалось проверить название")
                
                # Проверяем описание
                try:
                    all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                    if all_contenteditable:
                        desc_field = all_contenteditable[0]
                        final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        if not final_desc or final_desc.strip() != description.strip():
                            print(f"  ⚠ Описание пустое или неверное: '{final_desc[:50]}', заполняем заново...")
                            desc_field.click()
                            time.sleep(0.5)
                            self.driver.execute_script("arguments[0].innerText = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].textContent = arguments[1];", desc_field, description)
                            self.driver.execute_script("""
                                var event = new Event('input', { bubbles: true });
                                arguments[0].dispatchEvent(event);
                            """, desc_field)
                            time.sleep(0.5)
                        else:
                            print(f"  ✓ Описание заполнено: '{final_desc[:50]}'")
                    else:
                        print("  ⚠ Поле описания не найдено")
                except Exception as e:
                    print(f"  ⚠ Не удалось проверить описание: {e}")
                
                # Проверяем ссылку
                try:
                    link_field = self.driver.find_element(By.ID, 'WebsiteField')
                    final_link = link_field.get_attribute('value') or ''
                    if not final_link or final_link.strip() != link.strip():
                        print(f"  ⚠ Ссылка пустая или неверная: '{final_link}', заполняем заново...")
                        link_field.click()
                        time.sleep(0.3)
                        link_field.clear()
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].value = '';", link_field)
                        time.sleep(0.2)
                        self.driver.execute_script("arguments[0].value = arguments[1];", link_field, link)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", link_field)
                        time.sleep(0.5)
                    else:
                        print(f"  ✓ Ссылка заполнена: '{final_link}'")
                except:
                    print("  ⚠ Не удалось проверить ссылку")
                
                print("  Ожидание 2 секунды для сохранения всех полей...")
                time.sleep(2)
            except Exception as e:
                print(f"  ⚠ Ошибка при финальной проверке: {e}")
            
            # Финальная проверка и заполнение полей непосредственно перед публикацией
            print("\nФинальная проверка полей непосредственно перед публикацией...")
            time.sleep(2)
            
            # Проверяем и заполняем название
            try:
                title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                final_title = title_field.get_attribute('value') or ''
                if not final_title or final_title.strip() != title.strip():
                    print(f"  ⚠ Название пустое или неверное: '{final_title}', заполняем...")
                    title_field.click()
                    time.sleep(0.3)
                    title_field.clear()
                    time.sleep(0.3)
                    title_field.send_keys(title)
                    time.sleep(0.5)
                    # Также через JS
                    self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                    time.sleep(0.5)
                    final_title = title_field.get_attribute('value') or ''
                    print(f"  ✓ Название заполнено: '{final_title}'")
                else:
                    print(f"  ✓ Название уже заполнено: '{final_title}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки названия: {e}")
            
            # Проверяем и заполняем описание
            try:
                all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                if all_ce:
                    desc_field = all_ce[0]
                    final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                    if not final_desc or final_desc.strip() != description.strip():
                        print(f"  ⚠ Описание пустое или неверное: '{final_desc[:50]}', заполняем...")
                        desc_field.click()
                        time.sleep(0.5)
                        # Очищаем
                        self.driver.execute_script("arguments[0].innerText = '';", desc_field)
                        self.driver.execute_script("arguments[0].textContent = '';", desc_field)
                        time.sleep(0.3)
                        # Заполняем через более агрессивный метод
                        # Сначала фокусируемся на поле
                        self.driver.execute_script("arguments[0].focus();", desc_field)
                        time.sleep(0.3)
                        
                        # Очищаем содержимое полностью
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            elem.innerHTML = '';
                            elem.innerText = '';
                            elem.textContent = '';
                            // Удаляем все дочерние элементы
                            while (elem.firstChild) {
                                elem.removeChild(elem.firstChild);
                            }
                        """, desc_field)
                        time.sleep(0.3)
                        
                        # Заполняем через send_keys (симулируем реальный ввод)
                        desc_field.send_keys(description)
                        time.sleep(0.5)
                        
                        # Также устанавливаем через innerText и textContent
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            var text = arguments[1];
                            elem.innerText = text;
                            elem.textContent = text;
                            // Устанавливаем также через innerHTML для надежности
                            elem.innerHTML = text;
                        """, desc_field, description)
                        time.sleep(0.5)
                        
                        # Триггерим все возможные события в правильном порядке
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            // Сначала keydown
                            var keydownEvent = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'a' });
                            elem.dispatchEvent(keydownEvent);
                            // Потом input
                            var inputEvent = new InputEvent('input', { bubbles: true, cancelable: true, data: arguments[1] });
                            elem.dispatchEvent(inputEvent);
                            // Потом keyup
                            var keyupEvent = new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: 'a' });
                            elem.dispatchEvent(keyupEvent);
                            // Потом change
                            var changeEvent = new Event('change', { bubbles: true, cancelable: true });
                            elem.dispatchEvent(changeEvent);
                            // Потом blur (потеря фокуса)
                            var blurEvent = new FocusEvent('blur', { bubbles: true, cancelable: true });
                            elem.dispatchEvent(blurEvent);
                            // И снова focus
                            elem.focus();
                        """, desc_field, description)
                        time.sleep(1)
                        final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        print(f"  ✓ Описание заполнено: '{final_desc[:50]}'")
                    else:
                        print(f"  ✓ Описание уже заполнено: '{final_desc[:50]}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки описания: {e}")
            
            # Проверяем и заполняем ссылку
            try:
                link_field = self.driver.find_element(By.ID, 'WebsiteField')
                final_link = link_field.get_attribute('value') or ''
                if not final_link or final_link.strip() != link.strip():
                    print(f"  ⚠ Ссылка пустая или неверная: '{final_link}', заполняем...")
                    link_field.click()
                    time.sleep(0.3)
                    
                    # Очищаем поле через выделение и удаление (как пользователь)
                    from selenium.webdriver.common.keys import Keys
                    link_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                    time.sleep(0.2)
                    link_field.send_keys(Keys.DELETE)  # Удаляем
                    time.sleep(0.3)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                    link_field.send_keys(link)
                    time.sleep(1.5)  # Даем время на обработку
                    final_link = link_field.get_attribute('value') or ''
                    print(f"  ✓ Ссылка заполнена: '{final_link}'")
                else:
                    print(f"  ✓ Ссылка уже заполнена: '{final_link}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки ссылки: {e}")
            
            print("  Ожидание 3 секунды для финального сохранения...")
            time.sleep(3)
            
            # ЕЩЕ РАЗ проверяем и заполняем поля непосредственно перед публикацией
            print("\nПоследняя проверка и заполнение полей перед публикацией...")
            try:
                # Название
                try:
                    title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                    current_title = title_field.get_attribute('value') or ''
                    if not current_title or current_title.strip() != title.strip():
                        print(f"  ⚠ Название пустое перед публикацией, заполняем...")
                        title_field.click()
                        time.sleep(0.3)
                        from selenium.webdriver.common.keys import Keys
                        title_field.send_keys(Keys.COMMAND + 'a')
                        time.sleep(0.2)
                        title_field.send_keys(Keys.DELETE)
                        time.sleep(0.3)
                        title_field.send_keys(title)
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].blur();", title_field)
                        time.sleep(0.5)
                except:
                    pass
                
                # Описание
                try:
                    all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                    if all_ce:
                        desc_field = all_ce[0]
                        current_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        if not current_desc or current_desc.strip() != description.strip():
                            print(f"  ⚠ Описание пустое перед публикацией, заполняем...")
                            desc_field.click()
                            time.sleep(0.3)
                            from selenium.webdriver.common.keys import Keys
                            desc_field.send_keys(Keys.COMMAND + 'a')
                            time.sleep(0.2)
                            desc_field.send_keys(Keys.DELETE)
                            time.sleep(0.3)
                            desc_field.send_keys(description)
                            time.sleep(1.5)
                            self.driver.execute_script("arguments[0].blur();", desc_field)
                            time.sleep(0.5)
                except:
                    pass
                
                # Ссылка
                try:
                    link_field = self.driver.find_element(By.ID, 'WebsiteField')
                    current_link = link_field.get_attribute('value') or ''
                    if not current_link or current_link.strip() != link.strip():
                        print(f"  ⚠ Ссылка пустая перед публикацией, заполняем...")
                        link_field.click()
                        time.sleep(0.3)
                        from selenium.webdriver.common.keys import Keys
                        link_field.send_keys(Keys.COMMAND + 'a')
                        time.sleep(0.2)
                        link_field.send_keys(Keys.DELETE)
                        time.sleep(0.3)
                        link_field.send_keys(link)
                        time.sleep(1.5)
                        self.driver.execute_script("arguments[0].blur();", link_field)
                        time.sleep(0.5)
                except:
                    pass
                
                # Финальная задержка для сохранения всех изменений
                print("  Ожидание 2 секунды для финального сохранения всех полей...")
                time.sleep(2)
            except Exception as e:
                print(f"  ⚠ Ошибка при финальной проверке: {e}")
            
            # Шаг 6: Публикуем пин
            print("\n6. Публикация пина...")
            try:
                # ВАЖНО: Снимаем фокус со всех полей ввода перед публикацией
                print("  Снятие фокуса с полей ввода...")
                try:
                    # Снимаем фокус с поля ссылки (последнее заполненное поле)
                    link_field = self.driver.find_element(By.ID, 'WebsiteField')
                    self.driver.execute_script("arguments[0].blur();", link_field)
                    time.sleep(0.3)
                except:
                    pass
                try:
                    # Снимаем фокус с поля описания
                    all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                    if all_ce:
                        self.driver.execute_script("arguments[0].blur();", all_ce[0])
                        time.sleep(0.3)
                except:
                    pass
                try:
                    # Снимаем фокус с поля названия
                    title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                    self.driver.execute_script("arguments[0].blur();", title_field)
                    time.sleep(0.3)
                except:
                    pass
                # Кликаем вне всех полей для полного снятия фокуса
                self.driver.execute_script("document.body.click();")
                time.sleep(0.5)
                
                # Прокручиваем вверх, чтобы увидеть кнопку
                print("  Прокрутка вверх для поиска кнопки публикации...")
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.5)
                # Также пробуем прокрутить к началу страницы через body
                self.driver.execute_script("document.body.scrollTop = 0; document.documentElement.scrollTop = 0;")
                time.sleep(0.5)
                
                # Ищем кнопку "Опубликовать" - приоритет по тексту, так как она красная и видна
                publish_button = None
                
                # Способ 1: Поиск по тексту "Опубликовать" (самый надежный)
                try:
                    publish_button = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Опубликовать') or contains(text(), 'Publish')]"))
                    )
                    print("  ✓ Кнопка найдена по тексту")
                except:
                    pass
                
                # Способ 2: Поиск по селекторам
                if not publish_button:
                    publish_selectors = [
                        'button[type="submit"]',
                        'button[data-test-id*="publish" i]',
                        'button[aria-label*="опубликовать" i]',
                        'button[aria-label*="publish" i]',
                        'button[class*="publish" i]',
                        'button[class*="submit" i]'
                    ]
                    
                    for selector in publish_selectors:
                        try:
                            publish_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if publish_button:
                                btn_text = publish_button.text.strip()
                                if 'опубликовать' in btn_text.lower() or 'publish' in btn_text.lower() or not btn_text:
                                    if publish_button.is_displayed():
                                        print(f"  ✓ Кнопка найдена по селектору: {selector}")
                                        break
                        except:
                            continue
                
                # Способ 3: Поиск всех кнопок и проверка текста
                if not publish_button:
                    try:
                        all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                        for btn in all_buttons:
                            try:
                                btn_text = btn.text.strip()
                                if btn_text and ('опубликовать' in btn_text.lower() or 'publish' in btn_text.lower()):
                                    if btn.is_displayed():
                                        publish_button = btn
                                        print(f"  ✓ Кнопка найдена по тексту из всех кнопок: '{btn_text}'")
                                        break
                            except:
                                continue
                    except:
                        pass
                
                if publish_button:
                    # Прокручиваем к кнопке
                    print("  Прокрутка к кнопке публикации...")
                    # Сначала прокручиваем в самый верх
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    self.driver.execute_script("document.body.scrollTop = 0; document.documentElement.scrollTop = 0;")
                    time.sleep(1)
                    # Теперь прокручиваем к кнопке
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", publish_button)
                    time.sleep(1.5)
                    # Также пробуем прокрутить через window.scrollTo с координатами кнопки
                    try:
                        location = publish_button.location_once_scrolled_into_view
                        self.driver.execute_script(f"window.scrollTo(0, {location['y'] - 200});")
                        time.sleep(1)
                    except:
                        pass
                    
                    # Проверяем, что кнопка видима и кликабельна
                    if not publish_button.is_displayed():
                        print("⚠ Кнопка публикации не видна, пробуем разные способы прокрутки...")
                        # Прокручиваем вверх
                        self.driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(1)
                        self.driver.execute_script("document.body.scrollTop = 0; document.documentElement.scrollTop = 0;")
                        time.sleep(1)
                        # Прокручиваем к кнопке снова
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'start', behavior: 'auto'});", publish_button)
                        time.sleep(1.5)
                    
                    # Проверяем, что кнопка не disabled
                    is_disabled = publish_button.get_attribute('disabled') or publish_button.get_attribute('aria-disabled') == 'true'
                    if is_disabled:
                        print("⚠ Кнопка публикации отключена, проверяем поля...")
                        # Проверяем поля еще раз
                        try:
                            title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                            title_val = title_field.get_attribute('value') or ''
                            print(f"  Название: '{title_val}'")
                        except:
                            pass
                        try:
                            link_field = self.driver.find_element(By.ID, 'WebsiteField')
                            link_val = link_field.get_attribute('value') or ''
                            print(f"  Ссылка: '{link_val}'")
                        except:
                            pass
                        try:
                            all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                            if all_ce:
                                desc_val = all_ce[0].text or all_ce[0].get_attribute('innerText') or ''
                                print(f"  Описание: '{desc_val[:50]}'")
                        except:
                            pass
                        print("  Пробуем нажать кнопку несмотря на disabled...")
                    
                    # Сохраняем текущий URL перед кликом
                    url_before = self.driver.current_url
                    print(f"URL перед кликом: {url_before}")
                    
                    # Проверяем, что кнопка видима и кликабельна перед попыткой клика
                    print("  Проверка состояния кнопки перед кликом...")
                    try:
                        is_visible = publish_button.is_displayed()
                        is_enabled = publish_button.is_enabled()
                        btn_text = publish_button.text.strip()
                        print(f"    Видима: {is_visible}, Включена: {is_enabled}, Текст: '{btn_text}'")
                    except Exception as check_e:
                        print(f"    Ошибка проверки: {check_e}")
                    
                    # Пробуем кликнуть через разные методы
                    clicked = False
                    click_methods = []
                    
                    # Метод 1: ActionChains с move_to_element (самый надежный)
                    try:
                        print("  Попытка клика методом 1: ActionChains move_to_element + click...")
                        from selenium.webdriver.common.action_chains import ActionChains
                        # Убеждаемся, что кнопка в viewport
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'nearest', behavior: 'auto'});", publish_button)
                        time.sleep(0.3)
                        # Используем ActionChains для надежного клика
                        actions = ActionChains(self.driver)
                        actions.move_to_element(publish_button).pause(0.2).click().perform()
                        clicked = True
                        click_methods.append("ActionChains")
                        print("  ✓ Кнопка публикации нажата (ActionChains)")
                    except Exception as e:
                        print(f"  ⚠ ActionChains не сработал: {e}")
                    
                    # Метод 2: JavaScript click
                    if not clicked:
                        try:
                            print("  Попытка клика методом 2: JavaScript click()...")
                            self.driver.execute_script("arguments[0].click();", publish_button)
                            clicked = True
                            click_methods.append("JS клик")
                            print("  ✓ Кнопка публикации нажата (JS клик)")
                        except Exception as e2:
                            print(f"  ⚠ JS клик не сработал: {e2}")
                    
                    # Метод 3: ActionChains
                    if not clicked:
                        try:
                            print("  Попытка клика методом 3: ActionChains...")
                            from selenium.webdriver.common.action_chains import ActionChains
                            actions = ActionChains(self.driver)
                            actions.move_to_element(publish_button).pause(0.5).click().perform()
                            clicked = True
                            click_methods.append("ActionChains")
                            print("  ✓ Кнопка публикации нажата (ActionChains)")
                        except Exception as e3:
                            print(f"  ⚠ ActionChains не сработал: {e3}")
                    
                    # Метод 4: JavaScript с dispatchEvent
                    if not clicked:
                        try:
                            print("  Попытка клика методом 4: JavaScript dispatchEvent...")
                            self.driver.execute_script("""
                                var btn = arguments[0];
                                var event = new MouseEvent('click', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true
                                });
                                btn.dispatchEvent(event);
                            """, publish_button)
                            clicked = True
                            click_methods.append("JS dispatchEvent")
                            print("  ✓ Кнопка публикации нажата (JS dispatchEvent)")
                        except Exception as e4:
                            print(f"  ⚠ JS dispatchEvent не сработал: {e4}")
                    
                    # Метод 5: JavaScript с mousedown/mouseup
                    if not clicked:
                        try:
                            print("  Попытка клика методом 5: JavaScript mousedown/mouseup...")
                            self.driver.execute_script("""
                                var btn = arguments[0];
                                var mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
                                var mouseup = new MouseEvent('mouseup', { bubbles: true, cancelable: true });
                                var click = new MouseEvent('click', { bubbles: true, cancelable: true });
                                btn.dispatchEvent(mousedown);
                                btn.dispatchEvent(mouseup);
                                btn.dispatchEvent(click);
                            """, publish_button)
                            clicked = True
                            click_methods.append("JS mousedown/mouseup")
                            print("  ✓ Кнопка публикации нажата (JS mousedown/mouseup)")
                        except Exception as e5:
                            print(f"  ⚠ JS mousedown/mouseup не сработал: {e5}")
                    
                    if not clicked:
                        print("  ⚠ ВСЕ методы клика не сработали!")
                        print("  Пробуем найти кнопку заново и кликнуть...")
                        # Пробуем найти кнопку заново
                        try:
                            publish_button_retry = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                            if publish_button_retry:
                                self.driver.execute_script("arguments[0].click();", publish_button_retry)
                                clicked = True
                                print("  ✓ Кнопка найдена заново и нажата")
                        except:
                            pass
                    
                    if not clicked:
                        print("  ⚠ Не удалось нажать кнопку публикации")
                        return False
                    
                    print(f"✓ Кнопка публикации нажата (методы: {', '.join(click_methods)})")
                    
                    # Ждем подтверждения публикации
                    print("Ожидание подтверждения публикации...")
                    time.sleep(0.5)
                    
                    # Сразу после клика проверяем, не появилась ли ошибка
                    print("  Проверка на наличие ошибок после клика...")
                    error_found = False
                    try:
                        # Проверяем наличие модальных окон с ошибками
                        modal_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="dialog"] [class*="error"], [role="dialog"] [role="alert"], [role="dialog"] [class*="Error"]')
                        if modal_errors:
                            for err in modal_errors:
                                error_text = err.text.strip()
                                if error_text:
                                    print(f"  ⚠ Обнаружена ошибка в модальном окне: {error_text}")
                                    error_found = True
                        
                        # Проверяем наличие toast-уведомлений с ошибками (но исключаем информационные сообщения)
                        toast_errors = self.driver.find_elements(By.CSS_SELECTOR, '[class*="toast"] [class*="error"], [class*="notification"] [class*="error"], [role="alert"]')
                        if toast_errors:
                            for err in toast_errors:
                                error_text = err.text.strip()
                                if error_text and len(error_text) > 0:
                                    # Исключаем информационные сообщения и сообщения об успехе (не ошибки)
                                    info_keywords = ['проверяем', 'проверяет', 'checking', 'проверка', 'одну минуту', 'one moment', 
                                                    'опубликовано', 'published', 'успешно', 'success', 'сохранено', 'saved']
                                    is_info = any(keyword in error_text.lower() for keyword in info_keywords)
                                    if not is_info:
                                        # Проверяем, что это действительно ошибка (содержит слова об ошибке)
                                        error_keywords = ['ошибка', 'error', 'не удалось', 'failed', 'неверно', 'invalid', 'неправильно', 
                                                         'недоступно', 'unavailable', 'отклонено', 'rejected']
                                        is_error = any(keyword in error_text.lower() for keyword in error_keywords)
                                        if is_error:
                                            print(f"  ⚠ Обнаружена ошибка в уведомлении: {error_text}")
                                            error_found = True
                                        else:
                                            print(f"  ℹ Информационное сообщение: {error_text}")
                                    else:
                                        # Это информационное сообщение или сообщение об успехе
                                        if 'опубликовано' in error_text.lower() or 'published' in error_text.lower():
                                            print(f"  ✓ Сообщение об успешной публикации: {error_text}")
                                        else:
                                            print(f"  ℹ Информационное сообщение: {error_text}")
                        
                        # Проверяем наличие ошибок валидации в полях
                        field_errors = self.driver.find_elements(By.CSS_SELECTOR, '[class*="error-message"], [class*="validation-error"], [data-test-id*="error"]')
                        if field_errors:
                            for err in field_errors:
                                error_text = err.text.strip()
                                if error_text and len(error_text) > 0:
                                    print(f"  ⚠ Обнаружена ошибка валидации: {error_text}")
                                    error_found = True
                    except Exception as check_err:
                        print(f"  ⚠ Ошибка при проверке ошибок: {check_err}")
                    
                    if error_found:
                        print("  ⚠ Обнаружены ошибки, публикация не удалась")
                        return False
                    
                    time.sleep(1.5)
                    
                    # Проверяем, что мы перешли на страницу пина (URL изменился)
                    current_url = self.driver.current_url
                    print(f"URL после клика (через 2 сек): {current_url}")
                    
                    if '/pin/' in current_url and current_url != url_before:
                        print("✓ Пин успешно опубликован!")
                        print(f"Текущий URL: {current_url}")
                        return True
                    elif '/pin-creation-tool/' not in current_url and current_url != url_before:
                        # URL изменился, но не на /pin/
                        print("✓ Пин успешно опубликован! (URL изменился)")
                        print(f"Текущий URL: {current_url}")
                        return True
                    else:
                        # Возможно, появилось модальное окно с подтверждением или идет обработка
                        print("⚠ URL не изменился сразу, ждем обработки...")
                        for i in range(15):  # Ждем до 15 секунд
                            time.sleep(1)
                            current_url = self.driver.current_url
                            if i % 3 == 0:  # Выводим каждые 3 секунды
                                print(f"  Проверка {i+1}/15: {current_url}")
                            if '/pin/' in current_url and current_url != url_before:
                                print("✓ Пин успешно опубликован!")
                                print(f"Текущий URL: {current_url}")
                                return True
                            if '/pin-creation-tool/' not in current_url and current_url != url_before:
                                print("✓ Пин успешно опубликован! (URL изменился)")
                                print(f"Текущий URL: {current_url}")
                                return True
                            # Проверяем наличие ошибок на странице
                            if i % 3 == 0:  # Проверяем ошибки каждые 3 секунды
                                try:
                                    # Ищем различные типы ошибок
                                    error_selectors = [
                                        '[role="alert"]',
                                        '.error',
                                        '[class*="error"]',
                                        '[class*="Error"]',
                                        '[data-test-id*="error"]',
                                        '[aria-live="polite"]',
                                        '[aria-live="assertive"]'
                                    ]
                                    for selector in error_selectors:
                                        error_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                                        if error_elements:
                                            for err in error_elements:
                                                error_text = err.text.strip()
                                                if error_text and len(error_text) > 0:
                                                    print(f"⚠ Обнаружена ошибка ({selector}): {error_text}")
                                    
                                    # Проверяем, не появилось ли модальное окно с ошибкой
                                    try:
                                        modal_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="dialog"] [class*="error"], [role="dialog"] [role="alert"]')
                                        if modal_errors:
                                            for err in modal_errors:
                                                error_text = err.text.strip()
                                                if error_text:
                                                    print(f"⚠ Обнаружена ошибка в модальном окне: {error_text}")
                                    except:
                                        pass
                                except:
                                    pass
                                
                                # Проверяем, не заблокирована ли кнопка публикации
                                try:
                                    publish_button_after = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], button[aria-label*="publish" i], button[aria-label*="опубликовать" i]')
                                    is_disabled_after = publish_button_after.get_attribute('disabled') or publish_button_after.get_attribute('aria-disabled') == 'true'
                                    if is_disabled_after:
                                        print(f"⚠ Кнопка публикации все еще отключена на проверке {i+1}")
                                except:
                                    pass
                        
                        # Если после 15 секунд URL не изменился
                        print("⚠ Пин не опубликован или публикация еще обрабатывается")
                        print(f"Финальный URL: {current_url}")
                        print(f"Ожидался URL с '/pin/' в пути или изменение URL")
                        
                        # Финальная проверка - может быть пин опубликован, но страница не обновилась
                        print("\nФинальная диагностика:")
                        try:
                            # Проверяем все ошибки на странице
                            all_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="alert"], .error, [class*="error"], [class*="Error"], [data-test-id*="error"]')
                            if all_errors:
                                print("  Найдены элементы с ошибками:")
                                for err in all_errors[:5]:  # Первые 5
                                    try:
                                        err_text = err.text.strip()
                                        if err_text:
                                            print(f"    - {err_text[:100]}")
                                    except:
                                        pass
                            
                            # Проверяем состояние кнопки публикации
                            try:
                                publish_btn_final = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], button[aria-label*="publish" i], button[aria-label*="опубликовать" i]')
                                btn_text = publish_btn_final.text.strip()
                                is_disabled_final = publish_btn_final.get_attribute('disabled') or publish_btn_final.get_attribute('aria-disabled') == 'true'
                                print(f"  Кнопка публикации: текст='{btn_text}', disabled={is_disabled_final}")
                            except:
                                print("  Кнопка публикации не найдена")
                            
                            # Проверяем поля еще раз
                            print("  Состояние полей:")
                            try:
                                title_field = self.driver.find_element(By.ID, 'storyboard-selector-title')
                                title_val = title_field.get_attribute('value') or ''
                                print(f"    Название: '{title_val}'")
                            except:
                                print("    Название: не найдено")
                            try:
                                link_field = self.driver.find_element(By.ID, 'WebsiteField')
                                link_val = link_field.get_attribute('value') or ''
                                print(f"    Ссылка: '{link_val}'")
                            except:
                                print("    Ссылка: не найдено")
                            try:
                                all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                                if all_ce:
                                    desc_val = all_ce[0].text or all_ce[0].get_attribute('innerText') or ''
                                    print(f"    Описание: '{desc_val[:50]}'")
                                else:
                                    print("    Описание: не найдено")
                            except:
                                print("    Описание: ошибка проверки")
                        except Exception as diag_e:
                            print(f"  Ошибка диагностики: {diag_e}")
                        
                        print("\nПроверьте браузер вручную - возможно пин опубликован, но страница не обновилась")
                        print("Или есть ошибка валидации, которая блокирует публикацию")
                        return False
                else:
                    print("⚠ Кнопка публикации не найдена")
                    print("Попробуйте опубликовать пин вручную в открывшемся браузере")
                    print("Все поля должны быть заполнены:")
                    print(f"  - Название: {title}")
                    print(f"  - Описание: {description}")
                    print(f"  - Ссылка: {link}")
                    print(f"  - Доска: {board_name}")
                    return False
            except Exception as e:
                print(f"⚠ Ошибка при публикации: {e}")
                import traceback
                traceback.print_exc()
                return False
            
        except Exception as e:
            print(f"⚠ Ошибка при создании пина: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def close(self):
        """Закрывает браузер если он был создан этим классом"""
        if self.own_driver and self.driver:
            self.driver.quit()
            print("✓ Браузер закрыт")


if __name__ == "__main__":
    """
    Тестовый модуль для публикации пина.
    """
    import sys
    
    print("=" * 80)
    print("ТЕСТОВЫЙ МОДУЛЬ ПУБЛИКАЦИИ ПИНА")
    print("=" * 80)
    
    # Ищем изображение: сначала проверяем chel.jpg, потом moncler.jpeg, потом папки результатов
    image_path = None
    
    # Проверяем chel.jpg в корне (приоритет)
    if os.path.exists('chel.jpg'):
        image_path = 'chel.jpg'
        print(f"\n✓ Найдено изображение в корне: {image_path}")
    elif os.path.exists('moncler.jpeg'):
        image_path = 'moncler.jpeg'
        print(f"\n✓ Найдено изображение в корне: {image_path}")
    else:
        # Ищем в папках результатов парсинга
        try:
            image_dirs = [d for d in os.listdir('.') if d.startswith('pinterest_images_') and os.path.isdir(d)]
            
            if image_dirs:
                # Берем последнюю папку
                latest_dir = sorted(image_dirs)[-1]
                image_files = [f for f in os.listdir(latest_dir) if f.endswith(('.jpg', '.jpeg', '.png', '.gif'))]
                
                if image_files:
                    image_path = os.path.join(latest_dir, image_files[0])
                    print(f"\n✓ Найдено изображение в папке результатов: {image_path}")
                else:
                    print("\n⚠ В папках результатов не найдено изображений")
            else:
                print("\n⚠ Папки с результатами парсинга не найдены")
        except Exception as e:
            print(f"\n⚠ Ошибка при поиске изображений: {e}")
    
    # Если изображение не найдено, запрашиваем у пользователя
    if not image_path:
        print("\nВведите путь к изображению для публикации:")
        user_path = input("Путь к изображению: ").strip()
        if user_path and os.path.exists(user_path):
            image_path = user_path
        else:
            print("\n⚠ Изображение не найдено. Завершение работы.")
            sys.exit(1)
    
    # Инициализируем парсер для получения досок
    print("\nИнициализация парсера...")
    parser = PinterestSeleniumParser(
        headless=False,
        download_images=False,
        auto_login=True
    )
    
    try:
        # Получаем список досок
        print("\nПолучение списка досок...")
        account_info = parser.get_account_info()
        if account_info:
            username = account_info.get('username')
            if username:
                boards = parser.parse_user_boards(username=username)
                
                if boards:
                    print(f"\n✓ Найдено досок: {len(boards)}")
                    print("\nСписок досок:")
                    for i, board in enumerate(boards, 1):
                        print(f"  {i}. {board.get('board_name', 'Без названия')}")
                    
                    # Берем первую доску для теста
                    test_board = boards[0].get('board_name')
                    print(f"\nИспользуем доску для теста: {test_board}")
                else:
                    print("\n⚠ Доски не найдены, используем 'test'")
                    test_board = "test"
            else:
                print("\n⚠ Не удалось определить имя пользователя")
                test_board = "test"
        else:
            print("\n⚠ Не удалось получить информацию об аккаунте")
            test_board = "test"
        
        # Создаем публикатор
        print("\nИнициализация публикатора...")
        publisher = PinterestPublisher(parser=parser)
        
        # Публикуем тестовый пин
        print("\n" + "=" * 80)
        success = publisher.create_pin(
            image_path=image_path,
            title="test",
            description="test 2",
            link="https://huggingface.co/",
            board_name=test_board
        )
        
        if success:
            print("\n" + "=" * 80)
            print("✓ ТЕСТ ПУБЛИКАЦИИ ЗАВЕРШЕН УСПЕШНО")
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("⚠ ТЕСТ ПУБЛИКАЦИИ ЗАВЕРШЕН С ОШИБКАМИ")
            print("=" * 80)
        
        # Не закрываем браузер, оставляем для проверки
        print("\nБраузер остается открытым для проверки результата")
        try:
            input("Нажмите Enter для закрытия браузера...")
        except (EOFError, KeyboardInterrupt):
            print("\nЗакрытие браузера...")
        
    finally:
        parser.close()
