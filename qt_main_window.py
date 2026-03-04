"""
Главное окно Qt-приложения для парсера Pinterest.
Информация об аккаунте отображается в главном меню/окне.
"""

# Настройка логирования
import logging
import sys
import os
from datetime import datetime

# Создаем логгер
logger = logging.getLogger('PinMaster')
logger.setLevel(logging.DEBUG)

# Создаем обработчик для вывода в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Создаем обработчик для записи в файл
log_file = os.path.join(os.path.dirname(__file__), 'pinmaster.log')
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

# Формат логов
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(console_handler)
logger.addHandler(file_handler)

logger.info("=" * 80)
logger.info("ЗАПУСК ПРИЛОЖЕНИЯ PINMASTER")
logger.info("=" * 80)

# Патч для работы webdriver-manager в frozen режиме (должен быть первым)
try:
    logger.debug("Попытка импорта webdriver_frozen_patch...")
    import webdriver_frozen_patch
    logger.debug("webdriver_frozen_patch успешно импортирован")
except ImportError as e:
    logger.warning(f"webdriver_frozen_patch не найден: {e}")  # Не критично, если патч не найден

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox,
    QStatusBar, QMenuBar, QMenu, QMessageBox, QSplitter,
    QComboBox, QFileDialog, QProgressBar, QListWidget, QListWidgetItem,
    QDialog, QSpinBox, QSystemTrayIcon, QCheckBox, QScrollArea, QGridLayout,
    QStackedWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QFile, QTextStream, QTimer, QSize
import requests
import csv
import re
from PyQt6.QtGui import QFont, QIcon, QAction, QPixmap, QImage
from typing import Optional, Dict, List
import json
import webbrowser

from pinterest_selenium_parser import PinterestSeleniumParser
from cache_manager import CacheManager
from pinterest_publisher import PinterestPublisher
from path_utils import (
    get_config_path, get_cookies_path, get_images_dir,
    get_csv_dir, get_styles_path, get_app_name, get_parsing_history_path,
)
from toast_notification import ToastManager
from status_indicator import StatusIndicator


class AccountInfoWidget(QGroupBox):
    """Виджет для отображения информации об аккаунте"""
    
    def __init__(self, parent=None):
        super().__init__("Авторизованный аккаунт", parent)
        self.setup_ui()
        self.account_info = None
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Имя пользователя (крупно и заметно) - убрали дублирование статуса
        self.username_label = QLabel("Не авторизован")
        self.username_label.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.username_label.setStyleSheet("""
            QLabel {
                color: #1a1a1a;
                padding: 12px 0px;
            }
        """)
        layout.addWidget(self.username_label)
        
        # Display name если есть
        self.display_name_label = QLabel("")
        self.display_name_label.setFont(QFont("Arial", 14))
        self.display_name_label.setStyleSheet("color: #666666; padding: 4px 0px;")
        self.display_name_label.hide()
        layout.addWidget(self.display_name_label)
        
        # Разделитель
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #e0e0e0;")
        layout.addWidget(separator)
        
        # Дополнительная информация
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 12px;
                padding: 8px 0px;
            }
        """)
        layout.addWidget(self.info_label)
        
        # URL профиля
        self.profile_url_label = QLabel("")
        self.profile_url_label.setWordWrap(True)
        self.profile_url_label.setStyleSheet("""
            QLabel {
                color: #000000;
                font-size: 11px;
                padding: 4px 0px;
                text-decoration: underline;
            }
        """)
        self.profile_url_label.hide()
        layout.addWidget(self.profile_url_label)
        
        # Кнопка обновления
        self.refresh_btn = QPushButton("Обновить информацию")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        layout.addWidget(self.refresh_btn)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def update_account_info(self, account_info: Optional[Dict[str, str]]):
        """Обновляет отображаемую информацию об аккаунте"""
        self.account_info = account_info
        
        if account_info:
            username = account_info.get('username', 'Неизвестно')
            
            # Обновляем имя пользователя (убрали дублирование статуса)
            self.username_label.setText(f"@{username}")
            self.username_label.setStyleSheet("""
                QLabel {
                    color: #1a1a1a;
                    padding: 8px 0px;
                }
            """)
            
            # Display name
            display_name = account_info.get('display_name', '')
            if display_name:
                self.display_name_label.setText(display_name)
                self.display_name_label.show()
            else:
                self.display_name_label.hide()
            
            # Формируем дополнительную информацию
            info_parts = []
            if account_info.get('pins_count'):
                info_parts.append(f"Пинов: {account_info['pins_count']}")
            if account_info.get('boards_count'):
                info_parts.append(f"Досок: {account_info['boards_count']}")
            
            if info_parts:
                self.info_label.setText(" | ".join(info_parts))
                self.info_label.show()
            else:
                self.info_label.setText("Аккаунт авторизован")
                self.info_label.show()
            
            # URL профиля
            profile_url = account_info.get('profile_url', '')
            if profile_url:
                self.profile_url_label.setText(f"Профиль: {profile_url}")
                self.profile_url_label.show()
            else:
                self.profile_url_label.hide()
            
            self.refresh_btn.setEnabled(True)
        else:
            # Не авторизован
            self.username_label.setText("Не авторизован")
            self.username_label.setStyleSheet("""
                QLabel {
                    color: #666666;
                    padding: 8px 0px;
                }
            """)
            
            self.display_name_label.hide()
            self.info_label.setText("Войдите в аккаунт для отображения информации")
            self.profile_url_label.hide()
            self.refresh_btn.setEnabled(True)
    
    def on_refresh_clicked(self):
        """Обработчик нажатия кнопки обновления"""
        # Сигнал будет обработан в главном окне
        parent = self.parent()
        while parent:
            if hasattr(parent, 'refresh_account_info'):
                parent.refresh_account_info()
                return
            parent = parent.parent()


class PinCardWidget(QWidget):
    """Виджет карточки пина с превью изображения"""
    
    def __init__(self, pin_data: Dict[str, str], parent=None):
        try:
            super().__init__(parent)
            self.pin_data = pin_data or {}
            self.setup_ui()
        except Exception as e:
            logger.error(f"PinCardWidget.__init__: ошибка при создании карточки: {e}", exc_info=True)
            # Создаем минимальную карточку с ошибкой
            super().__init__(parent)
            self.pin_data = pin_data or {}
            layout = QVBoxLayout()
            error_label = QLabel(f"Ошибка загрузки: {str(e)[:50]}")
            layout.addWidget(error_label)
            self.setLayout(layout)
    
    def setup_ui(self):
        try:
            layout = QVBoxLayout()
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(3)
            
            # Изображение - фиксированный размер, не растягивается
            self.image_label = QLabel()
            self.image_label.setFixedSize(180, 180)  # Уменьшенный размер карточки
            self.image_label.setScaledContents(True)
            # Фиксированная политика размера
            size_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.image_label.setSizePolicy(size_policy)
            self.image_label.setStyleSheet("""
                QLabel {
                    background-color: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                }
            """)
            self.image_label.setText("Загрузка...")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.image_label)
            
            # Заголовок
            title = self.pin_data.get('title', 'Без названия') or 'Без названия'
            if len(title) > 50:
                title = title[:47] + "..."
            
            self.title_label = QLabel(title)
            self.title_label.setWordWrap(True)
            self.title_label.setStyleSheet("""
                QLabel {
                    color: #1a1a1a;
                    font-size: 10px;
                    font-weight: 500;
                    padding: 2px;
                }
            """)
            layout.addWidget(self.title_label)
            
            # Автор
            author = self.pin_data.get('author', 'Неизвестно') or 'Неизвестно'
            self.author_label = QLabel(f"Автор: {author}")
            self.author_label.setStyleSheet("""
                QLabel {
                    color: #666666;
                    font-size: 9px;
                    padding: 1px 2px;
                }
            """)
            layout.addWidget(self.author_label)
            
            # Кнопки в одну строку
            buttons_layout = QHBoxLayout()
            buttons_layout.setSpacing(4)
            buttons_layout.setContentsMargins(0, 0, 0, 0)
            
            # Кнопка открытия
            self.open_btn = QPushButton("Открыть")
            self.open_btn.setObjectName("compactButton")
            self.open_btn.setStyleSheet("""
                QPushButton {
                    background-color: #000000;
                    color: #ffffff;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #333333;
                }
            """)
            self.open_btn.clicked.connect(self.open_pin)
            buttons_layout.addWidget(self.open_btn)
            
            # Кнопка предпросмотра изображения
            self.preview_btn = QPushButton("Просмотр")
            self.preview_btn.setObjectName("compactButton")
            self.preview_btn.setStyleSheet("""
                QPushButton {
                    background-color: #666666;
                    color: #ffffff;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #888888;
                }
            """)
            self.preview_btn.clicked.connect(self.preview_image)
            buttons_layout.addWidget(self.preview_btn)
            
            layout.addLayout(buttons_layout)
            self.setLayout(layout)
            self.setStyleSheet("""
                QWidget {
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                }
            """)
            
            # Загружаем изображение асинхронно
            self.load_image()
        except Exception as e:
            logger.error(f"PinCardWidget.setup_ui: ошибка при настройке UI: {e}", exc_info=True)
            # Создаем минимальный layout с ошибкой
            if not hasattr(self, 'image_label'):
                layout = QVBoxLayout()
                error_label = QLabel(f"Ошибка: {str(e)[:50]}")
                layout.addWidget(error_label)
                self.setLayout(layout)
    
    def load_image(self):
        """Загружает изображение асинхронно"""
        try:
            if not hasattr(self, 'image_label'):
                return
                
            image_url = self.pin_data.get('image_url', '') or self.pin_data.get('image_path', '')
            if not image_url:
                self.image_label.setText("Нет изображения")
                return
            
            # Если это локальный путь
            if os.path.exists(image_url):
                try:
                    pixmap = QPixmap(image_url)
                    if not pixmap.isNull():
                        self.image_label.setPixmap(pixmap)
                    else:
                        self.image_label.setText("Ошибка загрузки")
                except Exception as e:
                    logger.error(f"PinCardWidget.load_image: ошибка загрузки локального изображения: {e}")
                    self.image_label.setText("Ошибка")
                return
            
            # Загружаем из URL в отдельном потоке
            def load_from_url():
                try:
                    response = requests.get(image_url, timeout=10, stream=True)
                    if response.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(response.content)
                        if not pixmap.isNull():
                            self.image_label.setPixmap(pixmap)
                        else:
                            self.image_label.setText("Ошибка формата")
                    else:
                        self.image_label.setText("Не загружено")
                except Exception as e:
                    logger.error(f"PinCardWidget.load_image: ошибка загрузки изображения из URL: {e}")
                    self.image_label.setText("Ошибка")
            
            # Запускаем в отдельном потоке через QTimer
            QTimer.singleShot(0, load_from_url)
        except Exception as e:
            logger.error(f"PinCardWidget.load_image: критическая ошибка: {e}", exc_info=True)
            if hasattr(self, 'image_label'):
                self.image_label.setText("Ошибка")
    
    def open_pin(self):
        """Открывает пин в браузере"""
        pin_link = self.pin_data.get('pin_link', '')
        if pin_link:
            webbrowser.open(pin_link)
    
    def preview_image(self):
        """Открывает изображение в полном размере"""
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
            from PyQt6.QtCore import Qt
            
            image_url = self.pin_data.get('image_url', '') or self.pin_data.get('image_path', '')
            if not image_url:
                return
            
            # Создаем диалог предпросмотра
            preview_dialog = QDialog(self)
            preview_dialog.setWindowTitle("Предпросмотр изображения")
            preview_dialog.setMinimumSize(800, 600)
            
            layout = QVBoxLayout()
            
            # Изображение
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setScaledContents(True)
            
            # Загружаем изображение
            if os.path.exists(image_url):
                pixmap = QPixmap(image_url)
            else:
                # Пытаемся загрузить из URL
                try:
                    response = requests.get(image_url, timeout=10)
                    if response.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(response.content)
                    else:
                        image_label.setText("Не удалось загрузить изображение")
                        layout.addWidget(image_label)
                        preview_dialog.setLayout(layout)
                        preview_dialog.exec()
                        return
                except:
                    image_label.setText("Ошибка загрузки изображения")
                    layout.addWidget(image_label)
                    preview_dialog.setLayout(layout)
                    preview_dialog.exec()
                    return
            
            if not pixmap.isNull():
                # Масштабируем изображение под размер окна
                scaled_pixmap = pixmap.scaled(800, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                image_label.setPixmap(scaled_pixmap)
            
            layout.addWidget(image_label)
            
            # Кнопка закрытия
            close_btn = QPushButton("Закрыть")
            close_btn.clicked.connect(preview_dialog.close)
            layout.addWidget(close_btn)
            
            preview_dialog.setLayout(layout)
            preview_dialog.exec()
        except Exception as e:
            logger.error(f"PinCardWidget.preview_image: ошибка: {e}", exc_info=True)


class PinGridWidget(QWidget):
    """Виджет сетки с превью изображений пинов"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # ScrollArea для прокрутки
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #ffffff;
            }
        """)
        
        # Контейнер для сетки
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(12)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        # Устанавливаем одинаковые размеры колонок для равномерного распределения
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setColumnStretch(2, 1)
        self.grid_container.setLayout(self.grid_layout)
        
        scroll_area.setWidget(self.grid_container)
        layout.addWidget(scroll_area)
        
        self.setLayout(layout)
    
    def display_pins(self, pins: List[Dict[str, str]]):
        """Отображает пины в сетке"""
        logger.debug(f"PinGridWidget.display_pins: начало отображения {len(pins)} пинов")
        try:
            # Очищаем предыдущие карточки
            logger.debug("PinGridWidget.display_pins: очистка предыдущих карточек...")
            while self.grid_layout.count():
                child = self.grid_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            
            # Добавляем карточки в сетку (3 колонки)
            columns = 3
            logger.debug(f"PinGridWidget.display_pins: создание карточек в сетке {columns} колонок...")
            for i, pin in enumerate(pins):
                try:
                    row = i // columns
                    col = i % columns
                    logger.debug(f"PinGridWidget.display_pins: создание карточки {i+1}/{len(pins)} (row={row}, col={col})...")
                    card = PinCardWidget(pin)
                    self.grid_layout.addWidget(card, row, col)
                    logger.debug(f"PinGridWidget.display_pins: карточка {i+1} создана и добавлена")
                except Exception as e:
                    logger.error(f"PinGridWidget.display_pins: ошибка при создании карточки {i+1}: {e}", exc_info=True)
                    # Продолжаем создание остальных карточек даже при ошибке
                    continue
            
            logger.debug(f"PinGridWidget.display_pins: отображение завершено, создано карточек: {self.grid_layout.count()}")
        except Exception as e:
            logger.critical(f"PinGridWidget.display_pins: критическая ошибка при отображении пинов: {e}", exc_info=True)


class AccountInfoThread(QThread):
    """Поток для получения информации об аккаунте и парсинга пинов/досок"""
    
    account_info_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, parser: PinterestSeleniumParser):
        super().__init__()
        self.parser = parser
        self.setTerminationEnabled(True)
    
    def run(self):
        logger.info("AccountInfoThread: запуск потока...")
        try:
            # Проверяем что парсер доступен
            logger.debug("AccountInfoThread: проверка парсера...")
            if not self.parser or not self.parser.driver:
                error_msg = "Парсер не инициализирован"
                logger.error(f"AccountInfoThread: {error_msg}")
                self.error_occurred.emit(error_msg)
                return
            
            logger.debug("AccountInfoThread: парсер доступен, получение информации об аккаунте...")
            # Получаем базовую информацию об аккаунте
            try:
                account_info = self.parser.get_account_info()
                logger.debug(f"AccountInfoThread: информация об аккаунте получена: {account_info}")
            except Exception as e:
                error_msg = f"Ошибка при получении информации об аккаунте: {str(e)}"
                logger.error(f"AccountInfoThread: {error_msg}", exc_info=True)
                self.error_occurred.emit(error_msg)
                return
                
            if not account_info:
                error_msg = "Не удалось получить информацию об аккаунте"
                logger.error(f"AccountInfoThread: {error_msg}")
                self.error_occurred.emit(error_msg)
                return
            
            username = account_info.get('username')
            if not username:
                error_msg = "Не удалось определить имя пользователя"
                logger.error(f"AccountInfoThread: {error_msg}")
                self.error_occurred.emit(error_msg)
                return
            
            logger.info(f"AccountInfoThread: парсинг досок для пользователя {username}...")
            # Парсим доски пользователя (с проверкой кэша)
            try:
                # Сначала проверяем кэш
                boards = CacheManager.load_boards(username)
                if boards is None:
                    # Кэша нет или он устарел - парсим заново
                    logger.debug(f"AccountInfoThread: кэш досок для {username} не найден или устарел, парсим...")
                    print(f"Кэш досок для {username} не найден или устарел, парсим...")
                    boards = self.parser.parse_user_boards(username=username)
                    if boards:
                        # Сохраняем в кэш
                        CacheManager.save_boards(username, boards)
                        logger.debug(f"AccountInfoThread: сохранено {len(boards)} досок в кэш")
                else:
                    logger.debug(f"AccountInfoThread: используем кэш досок для {username}")
                    print(f"Используем кэш досок для {username}")
                
                if boards:
                    account_info['boards_count'] = f"{len(boards)} досок"
                    account_info['boards'] = boards
                else:
                    account_info['boards_count'] = "0 досок"
                    account_info['boards'] = []
            except Exception as e:
                logger.error(f"AccountInfoThread: ошибка при парсинге досок: {e}", exc_info=True)
                print(f"Ошибка при парсинге досок: {e}")
                account_info['boards_count'] = "Ошибка"
                account_info['boards'] = []
            
            logger.info(f"AccountInfoThread: парсинг пинов для пользователя {username}...")
            # Парсим пины пользователя (ограничиваем до 10 для быстрой загрузки, с проверкой кэша)
            try:
                # Сначала проверяем кэш
                pins = CacheManager.load_pins(username)
                if pins is None:
                    # Кэша нет или он устарел - парсим заново
                    logger.debug(f"AccountInfoThread: кэш пинов для {username} не найден или устарел, парсим...")
                    print(f"Кэш пинов для {username} не найден или устарел, парсим...")
                    pins = self.parser.parse_user_pins(username=username, max_pins=10)
                    if pins:
                        # Сохраняем в кэш
                        CacheManager.save_pins(username, pins)
                        logger.debug(f"AccountInfoThread: сохранено {len(pins)} пинов в кэш")
                else:
                    logger.debug(f"AccountInfoThread: используем кэш пинов для {username}")
                    print(f"Используем кэш пинов для {username}")
                    # Ограничиваем до 10 для отображения
                    pins = pins[:10]
                
                if pins:
                    account_info['pins_count'] = f"{len(pins)} пинов (показано 10)"
                    account_info['pins'] = pins
                else:
                    account_info['pins_count'] = "0 пинов"
                    account_info['pins'] = []
            except Exception as e:
                logger.error(f"AccountInfoThread: ошибка при парсинге пинов: {e}", exc_info=True)
                print(f"Ошибка при парсинге пинов: {e}")
                account_info['pins_count'] = "Ошибка"
                account_info['pins'] = []
            
            logger.info("AccountInfoThread: отправка сигнала account_info_ready...")
            self.account_info_ready.emit(account_info)
            logger.info("AccountInfoThread: поток завершен успешно")
            
        except Exception as e:
            logger.critical(f"AccountInfoThread: критическая ошибка: {e}", exc_info=True)
            self.error_occurred.emit(str(e))


class ParserInitThread(QThread):
    """Поток для инициализации парсера и ожидания логина"""
    
    parser_ready = pyqtSignal(object)  # PinterestSeleniumParser
    login_completed = pyqtSignal()  # Сигнал о завершении логина
    error_occurred = pyqtSignal(str)  # Сигнал об ошибке
    
    def __init__(self, enable_login: bool, headless: bool, download_images: bool):
        super().__init__()
        self.enable_login = enable_login
        self.headless = headless
        self.download_images = download_images
        self.setTerminationEnabled(True)
    
    def run(self):
        """Инициализирует парсер и ждет завершения логина"""
        logger.info("=" * 80)
        logger.info("ParserInitThread: ИНИЦИАЛИЗАЦИЯ ПАРСЕРА В ПОТОКЕ")
        logger.info("=" * 80)
        logger.info(f"ParserInitThread: enable_login={self.enable_login}")
        logger.info(f"ParserInitThread: headless={self.headless}")
        logger.info(f"ParserInitThread: download_images={self.download_images}")
        logger.info("=" * 80)
        
        print("\n" + "=" * 80)
        print("ИНИЦИАЛИЗАЦИЯ ПАРСЕРА В ПОТОКЕ")
        print("=" * 80)
        print(f"enable_login: {self.enable_login}")
        print(f"headless: {self.headless}")
        print(f"download_images: {self.download_images}")
        print("=" * 80 + "\n")
        
        try:
            # Инициализируем парсер (это может занять время, особенно при логине)
            logger.info("ParserInitThread: создание PinterestSeleniumParser...")
            print("Создание PinterestSeleniumParser...")
            parser = PinterestSeleniumParser(
                headless=self.headless,
                download_images=self.download_images,
                auto_login=self.enable_login
            )
            
            logger.info("ParserInitThread: парсер создан успешно")
            print("✓ Парсер создан успешно")
            
            # Проверяем что драйвер создан
            logger.debug("ParserInitThread: проверка драйвера...")
            if not parser.driver:
                error_msg = "Chrome драйвер не был создан после инициализации парсера"
                logger.critical(f"ParserInitThread: {error_msg}")
                raise RuntimeError(error_msg)
            
            logger.info("ParserInitThread: Chrome драйвер доступен")
            print("✓ Chrome драйвер доступен")
            
            # Отправляем сигнал о готовности парсера
            logger.info("ParserInitThread: отправка сигнала parser_ready...")
            print("Отправка сигнала parser_ready...")
            self.parser_ready.emit(parser)
            logger.info("ParserInitThread: сигнал parser_ready отправлен")
            print("✓ Сигнал parser_ready отправлен")
            
            # Если был включен логин, проверяем успешность и отправляем сигнал
            if self.enable_login:
                logger.debug("ParserInitThread: проверка успешности авторизации...")
                # Проверяем успешность авторизации
                if hasattr(parser, 'login_successful') and parser.login_successful:
                    logger.info("ParserInitThread: авторизация успешна, отправка сигнала login_completed...")
                    print("Отправка сигнала login_completed...")
                    self.login_completed.emit()
                    logger.info("ParserInitThread: сигнал login_completed отправлен")
                    print("✓ Сигнал login_completed отправлен")
                else:
                    logger.warning("ParserInitThread: авторизация не завершена или не удалась")
                    print("⚠ Авторизация не завершена или не удалась")
            
            logger.info("ParserInitThread: инициализация парсера завершена успешно")
            print("\n✓ Инициализация парсера завершена успешно\n")
                
        except RuntimeError as e:
            # Ошибка инициализации драйвера - отправляем специальный сигнал
            error_msg = str(e)
            logger.critical(f"ParserInitThread: ОШИБКА при инициализации парсера (RuntimeError): {error_msg}", exc_info=True)
            print(f"\n❌ ОШИБКА при инициализации парсера (RuntimeError): {error_msg}")
            import traceback
            print("\nПолный traceback:")
            traceback.print_exc()
            # Отправляем ошибку через сигнал
            if hasattr(self, 'error_occurred'):
                self.error_occurred.emit(error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"ParserInitThread: ОШИБКА при инициализации парсера (Exception): {error_msg}", exc_info=True)
            print(f"\n❌ ОШИБКА при инициализации парсера (Exception): {error_msg}")
            import traceback
            print("\nПолный traceback:")
            traceback.print_exc()
            if hasattr(self, 'error_occurred'):
                self.error_occurred.emit(error_msg)


class SearchParseThread(QThread):
    """Поток для парсинга поиска Pinterest"""
    
    parse_progress = pyqtSignal(str)  # Прогресс парсинга
    parse_completed = pyqtSignal(list)  # Результаты парсинга
    parse_error = pyqtSignal(str)  # Ошибка парсинга
    
    def __init__(self, parser: PinterestSeleniumParser, query: str, max_pins: int = 10):
        super().__init__()
        self.parser = parser
        self.query = query
        self.max_pins = max_pins
        self.setTerminationEnabled(True)
    
    def run(self):
        """Выполняет парсинг поиска"""
        logger.info(f"SearchParseThread: запуск парсинга для запроса '{self.query}', max_pins={self.max_pins}")
        try:
            self.parse_progress.emit(f"Начинаем парсинг: {self.query}")
            logger.debug(f"SearchParseThread: начинаем парсинг страницы поиска...")
            
            # Парсим результаты поиска
            pins = self.parser.parse_search_page(self.query, max_pins=self.max_pins)
            logger.info(f"SearchParseThread: парсинг завершен, найдено пинов: {len(pins) if pins else 0}")
            
            if pins:
                self.parse_progress.emit(f"Найдено пинов: {len(pins)}")
                self.parse_completed.emit(pins)
                logger.info("SearchParseThread: сигнал parse_completed отправлен")
            else:
                logger.warning("SearchParseThread: пины не найдены")
                self.parse_error.emit("Пины не найдены")
                
        except Exception as e:
            error_msg = f"Ошибка при парсинге: {str(e)}"
            logger.error(f"SearchParseThread: {error_msg}", exc_info=True)
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.parse_error.emit(error_msg)


class PinterestMainWindow(QMainWindow):
    """Главное окно приложения"""
    
    # Константы для единых отступов (предотвращение наложений)
    MARGIN_SMALL = 8
    MARGIN_MEDIUM = 12
    MARGIN_LARGE = 16
    MARGIN_XLARGE = 20
    SPACING_SMALL = 4
    SPACING_MEDIUM = 8
    SPACING_LARGE = 12
    SPACING_XLARGE = 16
    
    def _create_layout(self, layout_type='vbox', margin='medium', spacing='medium', top_margin=None):
        """
        Создает layout с едиными отступами для предотвращения наложений
        
        Args:
            layout_type: 'vbox', 'hbox', 'grid'
            margin: 'small', 'medium', 'large', 'xlarge' или число
            spacing: 'small', 'medium', 'large', 'xlarge' или число
            top_margin: специальный верхний отступ (для QGroupBox)
        """
        if layout_type == 'vbox':
            layout = QVBoxLayout()
        elif layout_type == 'hbox':
            layout = QHBoxLayout()
        elif layout_type == 'grid':
            layout = QGridLayout()
        else:
            layout = QVBoxLayout()
        
        # Определяем отступы
        margin_map = {
            'small': self.MARGIN_SMALL,
            'medium': self.MARGIN_MEDIUM,
            'large': self.MARGIN_LARGE,
            'xlarge': self.MARGIN_XLARGE
        }
        spacing_map = {
            'small': self.SPACING_SMALL,
            'medium': self.SPACING_MEDIUM,
            'large': self.SPACING_LARGE,
            'xlarge': self.SPACING_XLARGE
        }
        
        margin_val = margin_map.get(margin, margin) if isinstance(margin, str) else margin
        spacing_val = spacing_map.get(spacing, spacing) if isinstance(spacing, str) else spacing
        
        if top_margin is not None:
            top_margin_val = margin_map.get(top_margin, top_margin) if isinstance(top_margin, str) else top_margin
            layout.setContentsMargins(0, top_margin_val, 0, 0)
        else:
            layout.setContentsMargins(margin_val, margin_val, margin_val, margin_val)
        
        layout.setSpacing(spacing_val)
        return layout
    
    def __init__(self):
        logger.info("Инициализация PinterestMainWindow...")
        try:
            logger.debug("Вызов super().__init__()...")
            super().__init__()
            logger.debug("super().__init__() выполнен успешно")
            
            logger.debug("Инициализация переменных экземпляра...")
            self.parser: Optional[PinterestSeleniumParser] = None
            self.account_info_thread: Optional[AccountInfoThread] = None
            self.search_parse_thread: Optional[SearchParseThread] = None
            self.parser_init_thread: Optional[ParserInitThread] = None
            self.connection_test_thread: Optional[QThread] = None
            self.unique_thread: Optional[QThread] = None
            self.load_boards_thread: Optional[QThread] = None
            self.auto_publish_thread: Optional[QThread] = None
            self.parsed_pins: List[Dict] = []  # Сохраняем результаты парсинга
            self.csv_file_path: Optional[str] = None  # Путь к CSV файлу результатов
            self.openrouter_api_key: Optional[str] = None  # API ключ OpenRouter
            self.ai_tokens_used: int = 0  # Счетчик использованных токенов
            self.ai_cost: float = 0.0  # Счетчик затрат в долларах
            self.tray_icon: Optional[QSystemTrayIcon] = None
            self.toast_manager: Optional[ToastManager] = None  # Менеджер уведомлений
            logger.debug("Переменные экземпляра инициализированы")
            
            logger.info("Вызов setup_ui()...")
            self.setup_ui()
            logger.info("setup_ui() выполнен успешно")
            
            logger.info("Вызов setup_tray_icon()...")
            self.setup_tray_icon()
            logger.info("setup_tray_icon() выполнен успешно")
            
            logger.info("Вызов load_config()...")
            self.load_config()
            logger.info("load_config() выполнен успешно")
            
            logger.info("Инициализация ToastManager...")
            self.toast_manager = ToastManager(self)
            logger.info("ToastManager инициализирован успешно")
            
            logger.info("PinterestMainWindow инициализирован успешно")
        except Exception as e:
            logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при инициализации PinterestMainWindow: {e}", exc_info=True)
            raise
    
    def setup_ui(self):
        logger.debug("Начало setup_ui()...")
        try:
            logger.debug("Установка заголовка окна...")
            self.setWindowTitle(get_app_name())
            logger.debug(f"Заголовок установлен: {get_app_name()}")
            
            logger.debug("Установка минимального размера окна...")
            self.setMinimumSize(1000, 700)
            
            # Загружаем стили
            logger.debug("Загрузка стилей...")
            self.load_styles()
            logger.debug("Стили загружены")
        except Exception as e:
            logger.error(f"Ошибка в setup_ui(): {e}", exc_info=True)
            raise
        
        # Создаем главный splitter для сайдбара и центральной области
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)
        
        # === САЙДБАР ===
        sidebar_widget = QWidget()
        sidebar_widget.setObjectName("sidebar")
        # Настраиваем sizePolicy для адаптации по вертикали
        sidebar_size_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sidebar_widget.setSizePolicy(sidebar_size_policy)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(
            self.MARGIN_LARGE, self.MARGIN_LARGE, self.MARGIN_LARGE, self.MARGIN_LARGE
        )
        sidebar_layout.setSpacing(self.SPACING_LARGE)
        
        # Заголовок сайдбара
        sidebar_title = QLabel("Навигация")
        sidebar_title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        sidebar_title.setStyleSheet("""
            QLabel {
                color: #1a1a1a;
                padding: 6px 0px;
                font-size: 11px;
            }
        """)
        sidebar_layout.addWidget(sidebar_title, 0)  # Не растягивается
        
        # === БЛОК: СТАТУС АККАУНТА ===
        account_group = QGroupBox("Аккаунт")
        account_group_layout = QVBoxLayout()
        account_group_layout.setContentsMargins(0, self.MARGIN_SMALL, 0, 0)
        account_group_layout.setSpacing(self.SPACING_MEDIUM)
        
        # Индикатор статуса авторизации с цветной точкой (компактный)
        self.auth_status_indicator = StatusIndicator(self, "Не авторизован", "offline")
        self.auth_status_indicator.setStyleSheet("font-size: 10px;")
        account_group_layout.addWidget(self.auth_status_indicator, 0)  # Не растягивается
        
        account_group.setLayout(account_group_layout)
        sidebar_layout.addWidget(account_group, 0)  # Не растягивается
        
        # === БЛОК: ИИ API ===
        ai_group = QGroupBox("ИИ API")
        ai_layout = QVBoxLayout()
        ai_layout.setContentsMargins(0, self.MARGIN_SMALL, 0, 0)
        ai_layout.setSpacing(self.SPACING_MEDIUM)
        
        # Индикатор подключения ИИ с цветной точкой
        self.ai_status_indicator = StatusIndicator(self, "Не подключен", "offline")
        self.ai_status_indicator.setStyleSheet("font-size: 10px;")
        ai_layout.addWidget(self.ai_status_indicator)
        
        # Поле ввода API ключа (компактное)
        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setPlaceholderText("API ключ...")
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_input.setMaximumHeight(28)
        self.ai_api_key_input.textChanged.connect(self.on_ai_key_changed)
        self.ai_api_key_input.setStyleSheet("""
            QLineEdit {
                font-size: 10px;
                padding: 6px 8px;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #000000;
            }
        """)
        ai_layout.addWidget(self.ai_api_key_input)
        
        # Кнопка проверки подключения
        self.ai_test_btn = QPushButton("Проверить")
        self.ai_test_btn.setObjectName("compactButton")
        self.ai_test_btn.setMaximumHeight(24)
        self.ai_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #000000;
                color: #ffffff;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #333333;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.ai_test_btn.clicked.connect(self.test_ai_connection)
        ai_layout.addWidget(self.ai_test_btn)
        
        # Убрали лишние элементы - перенесены в меню
        
        ai_group.setLayout(ai_layout)
        sidebar_layout.addWidget(ai_group, 0)  # Не растягивается
        
        # Блок режима браузера убран - перенесен в меню
        
        # === БЛОК: НАВИГАЦИЯ ===
        nav_group = QGroupBox("Страницы")
        nav_layout = QVBoxLayout()
        nav_layout.setContentsMargins(0, self.MARGIN_SMALL, 0, 0)
        nav_layout.setSpacing(self.SPACING_SMALL)
        
        # Кнопки навигации
        self.account_btn = QPushButton("Аккаунт")
        self.account_btn.setObjectName("sidebarButton")
        self.account_btn.setCheckable(True)
        self.account_btn.setChecked(True)
        self.account_btn.clicked.connect(lambda: self.show_page("account"))
        nav_layout.addWidget(self.account_btn)
        
        self.parse_btn = QPushButton("Парсинг")
        self.parse_btn.setObjectName("sidebarButton")
        self.parse_btn.setCheckable(True)
        self.parse_btn.clicked.connect(lambda: self.show_page("parse"))
        nav_layout.addWidget(self.parse_btn)
        
        self.results_btn = QPushButton("Результаты")
        self.results_btn.setObjectName("sidebarButton")
        self.results_btn.setCheckable(True)
        self.results_btn.clicked.connect(lambda: self.show_page("results"))
        nav_layout.addWidget(self.results_btn)
        
        self.publish_btn = QPushButton("Публикация")
        self.publish_btn.setObjectName("sidebarButton")
        self.publish_btn.setCheckable(True)
        self.publish_btn.clicked.connect(lambda: self.show_page("publish"))
        nav_layout.addWidget(self.publish_btn)
        
        nav_group.setLayout(nav_layout)
        sidebar_layout.addWidget(nav_group, 0)  # Не растягивается
        
        # Добавляем stretch в конце для заполнения пространства при увеличении высоты окна
        sidebar_layout.addStretch(1)  # Растягивается для заполнения вертикального пространства
        
        sidebar_widget.setLayout(sidebar_layout)
        main_splitter.addWidget(sidebar_widget)
        
        # === ЦЕНТРАЛЬНАЯ ОБЛАСТЬ ===
        # Используем QStackedWidget для правильного переключения страниц без наложений
        self.pages_stack = QStackedWidget()
        self.pages_stack.setObjectName("centralArea")
        
        # === СТРАНИЦА АККАУНТА ===
        self.account_page = QWidget()
        account_layout = self._create_layout('vbox', 'large', 'xlarge')
        self.account_info_widget = AccountInfoWidget()
        account_layout.addWidget(self.account_info_widget, 0)  # Не растягивается
        account_layout.addStretch(1)  # Растягивается для заполнения пространства
        self.account_page.setLayout(account_layout)
        self.pages_stack.addWidget(self.account_page)
        
        # === СТРАНИЦА ПАРСИНГА ===
        self.parse_page = QWidget()
        parse_layout = self._create_layout('vbox', 'large', 'large')
        
        functions_group = QGroupBox("Парсинг")
        functions_layout = self._create_layout('vbox', top_margin='medium', spacing='large')
        
        search_layout = self._create_layout('hbox', spacing='large')
        search_layout.addWidget(QLabel("Запрос:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("python programming...")
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("Парсить")
        self.search_btn.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.search_btn)
        functions_layout.addLayout(search_layout)
        
        # Количество пинов
        count_layout = self._create_layout('hbox', spacing='medium')
        count_layout.addWidget(QLabel("Кол-во:"))
        self.pins_count_spin = QSpinBox()
        self.pins_count_spin.setMinimum(1)
        self.pins_count_spin.setMaximum(1000)
        self.pins_count_spin.setValue(20)
        count_layout.addWidget(self.pins_count_spin)
        count_layout.addStretch()
        functions_layout.addLayout(count_layout)
        
        functions_group.setLayout(functions_layout)
        parse_layout.addWidget(functions_group)
        parse_layout.addStretch()
        self.parse_page.setLayout(parse_layout)
        self.pages_stack.addWidget(self.parse_page)
        
        # === СТРАНИЦА РЕЗУЛЬТАТОВ ===
        self.results_page = QWidget()
        results_layout = self._create_layout('vbox', 'large', 'large')
        
        results_group = QGroupBox("Результаты")
        results_group_layout = self._create_layout('vbox', top_margin='medium', spacing='large')
        
        # История парсингов
        history_group = QGroupBox("История")
        history_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Выбор даты
        date_layout = self._create_layout('hbox', spacing='medium')
        date_layout.addWidget(QLabel("Дата:"))
        self.history_date_combo = QComboBox()
        self.history_date_combo.setMinimumWidth(150)
        self.history_date_combo.currentTextChanged.connect(self.on_history_date_changed)
        date_layout.addWidget(self.history_date_combo)
        date_layout.addStretch()
        history_layout.addLayout(date_layout)
        
        # Список парсингов за выбранную дату - адаптивная высота
        self.history_list = QListWidget()
        self.history_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.history_list.itemClicked.connect(self.on_history_item_selected)
        history_layout.addWidget(self.history_list)
        
        history_group.setLayout(history_layout)
        results_group_layout.addWidget(history_group)
        
        # Информация о CSV файле
        self.csv_info_label = QLabel("CSV не создан")
        self.csv_info_label.setStyleSheet("color: #666666; font-size: 10px;")
        results_group_layout.addWidget(self.csv_info_label)
        
        # === БЛОК: ФИЛЬТРАЦИЯ И СОРТИРОВКА ===
        filter_group = QGroupBox("Фильтры")
        filter_layout = self._create_layout('hbox', spacing='medium')
        
        # Поиск
        filter_layout.addWidget(QLabel("Поиск:"))
        self.filter_search_input = QLineEdit()
        self.filter_search_input.setPlaceholderText("Название/автор...")
        self.filter_search_input.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.filter_search_input)
        
        # Сортировка
        filter_layout.addWidget(QLabel("Сорт:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Дата ↓", "Дата ↑", "Название А-Я", "Название Я-А", "Автор А-Я", "Автор Я-А"])
        self.sort_combo.currentIndexChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.sort_combo)
        
        # Кнопка импорта CSV
        self.import_csv_btn = QPushButton("Импорт")
        self.import_csv_btn.setObjectName("compactButton")
        self.import_csv_btn.clicked.connect(self.import_csv)
        self.import_csv_btn.setToolTip("Импортировать CSV файл")
        filter_layout.addWidget(self.import_csv_btn)
        
        filter_group.setLayout(filter_layout)
        results_group_layout.addWidget(filter_group)
        
        # Виджет сетки с превью изображений - растягивается для заполнения пространства
        self.pin_grid = PinGridWidget()
        results_group_layout.addWidget(self.pin_grid, 1)  # Растягивается
        
        # Текстовая область для отображения информации (скрыта, используется для логов)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(100)
        self.results_text.hide()  # Скрываем текстовую область
        results_group_layout.addWidget(self.results_text)
        
        # Кнопки экспорта и уникализации
        results_buttons_layout = self._create_layout('hbox', spacing='medium')
        self.unique_results_btn = QPushButton("Уникализировать")
        self.unique_results_btn.setObjectName("compactButton")
        self.unique_results_btn.clicked.connect(self.unique_results_csv)
        self.unique_results_btn.setEnabled(False)
        self.unique_results_btn.setToolTip("Уникализировать через ИИ")
        results_buttons_layout.addWidget(self.unique_results_btn)
        self.export_csv_btn = QPushButton("CSV")
        self.export_csv_btn.setObjectName("compactButton")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setToolTip("Экспорт CSV")
        results_buttons_layout.addWidget(self.export_csv_btn)
        
        # Кнопки экспорта в другие форматы
        self.export_json_btn = QPushButton("JSON")
        self.export_json_btn.setObjectName("compactButton")
        self.export_json_btn.clicked.connect(self.export_to_json)
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.setToolTip("Экспорт JSON")
        results_buttons_layout.addWidget(self.export_json_btn)
        
        self.export_excel_btn = QPushButton("Excel")
        self.export_excel_btn.setObjectName("compactButton")
        self.export_excel_btn.clicked.connect(self.export_to_excel)
        self.export_excel_btn.setEnabled(False)
        self.export_excel_btn.setToolTip("Экспорт Excel")
        results_buttons_layout.addWidget(self.export_excel_btn)
        
        results_buttons_layout.addStretch()
        results_group_layout.addLayout(results_buttons_layout)
        
        results_group.setLayout(results_group_layout)
        results_layout.addWidget(results_group)
        self.results_page.setLayout(results_layout)
        self.pages_stack.addWidget(self.results_page)
        
        # === СТРАНИЦА АВТОПУБЛИКАЦИИ ===
        self.publish_page = QWidget()
        publish_layout = self._create_layout('vbox', 'large', 'large')
        
        # === БЛОК 1: ВЫБОР ПАРСИНГА ===
        source_group = QGroupBox("1. Парсинг")
        source_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Выбор даты парсинга
        date_layout = self._create_layout('hbox', spacing='medium')
        date_layout.addWidget(QLabel("Дата:"))
        self.publish_date_combo = QComboBox()
        self.publish_date_combo.setMinimumWidth(120)
        self.publish_date_combo.currentTextChanged.connect(self.on_publish_date_changed)
        date_layout.addWidget(self.publish_date_combo)
        date_layout.addStretch()
        source_layout.addLayout(date_layout)
        
        # Выбор парсинга за дату
        parsing_layout = self._create_layout('hbox', spacing='medium')
        parsing_layout.addWidget(QLabel("Запрос:"))
        self.publish_parsing_combo = QComboBox()
        self.publish_parsing_combo.setMinimumWidth(150)
        self.publish_parsing_combo.currentTextChanged.connect(self.on_publish_parsing_changed)
        parsing_layout.addWidget(self.publish_parsing_combo)
        parsing_layout.addStretch()
        source_layout.addLayout(parsing_layout)
        
        # Информация о выбранном парсинге
        self.publish_parsing_info = QLabel("Выберите парсинг")
        self.publish_parsing_info.setStyleSheet("color: #666666; font-size: 10px;")
        source_layout.addWidget(self.publish_parsing_info)
        
        source_group.setLayout(source_layout)
        publish_layout.addWidget(source_group)
        
        # === БЛОК 2: УНИКАЛИЗАЦИЯ ===
        unique_group = QGroupBox("2. Уникализация")
        unique_layout = self._create_layout('vbox', top_margin='medium', spacing='small')
        
        self.unique_before_publish_checkbox = QCheckBox("Уникализировать через ИИ")
        self.unique_before_publish_checkbox.setStyleSheet("""
            QCheckBox {
                color: #1a1a1a;
                font-size: 10px;
            }
        """)
        unique_layout.addWidget(self.unique_before_publish_checkbox)
        
        unique_group.setLayout(unique_layout)
        publish_layout.addWidget(unique_group)
        
        # === БЛОК 3: ВЫБОР ПИНОВ ===
        pins_group = QGroupBox("3. Пины")
        pins_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Кнопки выбора
        pins_buttons_layout = self._create_layout('hbox', spacing='medium')
        self.select_all_pins_btn = QPushButton("Все")
        self.select_all_pins_btn.setObjectName("compactButton")
        self.select_all_pins_btn.clicked.connect(lambda: self._select_pins(True))
        pins_buttons_layout.addWidget(self.select_all_pins_btn)
        self.deselect_all_pins_btn = QPushButton("Снять")
        self.deselect_all_pins_btn.setObjectName("compactButton")
        self.deselect_all_pins_btn.clicked.connect(lambda: self._select_pins(False))
        pins_buttons_layout.addWidget(self.deselect_all_pins_btn)
        pins_buttons_layout.addStretch()
        self.selected_pins_count_label = QLabel("Выбрано: 0")
        self.selected_pins_count_label.setStyleSheet("font-size: 10px; color: #666666;")
        pins_buttons_layout.addWidget(self.selected_pins_count_label)
        pins_layout.addLayout(pins_buttons_layout)
        
        # Список пинов с чекбоксами
        # Список пинов для выбора - адаптивная высота
        self.pins_list_widget = QListWidget()
        self.pins_list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pins_layout.addWidget(self.pins_list_widget, 1)  # Растягивается
        
        pins_group.setLayout(pins_layout)
        publish_layout.addWidget(pins_group)
        
        # === БЛОК 4: НАСТРОЙКИ ПУБЛИКАЦИИ ===
        settings_group = QGroupBox("4. Настройки")
        settings_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Ссылка
        link_layout = self._create_layout('hbox', spacing='medium')
        link_layout.addWidget(QLabel("Ссылка:"))
        self.pin_link_input = QLineEdit()
        self.pin_link_input.setPlaceholderText("https://...")
        link_layout.addWidget(self.pin_link_input)
        settings_layout.addLayout(link_layout)
        
        # Доска
        board_layout = self._create_layout('hbox', spacing='medium')
        board_layout.addWidget(QLabel("Доска:"))
        self.board_combo = QComboBox()
        self.board_combo.setPlaceholderText("Загрузка...")
        board_layout.addWidget(self.board_combo)
        self.refresh_boards_btn = QPushButton("↻")
        self.refresh_boards_btn.setObjectName("compactButton")
        self.refresh_boards_btn.setMaximumWidth(30)
        self.refresh_boards_btn.clicked.connect(self.load_boards)
        board_layout.addWidget(self.refresh_boards_btn)
        settings_layout.addLayout(board_layout)
        
        # Интервал между публикациями
        interval_layout = self._create_layout('hbox', spacing='medium')
        interval_layout.addWidget(QLabel("Интервал (мин):"))
        self.publish_interval_spin = QSpinBox()
        self.publish_interval_spin.setMinimum(1)
        self.publish_interval_spin.setMaximum(1440)
        self.publish_interval_spin.setValue(30)
        self.publish_interval_spin.setSuffix(" мин")
        interval_layout.addWidget(self.publish_interval_spin)
        interval_layout.addStretch()
        settings_layout.addLayout(interval_layout)
        
        # Время начала публикации
        start_time_layout = self._create_layout('hbox', spacing='medium')
        start_time_layout.addWidget(QLabel("Начать в:"))
        self.publish_start_time = QLineEdit()
        self.publish_start_time.setPlaceholderText("HH:MM или пусто")
        start_time_layout.addWidget(self.publish_start_time)
        settings_layout.addLayout(start_time_layout)
        
        settings_group.setLayout(settings_layout)
        publish_layout.addWidget(settings_group)
        
        # === БЛОК 5: ЗАПУСК ===
        action_group = QGroupBox("5. Запуск")
        action_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Кнопка запуска
        self.start_auto_publish_btn = QPushButton("Запустить")
        self.start_auto_publish_btn.clicked.connect(self.start_auto_publish)
        action_layout.addWidget(self.start_auto_publish_btn)
        
        # Прогресс бар
        self.publish_progress = QProgressBar()
        self.publish_progress.setVisible(False)
        action_layout.addWidget(self.publish_progress)
        
        # Лог публикации - адаптивная высота
        self.publish_log = QTextEdit()
        self.publish_log.setReadOnly(True)
        self.publish_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        action_layout.addWidget(self.publish_log, 1)  # Растягивается
        
        action_group.setLayout(action_layout)
        publish_layout.addWidget(action_group)
        
        publish_layout.addStretch()
        self.publish_page.setLayout(publish_layout)
        self.pages_stack.addWidget(self.publish_page)
        
        # Инициализация данных
        self.publish_selected_pins = []  # Список выбранных пинов
        self.publish_current_csv_path = None
        self.publish_current_pins_data = []  # Текущие данные пинов
        
        # Устанавливаем отступы для центральной области
        central_container = QWidget()
        central_container.setObjectName("centralArea")
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(24, 24, 24, 24)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.pages_stack)
        central_container.setLayout(central_layout)
        
        main_splitter.addWidget(central_container)
        # Адаптивное растягивание: сайдбар фиксированной ширины, центральная область растягивается
        main_splitter.setStretchFactor(0, 0)  # Сайдбар не растягивается
        main_splitter.setStretchFactor(1, 1)  # Центральная область растягивается
        # Убираем жесткие размеры, позволяем пользователю изменять размер splitter'а
        
        # === МЕНЮ ===
        self.setup_menu()
        
        # === СТАТУС БАР ===
        self.statusBar().showMessage("Готово")
    
    def load_styles(self):
        """Загружает стили из QSS файла или встроенный fallback."""
        logger.debug("Начало load_styles()...")
        try:
            style_path = get_styles_path()
            logger.debug(f"Путь к стилям: {style_path}")
            style_file = QFile(str(style_path))
            if style_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
                logger.debug("Файл стилей открыт, чтение...")
                stream = QTextStream(style_file)
                style = stream.readAll()
                self.setStyleSheet(style)
                style_file.close()
                logger.debug("Стили загружены из файла")
            else:
                logger.warning(f"Не удалось открыть файл стилей {style_path}, используем встроенные стили")
                from embedded_styles import EMBEDDED_QSS
                self.setStyleSheet(EMBEDDED_QSS)
                logger.debug("Использованы встроенные стили")
        except Exception as e:
            logger.error(f"Ошибка в load_styles(): {e}", exc_info=True)
            # Пытаемся использовать встроенные стили как fallback
            try:
                from embedded_styles import EMBEDDED_QSS
                self.setStyleSheet(EMBEDDED_QSS)
                logger.warning("Использованы встроенные стили после ошибки")
            except Exception as e2:
                logger.critical(f"Не удалось загрузить даже встроенные стили: {e2}", exc_info=True)
    
    def setup_tray_icon(self):
        """Настраивает системный трей"""
        logger.debug("Начало setup_tray_icon()...")
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("Системный трей недоступен")
                return
            
            logger.debug("Создание иконки трея...")
            # Создаем иконку трея
            self.tray_icon = QSystemTrayIcon(self)
            # Используем стандартную иконку, можно заменить на кастомную
            self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
            
            logger.debug("Создание меню трея...")
            # Создаем меню трея
            tray_menu = QMenu(self)
            
            show_action = QAction("Показать", self)
            show_action.triggered.connect(self.show)
            tray_menu.addAction(show_action)
            
            hide_action = QAction("Скрыть", self)
            hide_action.triggered.connect(self.hide)
            tray_menu.addAction(hide_action)
            
            tray_menu.addSeparator()
            
            quit_action = QAction("Выход", self)
            quit_action.triggered.connect(self.quit_app)
            tray_menu.addAction(quit_action)
            
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self.tray_icon_activated)
            self.tray_icon.show()
            logger.debug("Иконка трея настроена и отображена")
        except Exception as e:
            logger.error(f"Ошибка в setup_tray_icon(): {e}", exc_info=True)
            # Не критично, продолжаем работу
        self.tray_icon.setToolTip(get_app_name())
    
    def tray_icon_activated(self, reason):
        """Обработка активации иконки трея"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()
    
    def quit_app(self):
        """Полный выход из приложения (в т.ч. из трея)"""
        if self.tray_icon and self.tray_icon.isVisible():
            self.tray_icon.hide()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        # Завершаем все потоки
        if hasattr(self, 'account_info_thread') and self.account_info_thread and self.account_info_thread.isRunning():
            self.account_info_thread.quit()
            self.account_info_thread.wait(3000)
        
        if hasattr(self, 'search_parse_thread') and self.search_parse_thread and self.search_parse_thread.isRunning():
            self.search_parse_thread.quit()
            self.search_parse_thread.wait(3000)
        
        if hasattr(self, 'parser_init_thread') and self.parser_init_thread and self.parser_init_thread.isRunning():
            self.parser_init_thread.quit()
            self.parser_init_thread.wait(3000)
        
        if hasattr(self, 'unique_thread') and self.unique_thread and self.unique_thread.isRunning():
            self.unique_thread.quit()
            self.unique_thread.wait(3000)
        
        if hasattr(self, 'connection_test_thread') and self.connection_test_thread and self.connection_test_thread.isRunning():
            self.connection_test_thread.quit()
            self.connection_test_thread.wait(3000)
        
        # Закрываем парсер
        if self.parser:
            try:
                self.parser.close()
            except:
                pass
        
        if self.tray_icon and self.tray_icon.isVisible():
            # Скрываем окно вместо закрытия
            self.hide()
            self.tray_icon.showMessage(
                get_app_name(),
                "Приложение продолжает работать в системном трее",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            event.ignore()
        else:
            event.accept()
    
    def show_page(self, page_name: str):
        """Переключает отображаемую страницу"""
        logger.debug(f"show_page: переключение на страницу '{page_name}'")
        # Сбрасываем все кнопки
        self.account_btn.setChecked(False)
        self.parse_btn.setChecked(False)
        self.results_btn.setChecked(False)
        self.publish_btn.setChecked(False)
        
        # Переключаем страницу через QStackedWidget
        if page_name == "account":
            self.account_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.account_page)
        elif page_name == "parse":
            self.parse_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.parse_page)
        elif page_name == "results":
            self.results_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.results_page)
            # Загружаем историю парсингов при открытии страницы
            try:
                logger.debug("show_page: загрузка истории парсингов для страницы результатов...")
                self._load_parsing_history()
                logger.debug("show_page: история парсингов загружена")
            except Exception as e:
                logger.error(f"show_page: ошибка при загрузке истории парсингов: {e}", exc_info=True)
            # Обновляем информацию о CSV файле
            try:
                if self.csv_file_path and os.path.exists(self.csv_file_path):
                    self.csv_info_label.setText(f"CSV файл: {os.path.basename(self.csv_file_path)}")
                    self.csv_info_label.setStyleSheet("color: #1a1a1a;")
                    self.export_csv_btn.setEnabled(True)
            except Exception as e:
                logger.error(f"show_page: ошибка при обновлении информации о CSV: {e}", exc_info=True)
        elif page_name == "publish":
            self.publish_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.publish_page)
            # Загружаем доски при открытии страницы
            if self.parser:
                self.load_boards()
            # Загружаем историю парсингов для автопубликации
            self._load_publish_history()
    
    def setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()
        
        # Меню "Аккаунт"
        account_menu = menubar.addMenu("Аккаунт")
        
        refresh_action = account_menu.addAction("Обновить информацию")
        refresh_action.triggered.connect(self.refresh_account_info)
        
        account_menu.addSeparator()
        
        logout_action = account_menu.addAction("Выйти")
        logout_action.triggered.connect(self.on_logout)
        
        # Меню "Данные"
        data_menu = menubar.addMenu("Данные")
        
        backup_action = data_menu.addAction("Создать резервную копию")
        backup_action.triggered.connect(self.backup_data)
        
        restore_action = data_menu.addAction("Восстановить из резервной копии")
        restore_action.triggered.connect(self.restore_data)
        
        data_menu.addSeparator()
        
        clear_cache_action = data_menu.addAction("Очистить кэш")
        clear_cache_action.triggered.connect(self._clear_cache)
        
        # Меню "Настройки"
        settings_menu = menubar.addMenu("Настройки")
        
        # Режим браузера
        self.headless_action = settings_menu.addAction("Работать в фоне")
        self.headless_action.setCheckable(True)
        self.headless_action.setChecked(False)
        self.headless_action.triggered.connect(self.on_headless_mode_changed_from_menu)
        
        settings_menu.addSeparator()
        
        # Метрики ИИ
        self.ai_metrics_action = settings_menu.addAction("ИИ: Токены: 0 | $0.00")
        self.ai_metrics_action.setEnabled(False)  # Только для отображения
        
        settings_menu.addSeparator()
        
        # Информация о модели
        model_action = settings_menu.addAction("Модель: mistralai/mistral-nemo")
        model_action.setEnabled(False)
        
        # Ссылка на получение ключа
        key_action = settings_menu.addAction("Получить API ключ")
        key_action.triggered.connect(lambda: webbrowser.open("https://openrouter.ai/keys"))
        
        settings_menu.addSeparator()
        
        config_action = settings_menu.addAction("Конфигурация")
        config_action.triggered.connect(self.show_config)
    
    def on_headless_mode_changed_from_menu(self, checked):
        """Обработчик изменения режима браузера из меню"""
        new_headless = checked
        self.on_headless_mode_changed_internal(new_headless)
    
    def on_headless_mode_changed(self, state):
        """Обработчик изменения режима браузера"""
        new_headless = (state == Qt.CheckState.Checked.value)
        self.on_headless_mode_changed_internal(new_headless)
    
    def on_headless_mode_changed_internal(self, new_headless):
        """Внутренний обработчик изменения режима браузера"""
        current_headless = self.parser_config.get('headless', False)
        
        if new_headless == current_headless:
            return  # Режим не изменился
        
        # Обновляем чекбокс в меню если он есть
        if hasattr(self, 'headless_action'):
            self.headless_action.setChecked(new_headless)
        
        # Сохраняем настройку
        self.parser_config['headless'] = new_headless
        
        # Сохраняем в config.json
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config['headless'] = new_headless
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении настройки: {e}")
        
        # Если парсер уже инициализирован, автоматически перезапускаем
        if self.parser and self.parser.driver:
            old_headless = self.parser.headless
            if old_headless != new_headless:
                # Автоматически перезапускаем парсер с новыми настройками
                # Cookies уже сохранены, так что авторизация сохранится
                print(f"🔄 Переключение режима: {'headless' if old_headless else 'visible'} → {'headless' if new_headless else 'visible'}")
                self.statusBar().showMessage("Перезапуск парсера с новыми настройками...")
                
                # Закрываем текущий парсер
                try:
                    if self.parser:
                        self.parser.close()
                except:
                    pass
                self.parser = None
                
                # Перезапускаем парсер с новыми настройками
                QTimer.singleShot(500, self._restart_parser_with_config)
        
        # Обновляем индикатор
        self._update_browser_mode_indicator()
    
    def load_config(self):
        """Загружает конфигурацию и инициализирует парсер"""
        logger.debug("Начало load_config()...")
        try:
            config_path = get_config_path()
            logger.debug(f"Путь к конфигу: {config_path}")
            try:
                if config_path.exists():
                    logger.debug("Чтение конфига из файла...")
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    logger.debug("Конфиг загружен из файла")
                else:
                    logger.debug("Файл конфига не существует, используем пустой конфиг")
                    config = {}
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}", exc_info=True)
                config = {}
            
            # Загружаем API ключ OpenRouter
            self.openrouter_api_key = config.get("openrouter_api_key", "")
            self.ai_tokens_used = config.get("ai_tokens_used", 0)
            self.ai_cost = config.get("ai_cost", 0.0)
            
            # Обновляем UI если ключ уже есть
            if hasattr(self, 'ai_api_key_input'):
                self.ai_api_key_input.setText(self.openrouter_api_key)
                self._update_ai_tokens_display()
                if self.openrouter_api_key:
                    QTimer.singleShot(500, self.test_ai_connection)
            
            # Обновляем метрики в меню
            self._update_ai_metrics_in_menu()
            
            enable_login = config.get("enable_login", False)
            headless = config.get("headless", True)
            download_images = config.get("download_images", True)
            
            # Если включен логин, headless должен быть False
            if enable_login:
                headless = False
            
            # Ленивая инициализация парсера - создаем только когда нужно
            # Не инициализируем сразу, чтобы не блокировать запуск приложения
            self.parser = None
            self.login_completed = False
            self.parser_config = {
                'enable_login': enable_login,
                'headless': headless,
                'download_images': download_images
            }
            
            # Обновляем чекбокс режима браузера в меню если он уже создан
            if hasattr(self, 'headless_action'):
                self.headless_action.setChecked(headless)
            
            # Загружаем историю парсингов
            QTimer.singleShot(1000, self._load_parsing_history)
            # Загружаем последний парсинг если есть
            QTimer.singleShot(1500, self._load_last_parsing)
            
            # Если включен логин, инициализируем парсер в фоне (с задержкой для полной инициализации UI)
            if enable_login:
                # Запускаем инициализацию парсера в отдельном потоке с задержкой
                QTimer.singleShot(2000, lambda: self._init_parser_with_login(enable_login, headless, download_images))
            else:
                # Если логин не нужен, парсер будет создан при первом использовании
                # Проверяем наличие cookies и загружаем информацию об аккаунте после инициализации
                cookies_file = get_cookies_path()
                if cookies_file.exists():
                    # Инициализируем парсер в фоне для загрузки информации об аккаунте
                    QTimer.singleShot(500, self._lazy_init_parser)
        except Exception as e:
            logger.error(f"Ошибка в load_config(): {e}", exc_info=True)
            # Устанавливаем значения по умолчанию при ошибке
            self.openrouter_api_key = ""
            self.ai_tokens_used = 0
            self.ai_cost = 0.0
            self.parser = None
            self.login_completed = False
            self.parser_config = {
                'enable_login': False,
                'headless': True,
                'download_images': True
            }
            # При ошибке не инициализируем парсер
            enable_login = False
            headless = True
            download_images = True
    
    def _lazy_init_parser(self):
        """Ленивая инициализация парсера в фоне (без логина)"""
        if self.parser and self.parser.driver:
            # Уже инициализирован и работает
            cookies_file = get_cookies_path()
            if cookies_file.exists():
                QTimer.singleShot(500, self.refresh_account_info)
            return
        
        try:
            config = self.parser_config
            self.parser = PinterestSeleniumParser(
                headless=config['headless'],
                download_images=config['download_images'],
                auto_login=False
            )
            # Проверяем что драйвер создан
            if self.parser.driver:
                # Блокируем кнопку парсинга на 10 секунд для инициализации браузера
                self._block_parse_button(10)
                # Проверяем наличие cookies и загружаем информацию об аккаунте
                cookies_file = get_cookies_path()
                if cookies_file.exists():
                    QTimer.singleShot(500, self.refresh_account_info)
            else:
                print("Chrome драйвер не создан, парсер будет недоступен")
        except Exception as e:
            print(f"Ошибка инициализации парсера: {e}")
            self.statusBar().showMessage("Парсер недоступен - проверьте Chrome")
            # Парсер будет создан при первом использовании
    
    def _ensure_parser(self) -> bool:
        """Проверяет наличие парсера и инициализирует при необходимости"""
        # Проверяем, нужно ли перезапустить парсер из-за изменения настроек
        if self.parser and self.parser.driver:
            # Проверяем соответствие режима headless
            current_headless = self.parser_config.get('headless', False)
            if self.parser.headless != current_headless:
                print(f"⚠ Режим парсера не соответствует настройкам. Перезапускаю...")
                print(f"   Текущий режим: {'headless' if self.parser.headless else 'visible'}")
                print(f"   Требуемый режим: {'headless' if current_headless else 'visible'}")
                try:
                    self.parser.close()
                except:
                    pass
                self.parser = None
            else:
                return True
        
        try:
            config = self.parser_config
            self.statusBar().showMessage("Инициализация парсера...")
            self.parser = PinterestSeleniumParser(
                headless=config['headless'],
                download_images=config['download_images'],
                auto_login=False
            )
            # Проверяем что драйвер действительно создан
            if not self.parser.driver:
                raise RuntimeError("Chrome драйвер не был создан")
            
            # Загружаем cookies если они есть (даже если auto_login=False)
            # Это нужно для работы в headless режиме
            try:
                from path_utils import get_cookies_path
                from cookies_manager import load_cookies_from_file
                cookies_file = get_cookies_path()
                if cookies_file.exists():
                    print("📋 Загружаю cookies для работы в headless режиме...")
                    # В headless режиме просто загружаем cookies без попытки логина
                    if config['headless']:
                        # Загружаем cookies напрямую без проверки авторизации
                        cookies = load_cookies_from_file(str(cookies_file))
                        if cookies:
                            self.parser.driver.get("https://www.pinterest.com")
                            import time
                            time.sleep(2)
                            cookies_set = 0
                            for name, value in cookies.items():
                                try:
                                    self.parser.driver.add_cookie({
                                        'name': name,
                                        'value': value,
                                        'domain': '.pinterest.com',
                                        'path': '/'
                                    })
                                    cookies_set += 1
                                except:
                                    pass
                            print(f"  ✓ Установлено {cookies_set} из {len(cookies)} cookies")
                            self.parser.driver.refresh()
                            time.sleep(2)
                            print("✓ Cookies загружены в headless режиме")
                    else:
                        # В видимом режиме используем стандартную проверку
                        self.parser._ensure_authentication()
            except Exception as e:
                print(f"⚠ Не удалось загрузить cookies: {e}")
                # Это не критично, продолжаем работу
            
            self.statusBar().showMessage("Парсер готов")
            # Блокируем кнопку парсинга на 10 секунд для инициализации браузера
            self._block_parse_button(10)
            return True
        except RuntimeError as e:
            error_msg = str(e)
            print(f"Ошибка инициализации парсера: {error_msg}")
            self.statusBar().showMessage("Парсер недоступен - проверьте Chrome")
            QMessageBox.warning(
                self, 
                "Ошибка инициализации", 
                f"Не удалось инициализировать парсер:\n{error_msg}\n\n"
                "Убедитесь, что:\n"
                "• Google Chrome установлен\n"
                "• Chrome доступен в системе\n"
                "• Нет проблем с правами доступа"
            )
            return False
        except Exception as e:
            error_msg = f"Неожиданная ошибка: {e}"
            print(f"Ошибка инициализации парсера: {error_msg}")
            self.statusBar().showMessage("Ошибка инициализации парсера")
            QMessageBox.warning(
                self, 
                "Ошибка инициализации", 
                f"Не удалось инициализировать парсер:\n{error_msg}"
            )
            return False
    
    def on_parser_init_error(self, error_msg: str):
        """Обработчик ошибки инициализации парсера"""
        from PyQt6.QtWidgets import QMessageBox, QPushButton
        import platform
        import subprocess
        import os
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Ошибка инициализации")
        msg.setIcon(QMessageBox.Icon.Warning)
        
        # Основное сообщение
        main_text = f"Не удалось инициализировать парсер:\n\n{error_msg}\n\n"
        main_text += "Убедитесь, что:\n"
        main_text += "• Google Chrome установлен\n"
        main_text += "• Chrome доступен в системе\n"
        main_text += "• Нет проблем с правами доступа\n\n"
        
        # Для macOS добавляем специальные инструкции
        if platform.system() == 'Darwin':
            main_text += "Для macOS:\n"
            main_text += "Проблема часто связана с карантином (quarantine) на Chrome драйвере.\n\n"
            
            # Пробуем найти путь к драйверу
            driver_path = None
            try:
                from chromedriver_helper import get_chromedriver_path
                driver_path = get_chromedriver_path()
            except:
                # Пробуем найти вручную
                home = os.path.expanduser("~")
                wdm_path = os.path.join(home, ".wdm", "drivers", "chromedriver")
                if os.path.exists(wdm_path):
                    for root, dirs, files in os.walk(wdm_path):
                        if "chromedriver" in files:
                            driver_path = os.path.join(root, "chromedriver")
                            break
            
            if driver_path and os.path.exists(driver_path):
                main_text += f"Путь к драйверу:\n{driver_path}\n\n"
                main_text += "Попробуйте выполнить в терминале:\n"
                main_text += f"xattr -d com.apple.quarantine '{driver_path}'\n"
                main_text += f"или\n"
                main_text += f"xattr -c '{driver_path}'\n"
                main_text += f"или\n"
                main_text += f"chmod +x '{driver_path}'\n\n"
                
                # Добавляем кнопку для автоматического исправления
                fix_btn = QPushButton("Попробовать исправить автоматически")
                fix_btn.clicked.connect(lambda: self._try_fix_chromedriver(driver_path, msg))
                msg.addButton(fix_btn, QMessageBox.ButtonRole.ActionRole)
            else:
                main_text += "Не удалось найти путь к драйверу.\n"
                main_text += "Попробуйте найти вручную:\n"
                main_text += "find ~/.wdm -name chromedriver -type f\n"
        
        msg.setText(main_text)
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        
        self.statusBar().showMessage("Ошибка инициализации парсера")
    
    def _try_fix_chromedriver(self, driver_path: str, parent_msg: QMessageBox):
        """Пытается автоматически исправить проблему с Chrome драйвером"""
        import subprocess
        import os
        from PyQt6.QtWidgets import QMessageBox
        
        parent_msg.close()
        
        fixes_applied = []
        
        # Попытка 1: Удалить карантин
        try:
            result = subprocess.run(
                ['xattr', '-d', 'com.apple.quarantine', driver_path],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                timeout=10
            )
            if result.returncode == 0:
                fixes_applied.append("✓ Карантин удален")
            else:
                # Пробуем удалить все атрибуты
                result2 = subprocess.run(
                    ['xattr', '-c', driver_path],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    timeout=10
                )
                if result2.returncode == 0:
                    fixes_applied.append("✓ Все расширенные атрибуты удалены")
        except Exception as e:
            pass
        
        # Попытка 2: Установить права на выполнение
        try:
            os.chmod(driver_path, 0o755)
            fixes_applied.append("✓ Права доступа установлены")
        except Exception as e:
            pass
        
        # Показываем результат
        result_msg = QMessageBox(self)
        result_msg.setWindowTitle("Результат исправления")
        
        if fixes_applied:
            result_msg.setIcon(QMessageBox.Icon.Information)
            result_text = "Выполнены исправления:\n\n"
            result_text += "\n".join(fixes_applied)
            result_text += "\n\nПопробуйте запустить приложение снова."
            result_msg.setText(result_text)
        else:
            result_msg.setIcon(QMessageBox.Icon.Warning)
            result_text = "Не удалось автоматически исправить проблему.\n\n"
            result_text += "Попробуйте выполнить вручную в терминале:\n"
            result_text += f"xattr -d com.apple.quarantine '{driver_path}'\n"
            result_text += f"xattr -c '{driver_path}'\n"
            result_text += f"chmod +x '{driver_path}'"
            result_msg.setText(result_text)
        
        result_msg.exec()
    
    def _init_parser_with_login(self, enable_login: bool, headless: bool, download_images: bool):
        """Инициализирует парсер с логином в отдельном потоке"""
        # Проверяем, не инициализируется ли уже парсер
        if hasattr(self, 'parser_init_thread') and self.parser_init_thread is not None and self.parser_init_thread.isRunning():
            logger.warning("_init_parser_with_login: парсер уже инициализируется, пропускаем повторный вызов")
            return
        
        # Проверяем, не создан ли уже парсер
        if self.parser is not None:
            logger.warning("_init_parser_with_login: парсер уже создан, пропускаем повторную инициализацию")
            return
        
        logger.info(f"_init_parser_with_login: запуск инициализации парсера, enable_login={enable_login}, headless={headless}")
        try:
            # Создаем поток для инициализации парсера
            self.parser_init_thread = ParserInitThread(enable_login, headless, download_images)
            self.parser_init_thread.parser_ready.connect(self.on_parser_ready)
            self.parser_init_thread.login_completed.connect(self.on_login_completed)
            self.parser_init_thread.error_occurred.connect(self.on_parser_error)
            self.parser_init_thread.start()
            logger.info("_init_parser_with_login: поток инициализации парсера запущен")
        except Exception as e:
            logger.error(f"_init_parser_with_login: ошибка при запуске потока: {e}", exc_info=True)
            self.statusBar().showMessage(f"Ошибка инициализации парсера: {str(e)}")
    
    def on_parser_error(self, error_msg: str):
        """Обработчик ошибки инициализации парсера"""
        logger.error(f"on_parser_error: {error_msg}")
        self.statusBar().showMessage(f"Ошибка парсера: {error_msg}")
        if self.toast_manager:
            self.toast_manager.show_error(f"Ошибка парсера: {error_msg}")
    
    def on_parser_ready(self, parser: PinterestSeleniumParser):
        """Обработчик готовности парсера"""
        logger.info("on_parser_ready: парсер готов")
        self.parser = parser
        self.statusBar().showMessage("Парсер готов")
        
        # Блокируем кнопку парсинга на 10 секунд для инициализации браузера
        self._block_parse_button(10)
        
        # Обновляем индикатор режима браузера
        self._update_browser_mode_indicator()
        
        # Если парсер готов и есть cookies, загружаем информацию об аккаунте
        if self.parser:
            # Проверяем наличие cookies файла
            cookies_file = get_cookies_path()
            if cookies_file.exists():
                # Загружаем информацию об аккаунте автоматически
                self.refresh_account_info()
    
    def _update_browser_mode_indicator(self):
        """Обновляет индикатор режима браузера (убрано из сайдбара, теперь в меню)"""
        # Метод оставлен для совместимости, но больше не обновляет UI в сайдбаре
        # Режим браузера теперь управляется через меню "Настройки" -> "Работать в фоне"
        pass
    
    def on_login_completed(self):
        """Обработчик завершения логина - загружаем информацию об аккаунте"""
        self.login_completed = True
        self.statusBar().showMessage("Логин завершен, загрузка информации об аккаунте...")
        # Загружаем информацию об аккаунте после успешного логина с небольшой задержкой
        if self.parser:
            # Небольшая задержка чтобы браузер успел полностью загрузиться
            QTimer.singleShot(2000, self.refresh_account_info)
    
    def _block_parse_button(self, seconds: int = 10):
        """Блокирует кнопку парсинга на указанное количество секунд"""
        if not hasattr(self, 'search_btn'):
            return
        
        # Блокируем кнопку
        self.search_btn.setEnabled(False)
        original_text = self.search_btn.text()
        
        # Обновляем текст кнопки с обратным отсчетом
        def update_button_text(remaining):
            if remaining > 0:
                self.search_btn.setText(f"Ожидание... ({remaining}с)")
                QTimer.singleShot(1000, lambda: update_button_text(remaining - 1))
            else:
                # Разблокируем кнопку
                self.search_btn.setEnabled(True)
                self.search_btn.setText(original_text)
                self.statusBar().showMessage("Парсер готов к работе")
        
        # Начинаем отсчет
        self.statusBar().showMessage(f"Инициализация браузера... Парсинг будет доступен через {seconds} секунд")
        update_button_text(seconds)
    
    def on_ai_key_changed(self, text: str):
        """Обработчик изменения API ключа"""
        self.openrouter_api_key = text.strip()
        # Сохраняем в config.json
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            config['openrouter_api_key'] = self.openrouter_api_key
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении API ключа: {e}")
        
        # Обновляем статус
        if not text.strip():
            self.ai_status_indicator.set_text("Не подключен")
            self.ai_status_indicator.update_status("offline")
    
    def test_ai_connection(self):
        """Проверяет подключение к OpenRouter API"""
        api_key = self.openrouter_api_key or (hasattr(self, 'ai_api_key_input') and self.ai_api_key_input.text().strip())
        if not api_key:
            self.ai_status_indicator.set_text("Не подключен")
            self.ai_status_indicator.update_status("offline")
            return
        
        self.ai_test_btn.setEnabled(False)
        self.ai_test_btn.setText("Проверка...")
        self.ai_status_indicator.set_text("Проверка подключения...")
        self.ai_status_indicator.update_status("loading")
        
        # Запускаем проверку в отдельном потоке
        class ConnectionTestThread(QThread):
            finished = pyqtSignal(bool, str)  # success, message
            
            def __init__(self, api_key):
                super().__init__()
                self.api_key = api_key
            
            def run(self):
                logger.info("ConnectionTestThread: запуск проверки подключения к ИИ API...")
                try:
                    logger.debug("ConnectionTestThread: отправка запроса к OpenRouter API...")
                    # Используем только ASCII символы в заголовках для избежания проблем с кодировкой
                    response = requests.post(
                        url="https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "mistralai/mistral-nemo",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "test"
                                }
                            ],
                            "max_tokens": 5
                        },
                        timeout=10
                    )
                    response.raise_for_status()
                    result = response.json()
                    logger.info("ConnectionTestThread: подключение к ИИ API успешно")
                    self.finished.emit(True, "Подключение успешно")
                except requests.exceptions.RequestException as e:
                    error_msg = str(e)
                    logger.error(f"ConnectionTestThread: ошибка запроса: {error_msg}", exc_info=True)
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        error_msg = "Неверный API ключ"
                    elif "429" in error_msg:
                        error_msg = "Превышен лимит запросов"
                    else:
                        error_msg = f"Ошибка: {error_msg[:50]}"
                    self.finished.emit(False, error_msg)
                except Exception as e:
                    logger.critical(f"ConnectionTestThread: неожиданная ошибка: {e}", exc_info=True)
                    self.finished.emit(False, f"Неожиданная ошибка: {str(e)}")
        
        def on_test_finished(success: bool, message: str):
            if success:
                self.ai_status_indicator.set_text("Подключен")
                self.ai_status_indicator.update_status("online")
                self.openrouter_api_key = api_key
            if self.toast_manager:
                self.toast_manager.show_success("ИИ API успешно подключен")
            else:
                self.ai_status_indicator.set_text(message)
                self.ai_status_indicator.update_status("error")
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка подключения: {message}")
            self.ai_test_btn.setEnabled(True)
            self.ai_test_btn.setText("Проверить подключение")
        
        self.connection_test_thread = ConnectionTestThread(api_key)
        self.connection_test_thread.finished.connect(on_test_finished)
        self.connection_test_thread.start()
    
    def _update_ai_tokens_display(self):
        """Обновляет отображение счетчика токенов"""
        self._update_ai_metrics_in_menu()
    
    def _update_ai_metrics_in_menu(self):
        """Обновляет метрики ИИ в меню"""
        if hasattr(self, 'ai_metrics_action'):
            self.ai_metrics_action.setText(f"ИИ: Токены: {self.ai_tokens_used:,} | Затраты: ${self.ai_cost:.4f}")
    
    def _save_ai_stats(self):
        """Сохраняет статистику использования ИИ"""
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            config['ai_tokens_used'] = self.ai_tokens_used
            config['ai_cost'] = self.ai_cost
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении статистики ИИ: {e}")
    
    def refresh_account_info(self):
        """Обновляет информацию об аккаунте"""
        if not self._ensure_parser():
            return
        
        self.statusBar().showMessage("Загрузка информации об аккаунте...")
        self.account_info_widget.refresh_btn.setEnabled(False)
        
        # Запускаем в отдельном потоке
        self.account_info_thread = AccountInfoThread(self.parser)
        self.account_info_thread.account_info_ready.connect(self.on_account_info_ready)
        self.account_info_thread.error_occurred.connect(self.on_account_info_error)
        self.account_info_thread.start()
    
    def on_account_info_ready(self, account_info: Dict[str, str]):
        """Обработчик успешного получения информации об аккаунте"""
        # Обновляем виджет с информацией об аккаунте
        self.account_info_widget.update_account_info(account_info)
        
        # Обновляем индикатор в сайдбаре
        username = account_info.get('username', '')
        if username:
            # Используем новый индикатор
            if hasattr(self, 'auth_status_indicator'):
                self.auth_status_indicator.set_text(f"@{username}")
                self.auth_status_indicator.update_status("online")
        else:
            # Используем новый индикатор
            if hasattr(self, 'auth_status_indicator'):
                self.auth_status_indicator.set_text("Не авторизован")
                self.auth_status_indicator.update_status("offline")
        
        # Формируем сообщение о результатах парсинга
        pins_count = account_info.get('pins_count', 'Неизвестно')
        boards_count = account_info.get('boards_count', 'Неизвестно')
        status_msg = f"Аккаунт авторизован: @{username} | {pins_count}, {boards_count}"
        self.statusBar().showMessage(status_msg)
        
        self.account_info_widget.refresh_btn.setEnabled(True)
    
    def on_account_info_error(self, error: str):
        """Обработчик ошибки при получении информации об аккаунте"""
        self.account_info_widget.update_account_info(None)
        
        # Обновляем индикатор в сайдбаре
        self.auth_status_indicator.set_text("Не авторизован")
        self.auth_status_indicator.update_status("offline")
        self.auth_username_label.hide()
        
        self.statusBar().showMessage(f"Ошибка: {error}")
        self.account_info_widget.refresh_btn.setEnabled(True)
        if self.toast_manager:
            self.toast_manager.show_error(error)
    
    def on_search_clicked(self):
        """Обработчик парсинга по поиску"""
        query = self.search_input.text().strip()
        if not query:
            if self.toast_manager:
                self.toast_manager.show_warning("Введите тематику для поиска")
            return
        
        if not self._ensure_parser():
            return
        
        # Получаем количество пинов
        max_pins = self.pins_count_spin.value()
        
        # Очищаем результаты
        self.pin_grid.display_pins([])  # Очищаем сетку
        
        # Блокируем кнопку на время парсинга
        self.search_btn.setEnabled(False)
        self.statusBar().showMessage("Парсинг в процессе...")
        
        # Запускаем парсинг в отдельном потоке
        self.search_parse_thread = SearchParseThread(self.parser, query, max_pins=max_pins)
        self.search_parse_thread.parse_progress.connect(self.on_parse_progress)
        self.search_parse_thread.parse_completed.connect(self.on_parse_completed)
        self.search_parse_thread.parse_error.connect(self.on_parse_error)
        self.search_parse_thread.start()
    
    def on_parse_progress(self, message: str):
        """Обработчик прогресса парсинга"""
        self.statusBar().showMessage(message)
    
    def on_parse_completed(self, pins: list):
        """Обработчик завершения парсинга"""
        # Сохраняем результаты парсинга
        self.parsed_pins = pins
        
        # Сохраняем в CSV с датой
        try:
            from datetime import datetime
            import csv
            
            # Создаем папку с текущей датой
            current_date = datetime.now().strftime("%Y-%m-%d")
            csv_dir = get_csv_dir(current_date)
            
            query = self.search_input.text().strip()
            timestamp = datetime.now().strftime("%H-%M-%S")
            filename = f"pinterest_pins_{query.replace(' ', '_').replace('/', '_')[:50]}_{timestamp}.csv"
            csv_path = csv_dir / filename
            
            # Сохраняем в CSV
            if pins:
                fieldnames = ['title', 'description', 'pin_link', 'image_url', 'author', 'board_name', 'board_url']
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(pins)
            self.csv_file_path = str(csv_path)
            
            # Сохраняем в историю парсингов
            self._save_parsing_to_history(query, len(pins), str(csv_path), current_date)
            
            # Переключаемся на страницу результатов
            self.show_page("results")
            
            # Отображаем пины в сетке
            self.pin_grid.display_pins(pins)
            
            # Обновляем информацию
            self.csv_info_label.setText(f"Найдено пинов: {len(pins)} | CSV файл: {os.path.basename(filename)}")
            self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
            self.unique_results_btn.setEnabled(True)
            self.export_csv_btn.setEnabled(True)
            
            self.statusBar().showMessage(f"Парсинг завершен. Найдено {len(pins)} пинов. Сохранено в {current_date}/{filename}")
        except Exception as e:
            self.statusBar().showMessage(f"Парсинг завершен, но ошибка при сохранении: {e}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при сохранении CSV: {e}")
        
        self.search_btn.setEnabled(True)
    
    def on_parse_error(self, error: str):
        """Обработчик ошибки парсинга"""
        self.statusBar().showMessage(f"Ошибка: {error}")
        self.search_btn.setEnabled(True)
        if self.toast_manager:
            self.toast_manager.show_error(f"Ошибка парсинга: {error}")
    
    def on_logout(self):
        """Обработчик выхода из аккаунта"""
        reply = QMessageBox.question(
            self, "Выход", 
            "Вы уверены, что хотите выйти?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.account_info_widget.update_account_info(None)
            self.statusBar().showMessage("Выход выполнен")
    
    def show_config(self):
        """Показывает окно настроек"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки")
        dialog.setMinimumWidth(450)
        
        layout = QVBoxLayout()
        layout.setSpacing(16)
        
        # OpenRouter API ключ
        api_key_group = QGroupBox("OpenRouter API")
        api_key_layout = QVBoxLayout()
        api_key_layout.setSpacing(8)
        
        api_key_layout.addWidget(QLabel("API ключ OpenRouter:"))
        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText("Введите ваш OpenRouter API ключ...")
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        if self.openrouter_api_key:
            api_key_input.setText(self.openrouter_api_key)
        api_key_layout.addWidget(api_key_input)
        
        api_key_group.setLayout(api_key_layout)
        layout.addWidget(api_key_group)
        
        # Настройки браузера
        browser_group = QGroupBox("Настройки браузера")
        browser_layout = QVBoxLayout()
        browser_layout.setSpacing(8)
        
        # Headless режим
        headless_checkbox = QCheckBox("Работать в фоновом режиме (без окна браузера)")
        headless_checkbox.setToolTip("Если включено, браузер будет работать в фоне без видимого окна")
        current_headless = self.parser_config.get('headless', False)
        headless_checkbox.setChecked(current_headless)
        browser_layout.addWidget(headless_checkbox)
        
        # Информация о текущем режиме
        if self.parser and self.parser.driver:
            current_mode = "фоновый" if self.parser.headless else "обычный"
            mode_label = QLabel(f"Текущий режим: {current_mode}")
            mode_label.setStyleSheet("color: #666666; font-size: 11px;")
            browser_layout.addWidget(mode_label)
        
        browser_group.setLayout(browser_layout)
        layout.addWidget(browser_group)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        
        def save_config():
            self.openrouter_api_key = api_key_input.text().strip()
            new_headless = headless_checkbox.isChecked()
            
            # Сохраняем в config.json
            try:
                config_path = get_config_path()
                config = {}
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                
                config['openrouter_api_key'] = self.openrouter_api_key
                config['headless'] = new_headless
                
                # Если включен логин, headless должен быть False
                if config.get('enable_login', False) and new_headless:
                    QMessageBox.warning(
                        dialog, 
                        "Предупреждение", 
                        "Нельзя включить фоновый режим при включенной авторизации.\n"
                        "Сначала отключите авторизацию в config.json"
                    )
                    return
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                # Обновляем конфигурацию парсера
                self.parser_config['headless'] = new_headless
                
                # Если режим изменился и парсер уже инициализирован, нужно перезапустить
                if self.parser and self.parser.driver:
                    old_headless = self.parser.headless
                    if old_headless != new_headless:
                        reply = QMessageBox.question(
                            dialog,
                            "Перезапуск парсера",
                            "Для применения изменений нужно перезапустить парсер.\n"
                            "Перезапустить сейчас?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            # Закрываем текущий парсер и все старые браузеры
                            try:
                                if self.parser:
                                    self.parser.close()
                            except:
                                pass
                            self.parser = None
                            
                            # Перезапускаем парсер с новыми настройками (закроет старые браузеры)
                            QTimer.singleShot(500, self._restart_parser_with_config)
                
                if self.toast_manager:
                    self.toast_manager.show_success("Настройки сохранены")
                dialog.accept()
            except Exception as e:
                if self.toast_manager:
                    self.toast_manager.show_error(f"Не удалось сохранить настройки: {e}")
        
        save_btn.clicked.connect(save_config)
        cancel_btn.clicked.connect(dialog.reject)
        
        buttons_layout.addWidget(save_btn)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def _restart_parser_with_config(self):
        """Перезапускает парсер с текущей конфигурацией"""
        try:
            config = self.parser_config
            enable_login = config.get('enable_login', False)
            headless = config.get('headless', True)
            download_images = config.get('download_images', True)
            
            # Проверяем наличие cookies - если они есть, можно работать в headless даже при enable_login
            from path_utils import get_cookies_path
            cookies_file = get_cookies_path()
            has_cookies = cookies_file.exists()
            
            # Если включен логин И нет cookies, headless должен быть False (нужен видимый браузер для первого входа)
            # Но если cookies уже есть, разрешаем headless режим
            if enable_login and not has_cookies:
                headless = False
                print("⚠ Первичная авторизация: браузер будет видимым для входа")
            elif has_cookies:
                # Cookies есть, можно работать в headless даже если enable_login=True
                print("✓ Cookies найдены: можно работать в headless режиме")
                # auto_login не нужен, так как cookies уже есть
                enable_login = False
            
            self.statusBar().showMessage("Перезапуск парсера...")
            
            # Создаем новый парсер (автоматически закроет старые браузеры в _setup_driver)
            self.parser = PinterestSeleniumParser(
                headless=headless,
                download_images=download_images,
                auto_login=enable_login
            )
            
            if self.parser and self.parser.driver:
                # Загружаем cookies если они есть (даже если auto_login=False)
                # Это нужно для работы в headless режиме
                try:
                    from path_utils import get_cookies_path
                    from cookies_manager import load_cookies_from_file
                    cookies_file = get_cookies_path()
                    if cookies_file.exists():
                        print("📋 Загружаю cookies после перезапуска парсера...")
                        # В headless режиме просто загружаем cookies без попытки логина
                        if headless:
                            # Загружаем cookies напрямую без проверки авторизации
                            cookies = load_cookies_from_file(str(cookies_file))
                            if cookies:
                                self.parser.driver.get("https://www.pinterest.com")
                                import time
                                time.sleep(2)
                                cookies_set = 0
                                for name, value in cookies.items():
                                    try:
                                        self.parser.driver.add_cookie({
                                            'name': name,
                                            'value': value,
                                            'domain': '.pinterest.com',
                                            'path': '/'
                                        })
                                        cookies_set += 1
                                    except:
                                        pass
                                print(f"  ✓ Установлено {cookies_set} из {len(cookies)} cookies")
                                self.parser.driver.refresh()
                                time.sleep(2)
                                print("✓ Cookies загружены в headless режиме")
                        else:
                            # В видимом режиме используем стандартную проверку
                            self.parser._ensure_authentication()
                except Exception as e:
                    print(f"⚠ Не удалось загрузить cookies: {e}")
                    # Это не критично, продолжаем работу
                
                self.statusBar().showMessage("Парсер перезапущен")
                # Блокируем кнопку парсинга на 10 секунд для инициализации браузера
                self._block_parse_button(10)
                # Обновляем индикатор режима
                self._update_browser_mode_indicator()
                # Обновляем информацию об аккаунте если есть cookies
                cookies_file = get_cookies_path()
                if cookies_file.exists():
                    QTimer.singleShot(500, self.refresh_account_info)
            else:
                self.statusBar().showMessage("Ошибка перезапуска парсера")
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка перезапуска: {e}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось перезапустить парсер: {e}")
    
    
    def load_boards(self):
        """Загружает список досок пользователя"""
        if not self._ensure_parser():
            return
        
        self.refresh_boards_btn.setEnabled(False)
        self.board_combo.clear()
        self.board_combo.addItem("Загрузка досок...")
        
        # Загружаем доски в отдельном потоке
        from PyQt6.QtCore import QThread
        
        class LoadBoardsThread(QThread):
            boards_loaded = pyqtSignal(list)
            error_occurred = pyqtSignal(str)
            
            def __init__(self, parser):
                super().__init__()
                self.parser = parser
            
            def run(self):
                logger.info("LoadBoardsThread: запуск загрузки досок...")
                try:
                    # Сначала пробуем получить доски через pin-creation-tool (самый актуальный способ)
                    logger.debug("LoadBoardsThread: попытка получить доски через pin-creation-tool...")
                    publisher = PinterestPublisher(parser=self.parser)
                    boards = publisher.get_boards_from_creation_tool()
                    
                    if boards:
                        logger.info(f"LoadBoardsThread: получено {len(boards)} досок через pin-creation-tool")
                        # Сохраняем в кэш
                        account_info = self.parser.get_account_info()
                        if account_info:
                            username = account_info.get('username')
                            if username:
                                CacheManager.save_boards(username, boards)
                                logger.debug(f"LoadBoardsThread: доски сохранены в кэш для {username}")
                        self.boards_loaded.emit(boards)
                        logger.info("LoadBoardsThread: сигнал boards_loaded отправлен")
                        return
                    
                    logger.debug("LoadBoardsThread: pin-creation-tool не вернул доски, используем парсер...")
                    # Если не получилось через pin-creation-tool, используем парсер
                    account_info = self.parser.get_account_info()
                    if not account_info:
                        error_msg = "Не удалось получить информацию об аккаунте"
                        logger.error(f"LoadBoardsThread: {error_msg}")
                        self.error_occurred.emit(error_msg)
                        return
                    
                    username = account_info.get('username')
                    if not username:
                        error_msg = "Не удалось определить имя пользователя"
                        logger.error(f"LoadBoardsThread: {error_msg}")
                        self.error_occurred.emit(error_msg)
                        return
                    
                    # Получаем доски из кэша или парсим
                    logger.debug(f"LoadBoardsThread: загрузка досок для {username}...")
                    boards = CacheManager.load_boards(username)
                    if boards is None:
                        logger.debug("LoadBoardsThread: кэш не найден, парсим доски...")
                        boards = self.parser.parse_user_boards(username=username)
                        if boards:
                            CacheManager.save_boards(username, boards)
                            logger.debug(f"LoadBoardsThread: сохранено {len(boards)} досок в кэш")
                    else:
                        logger.debug(f"LoadBoardsThread: использован кэш, найдено {len(boards)} досок")
                    
                    logger.info(f"LoadBoardsThread: загружено {len(boards) if boards else 0} досок")
                    self.boards_loaded.emit(boards or [])
                    logger.info("LoadBoardsThread: сигнал boards_loaded отправлен")
                except Exception as e:
                    logger.error(f"LoadBoardsThread: ошибка: {e}", exc_info=True)
                    self.error_occurred.emit(str(e))
        
        self.load_boards_thread = LoadBoardsThread(self.parser)
        self.load_boards_thread.boards_loaded.connect(self.on_boards_loaded)
        self.load_boards_thread.error_occurred.connect(self.on_boards_error)
        self.load_boards_thread.start()
    
    def on_boards_loaded(self, boards):
        """Обработчик загрузки досок"""
        self.board_combo.clear()
        if boards:
            # Фильтруем доски: исключаем те, что начинаются с нижнего подчеркивания
            filtered_boards = [
                board for board in boards 
                if board.get('board_name', '').strip() and not board.get('board_name', '').startswith('_')
            ]
            
            if filtered_boards:
                for board in filtered_boards:
                    board_name = board.get('board_name', 'Без названия')
                    self.board_combo.addItem(board_name, board)
                self.publish_log.append(f"Загружено досок: {len(filtered_boards)} (отфильтровано {len(boards) - len(filtered_boards)} с подчеркиванием)")
            else:
                self.board_combo.addItem("Нет доступных досок")
                self.publish_log.append("Нет доступных досок (все начинаются с подчеркивания)")
        else:
            self.board_combo.addItem("Доски не найдены")
            self.publish_log.append("Доски не найдены")
        self.refresh_boards_btn.setEnabled(True)
    
    def on_boards_error(self, error: str):
        """Обработчик ошибки загрузки досок"""
        self.board_combo.clear()
        self.board_combo.addItem("Ошибка загрузки")
        self.publish_log.append(f"Ошибка: {error}")
        self.refresh_boards_btn.setEnabled(True)
        if self.toast_manager:
            self.toast_manager.show_error(f"Не удалось загрузить доски: {error}")
    
    def _unique_pins_for_publish(self, pins_data: list) -> Optional[list]:
        """Уникализирует пины перед публикацией"""
        if not self.openrouter_api_key:
            return None
        
        try:
            unique_pins = []
            total = len(pins_data)
            
            for i, pin in enumerate(pins_data, 1):
                title = pin.get('title', '') or ''
                description = pin.get('description', '') or ''
                
                # Уникализируем заголовок
                unique_title = self._unique_text(title, "заголовок")
                # Уникализируем описание
                unique_description = self._unique_text(description, "описание")
                
                # Создаем новый пин с уникализированными данными
                unique_pin = pin.copy()
                unique_pin['title'] = unique_title
                unique_pin['description'] = unique_description
                unique_pins.append(unique_pin)
            
            return unique_pins
        except Exception as e:
            print(f"Ошибка при уникализации: {e}")
            return None
    
    def _unique_text(self, text: str, field_type: str) -> str:
        """Уникализирует текст через OpenRouter API"""
        if not text.strip() or not self.openrouter_api_key:
            return text
        
        prompt = f"""Перепиши следующий {field_type} для Pinterest поста, сделав его уникальным и оригинальным, но сохранив основной смысл и стиль. Используй синонимы и перефразирование. Ответь только переписанным текстом без дополнительных объяснений.

{field_type}: {text}"""
        
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistralai/mistral-nemo",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                },
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            unique_text = result['choices'][0]['message']['content'].strip()
            
            # Подсчитываем токены
            usage = result.get('usage', {})
            total_tokens = usage.get('total_tokens', 0)
            cost_per_1k = 0.0001
            cost = (total_tokens / 1000.0) * cost_per_1k
            self.on_tokens_used(total_tokens, cost)
            
            return unique_text
        except Exception as e:
            print(f"Ошибка уникализации текста: {e}")
            return text
    
    def start_auto_publish(self):
        """Запускает автопубликацию из CSV результатов"""
        if not self._ensure_parser():
            return
        
        # Проверяем что выбран парсинг
        if not self.publish_current_csv_path or not os.path.exists(self.publish_current_csv_path):
            if self.toast_manager:
                self.toast_manager.show_error("Выберите парсинг для публикации")
            return
        
        # Проверяем что выбраны пины
        if not self.publish_selected_pins:
            if self.toast_manager:
                self.toast_manager.show_error("Выберите хотя бы один пин для публикации")
            return
        
        link = self.pin_link_input.text().strip()
        if not link:
            if self.toast_manager:
                self.toast_manager.show_error("Введите ссылку для публикации")
            return
        
        board_index = self.board_combo.currentIndex()
        if board_index < 0:
            if self.toast_manager:
                self.toast_manager.show_error("Выберите доску для публикации")
            return
        
        board_data = self.board_combo.currentData()
        if not board_data:
            if self.toast_manager:
                self.toast_manager.show_error("Не удалось получить информацию о доске")
            return
        
        board_name = board_data.get('board_name', self.board_combo.currentText())
        
        # Получаем выбранные пины
        pins_data = [self.publish_current_pins_data[i] for i in self.publish_selected_pins]
        
        if not pins_data:
            if self.toast_manager:
                self.toast_manager.show_error("Нет выбранных пинов для публикации")
            return
        
        # Проверяем нужно ли уникализировать
        need_unique = self.unique_before_publish_checkbox.isChecked()
        if need_unique:
            if not self.openrouter_api_key:
                QMessageBox.warning(
                    self,
                    "API ключ не указан",
                    "Для уникализации необходим API ключ OpenRouter.\n"
                    "Введите ключ в настройках ИИ API (в сайдбаре)."
                )
                return
            
            # Уникализируем пины
            reply = QMessageBox.question(
                self,
                "Уникализация",
                f"Уникализировать {len(pins_data)} пинов перед публикацией?\n"
                "Это может занять некоторое время.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.publish_log.append(f"Начинается уникализация {len(pins_data)} пинов...")
                unique_pins = self._unique_pins_for_publish(pins_data)
                if unique_pins:
                    pins_data = unique_pins
                    self.publish_log.append("✓ Уникализация завершена")
                else:
                    reply2 = QMessageBox.question(
                        self,
                        "Ошибка уникализации",
                        "Не удалось уникализировать пины. Продолжить публикацию без уникализации?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply2 == QMessageBox.StandardButton.No:
                        return
        
        # Получаем настройки времени
        interval_minutes = self.publish_interval_spin.value()
        start_time_str = self.publish_start_time.text().strip()
        
        # Парсим время начала
        start_delay = 0
        if start_time_str:
            try:
                from datetime import datetime, timedelta, time as dt_time
                start_time = datetime.strptime(start_time_str, "%H:%M").time()
                now = datetime.now().time()
                start_datetime = datetime.combine(datetime.today(), start_time)
                now_datetime = datetime.combine(datetime.today(), now)
                
                if start_time > now:
                    start_delay = (start_datetime - now_datetime).total_seconds()
                else:
                    # Если время уже прошло, начинаем завтра
                    start_datetime = datetime.combine(datetime.today() + timedelta(days=1), start_time)
                    start_delay = (start_datetime - now_datetime).total_seconds()
            except ValueError:
                if self.toast_manager:
                    self.toast_manager.show_error("Неверный формат времени. Используйте HH:MM (например, 09:00)")
            return
        
        # Создаем поток для автопубликации
        class AutoPublishThread(QThread):
            publish_progress = pyqtSignal(str)
            publish_completed = pyqtSignal(bool, str)
            
            def __init__(self, parser, pins_data, link, board_name, interval_minutes=30, start_delay=0):
                super().__init__()
                self.parser = parser
                self.pins_data = pins_data
                self.link = link
                self.board_name = board_name
                self.interval_minutes = interval_minutes
                self.start_delay = start_delay
            
            def run(self):
                logger.info(f"AutoPublishThread: запуск автоматической публикации, пинов: {len(self.pins_data)}, интервал: {self.interval_minutes} мин")
                try:
                    # Ждем время начала если указано
                    if self.start_delay > 0:
                        from datetime import datetime, timedelta
                        start_time = datetime.now() + timedelta(seconds=self.start_delay)
                        logger.info(f"AutoPublishThread: ожидание времени начала: {start_time.strftime('%H:%M:%S')}")
                        self.publish_progress.emit(f"Ожидание времени начала: {start_time.strftime('%H:%M:%S')}")
                        import time
                        time.sleep(self.start_delay)
                        logger.info("AutoPublishThread: время начала наступило, начинаем публикацию...")
                        self.publish_progress.emit("Начало публикации...")
                    
                    # Перехватываем вывод print из create_pin
                    import sys
                    from io import StringIO
                    
                    class PrintCapture:
                        def __init__(self, signal):
                            self.signal = signal
                            self.buffer = StringIO()
                        
                        def write(self, text):
                            if text.strip():
                                self.signal.emit(text.strip())
                            self.buffer.write(text)
                        
                        def flush(self):
                            pass
                    
                    print_capture = PrintCapture(self.publish_progress)
                    old_stdout = sys.stdout
                    
                    logger.debug("AutoPublishThread: инициализация публикатора...")
                    self.publish_progress.emit("Инициализация публикатора...")
                    publisher = PinterestPublisher(parser=self.parser)
                    logger.info("AutoPublishThread: публикатор инициализирован")
                    self.publish_progress.emit("✓ Публикатор инициализирован")
                    
                    total = len(self.pins_data)
                    success_count = 0
                    logger.info(f"AutoPublishThread: всего пинов для публикации: {total}")
                    error_count = 0
                    self.publish_progress.emit(f"Всего пинов для публикации: {total}")
                    
                    # Перехватываем вывод для каждого пина
                    sys.stdout = print_capture
                    
                    try:
                        for i, pin in enumerate(self.pins_data, 1):
                            # Задержка между публикациями (кроме первого)
                            if i > 1:
                                delay_seconds = self.interval_minutes * 60
                                from datetime import datetime, timedelta
                                next_time = datetime.now() + timedelta(seconds=delay_seconds)
                                self.publish_progress.emit(f"\n⏱ Ожидание {self.interval_minutes} минут перед следующей публикацией...")
                                self.publish_progress.emit(f"   Следующая публикация в: {next_time.strftime('%H:%M:%S')}")
                                import time
                                time.sleep(delay_seconds)
                                self.publish_progress.emit("✓ Продолжаем публикацию...")
                            
                            title = pin.get('title', '') or ''
                            description = pin.get('description', '') or ''
                            image_url = pin.get('image_url', '') or ''
                            
                            self.publish_progress.emit(f"\n--- Пин {i}/{total} ---")
                            self.publish_progress.emit(f"URL изображения: {image_url[:80] if image_url else 'НЕТ'}")
                            
                            if not image_url:
                                self.publish_progress.emit(f"Пропуск {i}/{total}: нет изображения")
                                error_count += 1
                                continue
                            
                            # Загружаем изображение
                            self.publish_progress.emit(f"Загрузка изображения {i}/{total}...")
                            image_path = self.download_image(image_url)
                            
                            if not image_path:
                                self.publish_progress.emit(f"Ошибка загрузки изображения {i}/{total}: файл не найден или не загружен")
                                error_count += 1
                                continue
                            
                            self.publish_progress.emit(f"Изображение загружено: {image_path}")
                            
                            # Публикуем пин (используем данные из CSV как есть, без уникализации)
                            self.publish_progress.emit(f"Публикация {i}/{total} в доску '{self.board_name}'...")
                            self.publish_progress.emit(f"  Заголовок: {title[:50] if title else '(пусто)'}")
                            self.publish_progress.emit(f"  Описание: {description[:50] if description else '(пусто)'}")
                            
                            try:
                                # Проверяем что файл существует перед публикацией
                                if not os.path.exists(image_path):
                                    error_count += 1
                                    logger.error(f"AutoPublishThread: файл изображения не существует: {image_path}")
                                    self.publish_progress.emit(f"✗ Файл изображения не существует: {image_path}")
                                    continue
                                
                                # Проверяем размер файла
                                file_size = os.path.getsize(image_path)
                                if file_size == 0:
                                    error_count += 1
                                    logger.error(f"AutoPublishThread: файл изображения пуст: {image_path}")
                                    self.publish_progress.emit(f"✗ Файл изображения пуст: {image_path}")
                                    continue
                                
                                logger.info(f"AutoPublishThread: публикация пина {i}/{total}, размер файла: {file_size} байт")
                                self.publish_progress.emit(f"Публикация пина {i}/{total}...")
                                self.publish_progress.emit(f"  Размер файла: {file_size} байт")
                                
                                success = publisher.create_pin(
                                    image_path=image_path,
                                    title=title or "Без названия",
                                    description=description or "",
                                    link=self.link,
                                    board_name=self.board_name
                                )
                                
                                if success:
                                    success_count += 1
                                    logger.info(f"AutoPublishThread: пин {i}/{total} успешно опубликован")
                                    self.publish_progress.emit(f"✓ Успешно опубликовано {i}/{total}")
                                else:
                                    error_count += 1
                                    logger.warning(f"AutoPublishThread: ошибка публикации {i}/{total} (create_pin вернул False)")
                                    self.publish_progress.emit(f"✗ Ошибка публикации {i}/{total} (create_pin вернул False)")
                                    self.publish_progress.emit(f"  Проверьте логи в консоли для деталей")
                            except Exception as e:
                                error_count += 1
                                error_msg = f"✗ Исключение при публикации {i}/{total}: {str(e)}"
                                logger.error(f"AutoPublishThread: исключение при публикации {i}/{total}: {e}", exc_info=True)
                                self.publish_progress.emit(error_msg)
                                import traceback
                                tb_str = traceback.format_exc()
                                # Показываем только первые строки трейсбека
                                self.publish_progress.emit(f"Детали ошибки: {tb_str[:300]}")
                            
                            # Удаляем временный файл изображения только если это загруженный файл
                            # (не удаляем локальные файлы из папок pinterest_images_*)
                            try:
                                if image_path and os.path.exists(image_path):
                                    # Удаляем только если это временный файл (в temp директории)
                                    import tempfile
                                    temp_dir = tempfile.gettempdir()
                                    if image_path.startswith(temp_dir):
                                        logger.debug(f"AutoPublishThread: удаление временного файла: {image_path}")
                                        os.remove(image_path)
                            except Exception as e:
                                logger.warning(f"AutoPublishThread: ошибка при удалении временного файла: {e}")
                    finally:
                        # Восстанавливаем stdout
                        sys.stdout = old_stdout
                        logger.debug("AutoPublishThread: stdout восстановлен")
                    
                    result_msg = f"Автопубликация завершена. Успешно: {success_count}, Ошибок: {error_count}"
                    logger.info(f"AutoPublishThread: завершено, успешно: {success_count}, ошибок: {error_count}")
                    self.publish_completed.emit(success_count > 0, result_msg)
                except Exception as e:
                    logger.critical(f"AutoPublishThread: критическая ошибка: {e}", exc_info=True)
                    # Восстанавливаем stdout в случае ошибки
                    try:
                        if 'old_stdout' in locals():
                            sys.stdout = old_stdout
                            logger.debug("AutoPublishThread: stdout восстановлен после ошибки")
                    except Exception as e2:
                        logger.error(f"AutoPublishThread: ошибка при восстановлении stdout: {e2}")
                    self.publish_completed.emit(False, f"Ошибка при автопубликации: {str(e)}")
            
            def download_image(self, image_url: str) -> Optional[str]:
                """Загружает изображение по URL или из локального файла"""
                try:
                    # Если это относительный путь, проверяем локальный файл
                    if not image_url.startswith('http://') and not image_url.startswith('https://'):
                        # Это локальный файл - пробуем разные варианты путей
                        possible_paths = [
                            image_url,  # Как есть
                            os.path.join(os.getcwd(), image_url),  # От текущей директории
                            os.path.abspath(image_url),  # Абсолютный путь
                        ]
                        
                        for path in possible_paths:
                            if os.path.exists(path):
                                abs_path = os.path.abspath(path)
                                self.publish_progress.emit(f"  Найден локальный файл: {abs_path}")
                                return abs_path
                        
                        self.publish_progress.emit(f"  Локальный файл не найден: {image_url}")
                        self.publish_progress.emit(f"  Проверенные пути: {possible_paths}")
                        return None
                    
                    # Это URL - загружаем
                    self.publish_progress.emit(f"  Загрузка изображения по URL: {image_url[:80]}...")
                    response = requests.get(image_url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    response.raise_for_status()
                    
                    import tempfile
                    import uuid
                    temp_dir = tempfile.gettempdir()
                    # Определяем расширение из URL или используем .jpg по умолчанию
                    ext = os.path.splitext(image_url)[1] or '.jpg'
                    filename = f"pinterest_pin_{uuid.uuid4().hex[:8]}{ext}"
                    filepath = os.path.join(temp_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    self.publish_progress.emit(f"  Изображение загружено: {filepath} ({os.path.getsize(filepath)} байт)")
                    return filepath
                except Exception as e:
                    self.publish_progress.emit(f"  Ошибка загрузки изображения {image_url}: {str(e)}")
                    import traceback
                    self.publish_progress.emit(f"  Детали: {traceback.format_exc()[:200]}")
                    return None
        
        # Блокируем кнопку и показываем прогресс
        self.start_auto_publish_btn.setEnabled(False)
        self.publish_progress.setVisible(True)
        self.publish_progress.setRange(0, len(pins_data))
        self.publish_progress.setValue(0)
        self.publish_log.clear()
        self.publish_log.append("Начало автопубликации...")
        
        self.auto_publish_thread = AutoPublishThread(
            self.parser,
            pins_data,
            link,
            board_name,
            interval_minutes,
            start_delay
        )
        self.auto_publish_thread.publish_progress.connect(self.on_auto_publish_progress)
        self.auto_publish_thread.publish_completed.connect(self.on_auto_publish_completed)
        self.auto_publish_thread.start()
    
    def on_auto_publish_progress(self, message: str):
        """Обработчик прогресса автопубликации"""
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
        # Обновляем прогресс бар
        if "/" in message:
            try:
                # Ищем паттерн "число/число" в сообщении
                import re
                match = re.search(r'(\d+)/(\d+)', message)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    self.publish_progress.setMaximum(total)
                    self.publish_progress.setValue(current)
            except:
                pass
    
    def on_auto_publish_completed(self, success: bool, message: str):
        """Обработчик завершения автопубликации"""
        self.publish_progress.setVisible(False)
        self.start_auto_publish_btn.setEnabled(True)
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
        
        if success:
            if self.toast_manager:
                self.toast_manager.show_success(message)
        else:
            if self.toast_manager:
                self.toast_manager.show_error(message)
    
    
    def unique_results_csv(self):
        """Уникализирует названия и описания пинов из CSV результатов через OpenRouter API"""
        if not self.csv_file_path or not os.path.exists(self.csv_file_path):
            if self.toast_manager:
                self.toast_manager.show_error("CSV файл результатов не найден. Сначала выполните парсинг.")
            return
        
        # Используем сохраненный API ключ
        api_key = self.openrouter_api_key
        if not api_key:
            QMessageBox.warning(
                self,
                "API ключ не указан",
                "Пожалуйста, введите API ключ OpenRouter в настройках ИИ API (в сайдбаре).\n\n"
                "Рекомендуемая модель: mistralai/mistral-nemo\n"
                "Получить ключ: https://openrouter.ai/keys"
            )
            return
        
        csv_file = self.csv_file_path
        
        # Читаем CSV файл
        try:
            pins_data = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                if self.toast_manager:
                    self.toast_manager.show_error("CSV файл пуст")
                return
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось прочитать CSV файл: {e}")
            return
        
        # Запускаем уникализацию в отдельном потоке
        class UniquePinsThread(QThread):
            progress = pyqtSignal(str)
            completed = pyqtSignal(str)
            error = pyqtSignal(str)
            tokens_used = pyqtSignal(int, float)  # токены, стоимость
            
            def __init__(self, api_key, pins_data, csv_file_path):
                super().__init__()
                self.api_key = api_key
                self.pins_data = pins_data
                self.csv_file_path = csv_file_path
            
            def run(self):
                logger.info(f"UniquePinsThread: запуск уникализации, пинов: {len(self.pins_data)}")
                try:
                    unique_pins = []
                    total = len(self.pins_data)
                    
                    for i, pin in enumerate(self.pins_data, 1):
                        title = pin.get('title', '') or ''
                        description = pin.get('description', '') or ''
                        
                        logger.debug(f"UniquePinsThread: уникализация {i}/{total}: {title[:50]}...")
                        self.progress.emit(f"Уникализация {i}/{total}: {title[:50]}...")
                        
                        # Уникализируем заголовок
                        unique_title = self.unique_text(title, "заголовок")
                        # Уникализируем описание
                        unique_description = self.unique_text(description, "описание")
                        
                        # Создаем новый пин с уникализированными данными
                        unique_pin = pin.copy()
                        unique_pin['title'] = unique_title
                        unique_pin['description'] = unique_description
                        unique_pins.append(unique_pin)
                    
                    logger.info(f"UniquePinsThread: уникализация завершена, сохранение в файл {self.csv_file_path}...")
                    # Перезаписываем исходный файл с уникализированными данными
                    with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as f:
                        if unique_pins:
                            writer = csv.DictWriter(f, fieldnames=unique_pins[0].keys())
                            writer.writeheader()
                            writer.writerows(unique_pins)
                    
                    logger.info(f"UniquePinsThread: файл сохранен, уникализировано {len(unique_pins)} пинов")
                    self.completed.emit(f"Уникализация завершена. Файл {os.path.basename(self.csv_file_path)} обновлен.")
                except Exception as e:
                    logger.error(f"UniquePinsThread: ошибка: {e}", exc_info=True)
                    self.error.emit(str(e))
            
            def unique_text(self, text: str, field_type: str) -> str:
                """Уникализирует текст через OpenRouter API"""
                if not text.strip():
                    logger.debug(f"UniquePinsThread.unique_text: текст пуст для {field_type}, возвращаем как есть")
                    return text
                
                logger.debug(f"UniquePinsThread.unique_text: уникализация {field_type}, длина текста: {len(text)}")
                prompt = f"""Перепиши следующий {field_type} для Pinterest поста, сделав его уникальным и оригинальным, но сохранив основной смысл и стиль. Используй синонимы и перефразирование. Ответь только переписанным текстом без дополнительных объяснений.

{field_type}: {text}"""
                
                try:
                    logger.debug(f"UniquePinsThread.unique_text: отправка запроса к OpenRouter API для {field_type}...")
                    response = requests.post(
                        url="https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "mistralai/mistral-nemo",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ]
                        },
                        timeout=30
                    )
                    response.raise_for_status()
                    result = response.json()
                    unique_text = result['choices'][0]['message']['content'].strip()
                    
                    # Подсчитываем токены и затраты
                    usage = result.get('usage', {})
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)
                    total_tokens = usage.get('total_tokens', prompt_tokens + completion_tokens)
                    
                    # Стоимость для mistralai/mistral-nemo: ~$0.0001 за 1K токенов
                    # Примерная стоимость: $0.0001 за 1K токенов
                    cost_per_1k = 0.0001
                    cost = (total_tokens / 1000.0) * cost_per_1k
                    
                    logger.debug(f"UniquePinsThread.unique_text: {field_type} уникализирован, токены: {total_tokens}, стоимость: ${cost:.6f}")
                    # Отправляем сигнал для обновления счетчика
                    self.tokens_used.emit(total_tokens, cost)
                    
                    return unique_text
                except Exception as e:
                    logger.error(f"UniquePinsThread.unique_text: ошибка при уникализации {field_type}: {e}", exc_info=True)
                    # Если ошибка, возвращаем оригинальный текст
                    return text
        
        # Блокируем кнопку и показываем прогресс
        self.unique_results_btn.setEnabled(False)
        self.statusBar().showMessage("Начало уникализации результатов...")
        
        # Читаем CSV файл
        try:
            pins_data = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                if self.toast_manager:
                    self.toast_manager.show_error("CSV файл пуст")
                self.unique_results_btn.setEnabled(True)
                return
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось прочитать CSV файл: {e}")
            self.unique_results_btn.setEnabled(True)
            return
        
        self.unique_thread = UniquePinsThread(api_key, pins_data, csv_file)
        self.unique_thread.progress.connect(self.on_unique_progress)
        self.unique_thread.completed.connect(self.on_unique_completed)
        self.unique_thread.error.connect(self.on_unique_error)
        self.unique_thread.tokens_used.connect(self.on_tokens_used)
        self.unique_thread.finished.connect(lambda: self.unique_results_btn.setEnabled(True))
        self.unique_thread.start()
    
    def on_unique_progress(self, message: str):
        """Обработчик прогресса уникализации"""
        self.statusBar().showMessage(message)
    
    def on_unique_completed(self, message: str):
        """Обработчик завершения уникализации"""
        self.statusBar().showMessage(message)
        if self.toast_manager:
            self.toast_manager.show_success(message)
        # Обновляем информацию о файле
        if self.csv_file_path:
            self.csv_info_label.setText(f"CSV файл: {os.path.basename(self.csv_file_path)} (уникализирован)")
    
    def export_csv(self):
        """Экспортирует текущий CSV в выбранную пользователем папку"""
        if not self.csv_file_path or not os.path.exists(self.csv_file_path):
            if self.toast_manager:
                self.toast_manager.show_error("CSV файл не найден. Сначала выполните парсинг.")
            return
        default_name = os.path.basename(self.csv_file_path)
        start_dir = str(get_csv_dir())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспортировать CSV",
            os.path.join(start_dir, default_name),
            "CSV файлы (*.csv);;Все файлы (*)"
        )
        if not path:
            return
        try:
            import shutil
            shutil.copy2(self.csv_file_path, path)
            self.statusBar().showMessage(f"Экспортировано: {path}")
            if self.toast_manager:
                self.toast_manager.show_success(f"CSV сохранен:\n{path}")
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось экспортировать CSV: {e}")
    
    def on_unique_error(self, error: str):
        """Обработчик ошибки уникализации"""
        self.statusBar().showMessage(f"Ошибка: {error}")
        if self.toast_manager:
            self.toast_manager.show_error(f"Ошибка при уникализации: {error}")
    
    def _apply_filters(self):
        """Применяет фильтры и сортировку к отображаемым пинам"""
        if not hasattr(self, 'parsed_pins') or not self.parsed_pins:
            return
        
        try:
            # Получаем поисковый запрос
            search_text = ""
            if hasattr(self, 'filter_search_input'):
                search_text = self.filter_search_input.text().strip().lower()
            
            # Фильтруем пины
            filtered_pins = self.parsed_pins.copy()
            if search_text:
                filtered_pins = [
                    pin for pin in filtered_pins
                    if search_text in (pin.get('title', '') or '').lower() or
                       search_text in (pin.get('author', '') or '').lower()
                ]
            
            # Сортируем
            if hasattr(self, 'sort_combo'):
                sort_index = self.sort_combo.currentIndex()
                if sort_index == 0:  # По дате (новые)
                    filtered_pins = sorted(filtered_pins, key=lambda x: x.get('timestamp', ''), reverse=True)
                elif sort_index == 1:  # По дате (старые)
                    filtered_pins = sorted(filtered_pins, key=lambda x: x.get('timestamp', ''))
                elif sort_index == 2:  # По названию (А-Я)
                    filtered_pins = sorted(filtered_pins, key=lambda x: (x.get('title', '') or '').lower())
                elif sort_index == 3:  # По названию (Я-А)
                    filtered_pins = sorted(filtered_pins, key=lambda x: (x.get('title', '') or '').lower(), reverse=True)
                elif sort_index == 4:  # По автору (А-Я)
                    filtered_pins = sorted(filtered_pins, key=lambda x: (x.get('author', '') or '').lower())
                elif sort_index == 5:  # По автору (Я-А)
                    filtered_pins = sorted(filtered_pins, key=lambda x: (x.get('author', '') or '').lower(), reverse=True)
            
            # Обновляем отображение
            if hasattr(self, 'pin_grid'):
                self.pin_grid.display_pins(filtered_pins)
            
            logger.debug(f"_apply_filters: отфильтровано {len(filtered_pins)} из {len(self.parsed_pins)} пинов")
        except Exception as e:
            logger.error(f"_apply_filters: ошибка при применении фильтров: {e}", exc_info=True)
    
    def import_csv(self):
        """Импортирует CSV файл для работы"""
        try:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Импортировать CSV",
                str(get_csv_dir()),
                "CSV файлы (*.csv);;Все файлы (*)"
            )
            if not path:
                return
            
            # Загружаем данные из CSV
            pins_data = []
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                if self.toast_manager:
                    self.toast_manager.show_error("CSV файл пуст")
                return
            
            # Сохраняем данные
            self.parsed_pins = pins_data
            self.csv_file_path = path
            
            # Обновляем интерфейс
            if hasattr(self, 'pin_grid'):
                self.pin_grid.display_pins(pins_data)
            
            if hasattr(self, 'csv_info_label'):
                self.csv_info_label.setText(f"Импортировано пинов: {len(pins_data)} | Файл: {os.path.basename(path)}")
                self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
            
            if hasattr(self, 'unique_results_btn'):
                self.unique_results_btn.setEnabled(True)
            if hasattr(self, 'export_csv_btn'):
                self.export_csv_btn.setEnabled(True)
            if hasattr(self, 'export_json_btn'):
                self.export_json_btn.setEnabled(True)
            if hasattr(self, 'export_excel_btn'):
                self.export_excel_btn.setEnabled(True)
            
            self.statusBar().showMessage(f"Импортировано {len(pins_data)} пинов из {os.path.basename(path)}")
            if self.toast_manager:
                self.toast_manager.show_success(f"Импортировано {len(pins_data)} пинов")
            
            logger.info(f"import_csv: импортировано {len(pins_data)} пинов из {path}")
        except Exception as e:
            logger.error(f"import_csv: ошибка при импорте CSV: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при импорте CSV: {e}")
    
    def export_to_json(self):
        """Экспортирует текущие пины в JSON"""
        if not self.parsed_pins:
            if self.toast_manager:
                self.toast_manager.show_error("Нет данных для экспорта")
            return
        
        try:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Экспортировать в JSON",
                str(get_csv_dir()),
                "JSON файлы (*.json);;Все файлы (*)"
            )
            if not path:
                return
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.parsed_pins, f, indent=2, ensure_ascii=False)
            
            self.statusBar().showMessage(f"Экспортировано в JSON: {path}")
            if self.toast_manager:
                self.toast_manager.show_success(f"Экспортировано в JSON:\n{path}")
            logger.info(f"export_to_json: экспортировано {len(self.parsed_pins)} пинов в {path}")
        except Exception as e:
            logger.error(f"export_to_json: ошибка: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при экспорте в JSON: {e}")
    
    def export_to_excel(self):
        """Экспортирует текущие пины в Excel"""
        if not self.parsed_pins:
            if self.toast_manager:
                self.toast_manager.show_error("Нет данных для экспорта")
            return
        
        try:
            # Проверяем наличие openpyxl
            try:
                import openpyxl
            except ImportError:
                if self.toast_manager:
                    self.toast_manager.show_error("Для экспорта в Excel требуется библиотека openpyxl.\nУстановите: pip install openpyxl")
                return
            
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Экспортировать в Excel",
                str(get_csv_dir()),
                "Excel файлы (*.xlsx);;Все файлы (*)"
            )
            if not path:
                return
            
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Pins"
            
            # Заголовки
            if self.parsed_pins:
                headers = list(self.parsed_pins[0].keys())
                ws.append(headers)
                
                # Данные
                for pin in self.parsed_pins:
                    row = [pin.get(header, '') for header in headers]
                    ws.append(row)
            
            wb.save(path)
            
            self.statusBar().showMessage(f"Экспортировано в Excel: {path}")
            if self.toast_manager:
                self.toast_manager.show_success(f"Экспортировано в Excel:\n{path}")
            logger.info(f"export_to_excel: экспортировано {len(self.parsed_pins)} пинов в {path}")
        except Exception as e:
            logger.error(f"export_to_excel: ошибка: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при экспорте в Excel: {e}")
    
    def backup_data(self):
        """Создает резервную копию данных (конфиг, cookies, история)"""
        try:
            backup_dir = QFileDialog.getExistingDirectory(
                self,
                "Выберите папку для резервной копии",
                str(get_csv_dir().parent)
            )
            if not backup_dir:
                return
            
            import shutil
            from datetime import datetime
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_subdir = os.path.join(backup_dir, f"PinMaster_backup_{timestamp}")
            os.makedirs(backup_subdir, exist_ok=True)
            
            # Копируем файлы
            files_to_backup = [
                (get_config_path(), "config.json"),
                (get_cookies_path(), "pinterest_cookies.json"),
                (get_parsing_history_path(), "parsing_history.json"),
            ]
            
            backed_up = []
            for file_path, name in files_to_backup:
                if file_path.exists():
                    dest = os.path.join(backup_subdir, name)
                    shutil.copy2(file_path, dest)
                    backed_up.append(name)
            
            if backed_up:
                self.statusBar().showMessage(f"Резервная копия создана: {backup_subdir}")
                if self.toast_manager:
                    self.toast_manager.show_success(f"Резервная копия создана:\n{backup_subdir}\n\nФайлы: {', '.join(backed_up)}")
                logger.info(f"backup_data: создана резервная копия в {backup_subdir}")
            else:
                if self.toast_manager:
                    self.toast_manager.show_warning("Нет файлов для резервного копирования")
        except Exception as e:
            logger.error(f"backup_data: ошибка: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при создании резервной копии: {e}")
    
    def restore_data(self):
        """Восстанавливает данные из резервной копии"""
        try:
            backup_dir = QFileDialog.getExistingDirectory(
                self,
                "Выберите папку с резервной копией",
                str(get_csv_dir().parent)
            )
            if not backup_dir:
                return
            
            # Ищем файлы резервной копии
            files_to_restore = {
                "config.json": get_config_path(),
                "pinterest_cookies.json": get_cookies_path(),
                "parsing_history.json": get_parsing_history_path(),
            }
            
            restored = []
            import shutil
            for backup_name, dest_path in files_to_restore.items():
                backup_path = os.path.join(backup_dir, backup_name)
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, dest_path)
                    restored.append(backup_name)
            
            if restored:
                # Перезагружаем конфиг
                self.load_config()
                self._load_parsing_history()
                
                self.statusBar().showMessage(f"Восстановлено файлов: {len(restored)}")
                if self.toast_manager:
                    self.toast_manager.show_success(f"Восстановлено файлов: {len(restored)}\n\n{', '.join(restored)}")
                logger.info(f"restore_data: восстановлено {len(restored)} файлов из {backup_dir}")
            else:
                if self.toast_manager:
                    self.toast_manager.show_warning("Файлы резервной копии не найдены")
        except Exception as e:
            logger.error(f"restore_data: ошибка: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при восстановлении: {e}")
    
    def _clear_cache(self):
        """Очищает кэш данных"""
        try:
            reply = QMessageBox.question(
                self,
                "Очистить кэш",
                "Вы уверены, что хотите очистить весь кэш?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                CacheManager.clear_cache()
                self.statusBar().showMessage("Кэш очищен")
                if self.toast_manager:
                    self.toast_manager.show_success("Кэш очищен")
                logger.info("_clear_cache: кэш очищен")
        except Exception as e:
            logger.error(f"_clear_cache: ошибка: {e}", exc_info=True)
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка при очистке кэша: {e}")
    
    def on_tokens_used(self, tokens: int, cost: float):
        """Обработчик использования токенов"""
        self.ai_tokens_used += tokens
        self.ai_cost += cost
        self._update_ai_tokens_display()
        self._save_ai_stats()
    
    def _save_parsing_to_history(self, query: str, pins_count: int, csv_path: str, date: str):
        """Сохраняет информацию о парсинге в историю"""
        try:
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            if date not in history:
                history[date] = []
            
            from datetime import datetime
            entry = {
                'query': query,
                'pins_count': pins_count,
                'csv_path': csv_path,
                'timestamp': datetime.now().isoformat(),
                'time': datetime.now().strftime("%H:%M:%S")
            }
            
            history[date].append(entry)
            
            # Сохраняем только последние 100 записей на дату
            if len(history[date]) > 100:
                history[date] = history[date][-100:]
            
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            
            # Обновляем UI
            self._load_parsing_history()
        except Exception as e:
            print(f"Ошибка при сохранении истории парсинга: {e}")
    
    def _load_parsing_history(self):
        """Загружает историю парсингов и обновляет UI"""
        logger.debug("_load_parsing_history: начало загрузки истории...")
        try:
            if not hasattr(self, 'history_date_combo'):
                logger.warning("_load_parsing_history: history_date_combo не найден, пропускаем загрузку")
                return
            
            logger.debug("_load_parsing_history: чтение файла истории...")
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                logger.debug(f"_load_parsing_history: история загружена, дат: {len(history)}")
            else:
                logger.debug("_load_parsing_history: файл истории не существует")
            
            # Обновляем список дат
            logger.debug("_load_parsing_history: обновление списка дат...")
            self.history_date_combo.clear()
            dates = sorted(history.keys(), reverse=True)  # Новые даты первыми
            if dates:
                logger.debug(f"_load_parsing_history: добавление {len(dates)} дат в комбобокс...")
                self.history_date_combo.addItems(dates)
                # Выбираем последнюю дату
                self.history_date_combo.setCurrentIndex(0)
                logger.debug(f"_load_parsing_history: обновление списка парсингов для даты {dates[0]}...")
                self._update_history_list(dates[0], history.get(dates[0], []))
            else:
                logger.debug("_load_parsing_history: нет дат, добавляем заглушку")
                self.history_date_combo.addItem("Нет парсингов")
                if hasattr(self, 'history_list'):
                    self.history_list.clear()
            logger.debug("_load_parsing_history: загрузка истории завершена успешно")
        except Exception as e:
            logger.error(f"_load_parsing_history: ошибка при загрузке истории парсинга: {e}", exc_info=True)
            print(f"Ошибка при загрузке истории парсинга: {e}")
    
    def _update_history_list(self, date: str, entries: list):
        """Обновляет список парсингов для выбранной даты"""
        logger.debug(f"_update_history_list: обновление списка для даты {date}, записей: {len(entries)}")
        try:
            if not hasattr(self, 'history_list'):
                logger.warning("_update_history_list: history_list не найден")
                return
            
            # Сохраняем все записи для фильтрации
            self._all_history_entries = entries.copy()
            
            # Применяем фильтр
            self._filter_history()
            logger.debug(f"_update_history_list: добавлено {len(entries)} элементов в список")
        except Exception as e:
            logger.error(f"_update_history_list: ошибка при обновлении списка: {e}", exc_info=True)
    
    def _filter_history(self):
        """Фильтрует историю парсингов по поисковому запросу"""
        if not hasattr(self, 'history_list') or not hasattr(self, '_all_history_entries'):
            return
        
        try:
            search_text = ""
            if hasattr(self, 'history_search_input'):
                search_text = self.history_search_input.text().strip().lower()
            
            self.history_list.clear()
            
            # Фильтруем записи
            filtered_entries = self._all_history_entries
            if search_text:
                filtered_entries = [
                    entry for entry in self._all_history_entries
                    if search_text in (entry.get('query', '') or '').lower()
                ]
            
            # Добавляем отфильтрованные записи
            for entry in reversed(filtered_entries):  # Новые первыми
                query = entry.get('query', 'Неизвестно')
                pins_count = entry.get('pins_count', 0)
                time = entry.get('time', '')
                item_text = f"{time} | {query} | {pins_count} пинов"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, entry)  # Сохраняем данные
                self.history_list.addItem(item)
            
            logger.debug(f"_filter_history: отфильтровано {len(filtered_entries)} из {len(self._all_history_entries)} записей")
        except Exception as e:
            logger.error(f"_filter_history: ошибка при фильтрации истории: {e}", exc_info=True)
    
    def on_history_date_changed(self, date: str):
        """Обработчик изменения даты в истории"""
        if not date or date == "Нет парсингов":
            if hasattr(self, 'history_list'):
                self.history_list.clear()
            return
        
        try:
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            entries = history.get(date, [])
            self._update_history_list(date, entries)
        except Exception as e:
            print(f"Ошибка при загрузке парсингов за дату: {e}")
    
    def _load_parsing_from_entry(self, entry: dict):
        """Загружает парсинг из записи истории"""
        logger.debug(f"_load_parsing_from_entry: загрузка парсинга из записи...")
        try:
            csv_path = entry.get('csv_path', '')
            if not csv_path or not os.path.exists(csv_path):
                logger.warning(f"_load_parsing_from_entry: CSV файл не найден: {csv_path}")
                return False
            
            # Загружаем данные из CSV
            logger.debug(f"_load_parsing_from_entry: чтение CSV файла {csv_path}...")
            pins_data = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                logger.warning(f"_load_parsing_from_entry: CSV файл пуст")
                return False
            
            logger.debug(f"_load_parsing_from_entry: загружено {len(pins_data)} пинов")
            # Обновляем интерфейс
            self.parsed_pins = pins_data
            self.csv_file_path = csv_path
            
            # Обновляем сетку пинов
            if hasattr(self, 'pin_grid'):
                try:
                    logger.debug("_load_parsing_from_entry: обновление сетки пинов...")
                    self.pin_grid.display_pins(pins_data)
                    logger.debug("_load_parsing_from_entry: сетка пинов обновлена")
                except Exception as e:
                    logger.error(f"_load_parsing_from_entry: ошибка при обновлении сетки пинов: {e}", exc_info=True)
            
            query = entry.get('query', 'Неизвестно')
            pins_count = entry.get('pins_count', len(pins_data))
            time = entry.get('time', '')
            
            # Обновляем информацию о CSV
            if hasattr(self, 'csv_info_label'):
                try:
                    self.csv_info_label.setText(f"Найдено пинов: {pins_count} | CSV файл: {os.path.basename(csv_path)}")
                    self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
                except Exception as e:
                    logger.error(f"_load_parsing_from_entry: ошибка при обновлении csv_info_label: {e}", exc_info=True)
            
            # Включаем кнопки
            if hasattr(self, 'unique_results_btn'):
                try:
                    self.unique_results_btn.setEnabled(True)
                except Exception as e:
                    logger.error(f"_load_parsing_from_entry: ошибка при включении unique_results_btn: {e}", exc_info=True)
            
            if hasattr(self, 'export_csv_btn'):
                try:
                    self.export_csv_btn.setEnabled(True)
                except Exception as e:
                    logger.error(f"_load_parsing_from_entry: ошибка при включении export_csv_btn: {e}", exc_info=True)
            
            logger.debug("_load_parsing_from_entry: загрузка парсинга завершена успешно")
            return True
        except Exception as e:
            logger.error(f"_load_parsing_from_entry: ошибка при загрузке парсинга: {e}", exc_info=True)
            print(f"Ошибка при загрузке парсинга: {e}")
            return False
    
    def _load_last_parsing(self):
        """Загружает последний парсинг при запуске"""
        try:
            history_path = get_parsing_history_path()
            if not history_path.exists():
                return
            
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            # Находим последнюю дату и последний парсинг
            dates = sorted(history.keys(), reverse=True)
            if not dates:
                return
            
            last_date = dates[0]
            entries = history.get(last_date, [])
            if not entries:
                return
            
            # Берем последний парсинг
            last_entry = entries[-1]
            if self._load_parsing_from_entry(last_entry):
                self.statusBar().showMessage(f"Загружен последний парсинг: {last_entry.get('query', '')}")
        except Exception as e:
            print(f"Ошибка при загрузке последнего парсинга: {e}")
    
    def on_history_item_selected(self, item: QListWidgetItem):
        """Обработчик выбора парсинга из истории"""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        
        if not self._load_parsing_from_entry(entry):
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось загрузить парсинг")
            return
        
        query = entry.get('query', 'Неизвестно')
        pins_count = entry.get('pins_count', 0)
        
        # Переключаемся на страницу результатов
        self.show_page("results")
        
        self.statusBar().showMessage(f"Загружен парсинг: {query} ({pins_count} пинов)")
    
    def _load_publish_history(self):
        """Загружает историю парсингов для вкладки автопубликации"""
        try:
            if not hasattr(self, 'publish_date_combo'):
                return
            
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            # Обновляем список дат
            self.publish_date_combo.clear()
            dates = sorted(history.keys(), reverse=True)  # Новые даты первыми
            if dates:
                self.publish_date_combo.addItems(dates)
                # Выбираем последнюю дату
                self.publish_date_combo.setCurrentIndex(0)
                self.on_publish_date_changed(dates[0])
            else:
                self.publish_date_combo.addItem("Нет парсингов")
                self.publish_parsing_combo.clear()
                self.publish_parsing_info.setText("Нет доступных парсингов")
        except Exception as e:
            print(f"Ошибка при загрузке истории для публикации: {e}")
    
    def on_publish_date_changed(self, date: str):
        """Обработчик изменения даты в автопубликации"""
        if not date or date == "Нет парсингов":
            self.publish_parsing_combo.clear()
            self.publish_parsing_info.setText("Выберите дату")
            return
        
        try:
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            entries = history.get(date, [])
            self.publish_parsing_combo.clear()
            
            for entry in reversed(entries):  # Новые первыми
                query = entry.get('query', 'Неизвестно')
                pins_count = entry.get('pins_count', 0)
                time = entry.get('time', '')
                display_text = f"{time} | {query} | {pins_count} пинов"
                self.publish_parsing_combo.addItem(display_text, entry)
            
            if entries:
                self.publish_parsing_combo.setCurrentIndex(0)
                self.on_publish_parsing_changed(0)
            else:
                self.publish_parsing_info.setText("Нет парсингов за эту дату")
        except Exception as e:
            print(f"Ошибка при загрузке парсингов за дату: {e}")
    
    def on_publish_parsing_changed(self, index: int):
        """Обработчик изменения выбранного парсинга"""
        try:
            # Проверяем, что index - это число
            if not isinstance(index, int):
                logger.warning(f"on_publish_parsing_changed: получен неверный тип индекса: {type(index)}, значение: {index}")
                return
            if index < 0:
                return
            
            entry = self.publish_parsing_combo.itemData(index)
            if not entry:
                return
            
            csv_path = entry.get('csv_path', '')
            if not csv_path or not os.path.exists(csv_path):
                self.publish_parsing_info.setText("CSV файл не найден")
                return
            
            # Загружаем пины из CSV
            pins_data = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                self.publish_parsing_info.setText("CSV файл пуст")
                return
            
            self.publish_current_csv_path = csv_path
            self.publish_current_pins_data = pins_data
            
            # Обновляем информацию
            query = entry.get('query', 'Неизвестно')
            pins_count = entry.get('pins_count', len(pins_data))
            time = entry.get('time', '')
            self.publish_parsing_info.setText(f"Запрос: {query} | Пинов: {pins_count} | Время: {time}")
            
            # Заполняем список пинов с чекбоксами
            self._load_pins_to_list(pins_data)
        except Exception as e:
            self.publish_parsing_info.setText(f"Ошибка загрузки: {e}")
            print(f"Ошибка при загрузке пинов: {e}")
    
    def _load_pins_to_list(self, pins_data: list):
        """Загружает пины в список с чекбоксами"""
        self.pins_list_widget.clear()
        self.publish_selected_pins = []
        
        for i, pin in enumerate(pins_data):
            title = pin.get('title', 'Без названия') or 'Без названия'
            if len(title) > 60:
                title = title[:57] + "..."
            
            item = QListWidgetItem(f"{i+1}. {title}")
            item.setCheckState(Qt.CheckState.Checked)  # По умолчанию все выбраны
            item.setData(Qt.ItemDataRole.UserRole, i)  # Сохраняем индекс
            self.pins_list_widget.addItem(item)
            self.publish_selected_pins.append(i)
        
        # Подключаем обработчик изменения состояния чекбоксов
        self.pins_list_widget.itemChanged.connect(self._on_pin_item_changed)
        self._update_selected_pins_count()
    
    def _on_pin_item_changed(self, item: QListWidgetItem):
        """Обработчик изменения состояния чекбокса пина"""
        self._update_selected_pins_count()
    
    def _select_pins(self, select_all: bool):
        """Выбирает или снимает выбор со всех пинов"""
        # Временно отключаем сигнал чтобы не вызывать обновление для каждого элемента
        self.pins_list_widget.itemChanged.disconnect()
        
        for i in range(self.pins_list_widget.count()):
            item = self.pins_list_widget.item(i)
            if select_all:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
        
        # Включаем сигнал обратно
        self.pins_list_widget.itemChanged.connect(self._on_pin_item_changed)
        self._update_selected_pins_count()
    
    def _update_selected_pins_count(self):
        """Обновляет счетчик выбранных пинов"""
        selected_count = 0
        self.publish_selected_pins = []
        
        for i in range(self.pins_list_widget.count()):
            item = self.pins_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_count += 1
                pin_index = item.data(Qt.ItemDataRole.UserRole)
                self.publish_selected_pins.append(pin_index)
        
        self.selected_pins_count_label.setText(f"Выбрано: {selected_count}")
    


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    import traceback
    
    logger.info("=" * 80)
    logger.info("ТОЧКА ВХОДА: Запуск приложения")
    logger.info("=" * 80)
    
    try:
        logger.info("Создание QApplication...")
        app = QApplication(sys.argv)
        logger.info("QApplication создан успешно")
        
        logger.info("Создание PinterestMainWindow...")
        window = PinterestMainWindow()
        logger.info("PinterestMainWindow создан успешно")
        
        logger.info("Отображение окна...")
        window.show()
        logger.info("Окно отображено, запуск event loop...")
        
        exit_code = app.exec()
        logger.info(f"Event loop завершен с кодом: {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Приложение прервано пользователем (KeyboardInterrupt)")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при запуске приложения: {e}", exc_info=True)
        print(f"Критическая ошибка при запуске приложения: {e}")
        traceback.print_exc()
        # Показываем диалог с ошибкой если возможно
        try:
            from PyQt6.QtWidgets import QMessageBox
            logger.debug("Попытка показать диалог с ошибкой...")
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Ошибка запуска")
            msg.setText(f"Не удалось запустить приложение:\n{str(e)}")
            msg.setDetailedText(traceback.format_exc())
            msg.exec()
            logger.debug("Диалог с ошибкой показан")
        except Exception as e2:
            logger.critical(f"Не удалось показать диалог с ошибкой: {e2}", exc_info=True)
        sys.exit(1)
