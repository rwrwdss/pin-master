"""
Конфигурация селекторов для парсинга Pinterest.
Здесь хранятся CSS селекторы и XPath для извлечения данных с Pinterest.
"""


class PinterestSelectors:
    """Пространство имен для селекторов Pinterest"""
    
    # Селекторы для пинов в ленте/поиске
    PIN_CARD = ""  # Будет заполнено после анализа страницы
    PIN_LINK = ""  # Ссылка на пин
    PIN_IMAGE = ""  # Изображение пина
    PIN_TITLE = ""  # Название пина
    PIN_DESCRIPTION = ""  # Описание пина
    PIN_AUTHOR = ""  # Автор пина
    
    # Селекторы для детальной страницы пина
    PIN_DETAIL_TITLE = ""
    PIN_DETAIL_DESCRIPTION = ""
    PIN_DETAIL_AUTHOR = ""
    PIN_DETAIL_IMAGE = ""
    
    # Селекторы для прямой ссылки на изображение
    PIN_IMAGE_DIRECT = ""  # Прямая ссылка на скачивание изображения


class PinterestURLs:
    """Пространство имен для URL шаблонов Pinterest"""
    
    BASE_URL = "https://www.pinterest.com"
    SEARCH_URL = "https://www.pinterest.com/search/pins/?q={query}"
    PIN_URL = "https://www.pinterest.com/pin/{pin_id}/"
    USER_ME = "https://ru.pinterest.com/me"
    USER_PROFILE = "https://ru.pinterest.com/{username}/"
    USER_PINS = "https://ru.pinterest.com/{username}/_pins/"
    USER_BOARDS = "https://ru.pinterest.com/{username}/_boards/"
    BOARD_PINS = "https://ru.pinterest.com/{username}/{board_name}/"


class PinterestConfig:
    """Конфигурация для парсера"""
    
    # Задержки для избежания блокировок
    REQUEST_DELAY = 1.0  # секунды между запросами
    PAGE_LOAD_DELAY = 2.0  # секунды для загрузки страницы
    
    # User-Agent для имитации браузера
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Количество пинов для парсинга
    MAX_PINS = 50
    
    # Путь к файлу с cookies по умолчанию
    DEFAULT_COOKIES_FILE = "pinterest_cookies.json"
