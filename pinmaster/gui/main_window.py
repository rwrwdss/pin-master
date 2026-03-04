"""
Главное окно Qt-приложения для парсера Pinterest.
Информация об аккаунте отображается в главном меню/окне.
"""

# Версия и сборка приложения (синхронизировать с build_macos_installer.py при релизе)
APP_VERSION = "1.0.0"
APP_BUILD = "20250204"

import csv
import json
import logging
import os
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QEvent, QFile, Qt, QThread, QTimer, QTextStream, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsBlurEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    import pinmaster.browser.webdriver_patch  # noqa: F401
except ImportError as e:
    logging.getLogger("PinMaster").warning("webdriver_patch не найден: %s", e)

import requests

from pinmaster.utils.cache import CacheManager
from pinmaster.utils.paths import (
    get_accounts_dir,
    get_config_path,
    get_cookies_path,
    get_csv_dir,
    get_logs_dir,
    get_parsing_history_path,
    get_playwright_profile_dir,
    get_results_csv_path,
    get_unique_results_csv_path,
    get_styles_path,
    get_app_name,
    get_user_data_dir,
    is_frozen,
)
from pinmaster.pinterest.publisher import PinterestPublisher
from pinmaster.pinterest.selenium_parser import PinterestSeleniumParser
from pinmaster.gui.status_indicator import StatusIndicator
from pinmaster.gui.toast_notification import ToastManager

try:
    from pinmaster.pinterest.board_scraper import get_boards as board_scraper_get_boards
    BOARD_SCRAPER_AVAILABLE = True
except ImportError:
    board_scraper_get_boards = None
    BOARD_SCRAPER_AVAILABLE = False

MAX_ACCOUNTS = 10  # Максимум аккаунтов (цикл автопостинга, загрузка досок — без хардкода)

# Настройка логирования
logger = logging.getLogger('PinMaster')
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

log_file = str(get_logs_dir() / "pinmaster.log")
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

logger.info("=" * 80)
logger.info("ЗАПУСК ПРИЛОЖЕНИЯ PINMASTER")
logger.info("=" * 80)


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
            
            # Заголовок (учитываем title и Title из CSV)
            title = (self.pin_data.get('title') or self.pin_data.get('Title') or '').strip() or 'Без названия'
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
                except Exception:
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
            logger.debug(f"PinGridWidget.display_pins: создание карточек в сетке {columns} колонок, всего {len(pins)}...")
            for i, pin in enumerate(pins):
                try:
                    row = i // columns
                    col = i % columns
                    card = PinCardWidget(pin)
                    self.grid_layout.addWidget(card, row, col)
                except Exception as e:
                    logger.error(f"PinGridWidget.display_pins: ошибка при создании карточки {i+1}: {e}", exc_info=True)
                    continue
            
            logger.debug(f"PinGridWidget.display_pins: отображение завершено, создано карточек: {self.grid_layout.count()}")
        except Exception as e:
            logger.critical(f"PinGridWidget.display_pins: критическая ошибка при отображении пинов: {e}", exc_info=True)


class AccountInfoThread(QThread):
    """Поток для получения базовой информации об аккаунте (username, URL). Доски/пины не грузим при инициализации."""
    
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
            
            # При инициализации только текущий аккаунт — доски и пины не грузим (чтобы не подвисало GUI).
            # Доски грузятся по кнопке ↻ на странице Публикация для каждого аккаунта.
            account_info['boards_count'] = "—"
            account_info['boards'] = []
            account_info['pins_count'] = "—"
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
    
    def __init__(self, enable_login: bool, headless: bool, download_images: bool, cookies_file: Optional[str] = None):
        super().__init__()
        self.enable_login = enable_login
        self.headless = headless
        self.download_images = download_images
        self.cookies_file = cookies_file  # путь к файлу cookies (для добавления аккаунта)
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
            logger.info("ParserInitThread: создание PinterestSeleniumParser...")
            print("Создание PinterestSeleniumParser...")
            parser = PinterestSeleniumParser(
                cookies_file=self.cookies_file,
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
            logger.debug("SearchParseThread: начинаем парсинг страницы поиска...")
            
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
            self.last_parsing_query: str = ""  # Запрос последнего парсинга (для уникализации пустых пинов)
            self.openrouter_api_key: Optional[str] = None  # API ключ OpenRouter
            self.ai_tokens_used: int = 0  # Счетчик использованных токенов
            self.ai_cost: float = 0.0  # Счетчик затрат в долларах
            self.tray_icon: Optional[QSystemTrayIcon] = None
            self.toast_manager: Optional[ToastManager] = None  # Менеджер уведомлений
            self.accounts: List[Dict] = []  # До 10 аккаунтов: [{"id": "1", "name": "...", "cookies_file": "..."}]
            self._cached_boards: Dict[str, list] = {}  # account_id -> [boards], кэш досок при старте
            self._pending_auto_publish: bool = False  # если True — ждём готовности парсера для автопостинга
            self._pending_parse: bool = False  # если True — ждём готовности парсера для парсинга (нажали «Парсить»)
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
        # На macOS app.setStyleSheet не всегда доходит до виджетов — задаём стили сайдбару явно
        sidebar_widget.setStyleSheet("""
            QWidget#sidebar {
                background-color: #f0f0f0;
                border-right: 2px solid #e0e0e0;
                min-width: 260px;
            }
            QLabel#sidebarTitle {
                font-size: 11px;
                font-weight: 600;
                color: #666666;
                padding: 6px 0;
            }
            QPushButton#sidebarButton {
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 10px 14px;
                border-radius: 6px;
                color: #1a1a1a;
                font-weight: 400;
            }
            QPushButton#sidebarButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton#sidebarButton:pressed {
                background-color: #d0d0d0;
            }
            QPushButton#sidebarButton:checked {
                background-color: #000000;
                color: #ffffff;
                font-weight: 600;
                border-left: 3px solid #ffffff;
            }
        """)
        # Настраиваем sizePolicy для адаптации по вертикали
        sidebar_size_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sidebar_widget.setSizePolicy(sidebar_size_policy)
        sidebar_layout = QVBoxLayout()
        # Apple HIG–подобные отступы сайдбара (16px)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(8)
        
        # Заголовок сайдбара — стили только через QSS (QLabel#sidebarTitle)
        sidebar_title = QLabel("Навигация")
        sidebar_title.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(sidebar_title, 0)  # Не растягивается
        
        # === БЛОК: НАВИГАЦИЯ (QWidget вместо QGroupBox — без лишних margins/title) ===
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 8, 0, 0)
        nav_layout.setSpacing(4)
        
        # Кнопки навигации
        self.parse_btn = QPushButton("Парсинг")
        self.parse_btn.setObjectName("sidebarButton")
        self.parse_btn.setCheckable(True)
        self.parse_btn.setChecked(True)
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
        
        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.setObjectName("sidebarButton")
        self.settings_btn.setCheckable(True)
        self.settings_btn.clicked.connect(lambda: self.show_page("settings"))
        nav_layout.addWidget(self.settings_btn)
        
        sidebar_layout.addWidget(nav_container, 0)  # Не растягивается
        
        # Добавляем stretch в конце для заполнения пространства при увеличении высоты окна
        sidebar_layout.addStretch(1)  # Растягивается для заполнения вертикального пространства
        
        sidebar_widget.setLayout(sidebar_layout)
        main_splitter.addWidget(sidebar_widget)
        
        # === ЦЕНТРАЛЬНАЯ ОБЛАСТЬ ===
        # Используем QStackedWidget для правильного переключения страниц без наложений
        self.pages_stack = QStackedWidget()
        self.pages_stack.setObjectName("centralArea")
        
        # Виджет инфо об аккаунте (используется после входа в Настройках, в стек не добавляем)
        self.account_page = QWidget()
        account_layout = self._create_layout('vbox', 'large', 'xlarge')
        self.account_info_widget = AccountInfoWidget()
        account_layout.addWidget(self.account_info_widget, 0)
        account_layout.addStretch(1)
        self.account_page.setLayout(account_layout)
        # Страница «Аккаунт» убрана из навигации — вход только через Настройки

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
        self.pins_count_spin.setMaximum(5000)
        self.pins_count_spin.setValue(20)
        self.pins_count_spin.setToolTip("До 5000 пинов. Большие объёмы (500+) сохраняются в CSV без превью карточек.")
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
        
        # История парсингов (один список без выбора даты)
        history_group = QGroupBox("История")
        history_layout = self._create_layout('vbox', top_margin='medium', spacing='medium')
        
        # Список всех парсингов (один выбор — для удаления; контекстное меню по правому клику)
        self.history_list = QListWidget()
        self.history_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.history_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.history_list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectItems)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._show_history_list_context_menu)
        self.history_list.itemClicked.connect(self.on_history_item_selected)
        history_layout.addWidget(self.history_list)
        
        # Кнопка удаления выбранного парсинга из истории
        self.delete_history_btn = QPushButton("Удалить выбранный результат")
        self.delete_history_btn.setObjectName("compactButton")
        self.delete_history_btn.clicked.connect(self._delete_selected_history_entry)
        self.delete_history_btn.setToolTip("Удалить выбранную запись из списка истории")
        history_layout.addWidget(self.delete_history_btn)
        
        history_group.setLayout(history_layout)
        results_group_layout.addWidget(history_group)
        
        # Информация о CSV и кнопка Импорт в одной строке
        self.csv_info_label = QLabel("CSV не создан")
        self.csv_info_label.setStyleSheet("color: #666666; font-size: 10px;")
        csv_row = self._create_layout('hbox', spacing='medium')
        csv_row.addWidget(self.csv_info_label)
        csv_row.addStretch()
        self.import_csv_btn = QPushButton("Импорт")
        self.import_csv_btn.setObjectName("compactButton")
        self.import_csv_btn.clicked.connect(self.import_csv)
        self.import_csv_btn.setToolTip("Импортировать CSV файл")
        csv_row.addWidget(self.import_csv_btn)
        results_group_layout.addLayout(csv_row)
        
        # Расположение файла результата и кнопка «Открыть в Finder»
        self.results_path_label = QLabel("Расположение: не выбрано")
        self.results_path_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.results_path_label.setWordWrap(True)
        path_row = self._create_layout('hbox', spacing='medium')
        path_row.addWidget(self.results_path_label, 1)
        self.open_results_folder_btn = QPushButton("Открыть в Finder")
        self.open_results_folder_btn.setObjectName("compactButton")
        self.open_results_folder_btn.clicked.connect(self._open_results_folder_in_finder)
        self.open_results_folder_btn.setToolTip("Открыть папку с файлом результата в Finder")
        self.open_results_folder_btn.setEnabled(False)
        path_row.addWidget(self.open_results_folder_btn)
        results_group_layout.addLayout(path_row)
        
        # Сводка по пинам (без тяжёлого превью карточек — при 500+ пинах сетка не показывается)
        self.results_summary_label = QLabel("Пинов: 0. Выберите запись в истории или выполните парсинг.")
        self.results_summary_label.setWordWrap(True)
        self.results_summary_label.setStyleSheet("color: #333; font-size: 13px; padding: 10px 0;")
        results_group_layout.addWidget(self.results_summary_label)
        # Сетка карточек не используется на вкладке Результаты (данные в CSV, публикация — на вкладке Публикация)
        self.pin_grid = PinGridWidget()
        self.pin_grid.hide()
        # pin_grid не добавляем в layout — превью убрано по запросу
        
        # Текстовая область для отображения информации (скрыта, используется для логов)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(100)
        self.results_text.hide()  # Скрываем текстовую область
        results_group_layout.addWidget(self.results_text)
        
        # Кнопки экспорта и уникализации
        results_buttons_layout = self._create_layout('hbox', spacing='medium')
        self.unique_results_btn = QPushButton("Уникализировать все")
        self.unique_results_btn.setObjectName("compactButton")
        self.unique_results_btn.clicked.connect(self.unique_results_csv)
        self.unique_results_btn.setEnabled(False)
        self.unique_results_btn.setToolTip("Уникализировать все заголовки и описания через ИИ (один раз)")
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
        
        # === СТРАНИЦА ПУБЛИКАЦИИ === (доска и результат по каждому аккаунту, у каждого аккаунта своя ссылка; картинки/заголовки/описания — из выбранного CSV)
        self.publish_page = QWidget()
        publish_layout = self._create_layout('vbox', 'large', 'large')
        
        posts_row = QHBoxLayout()
        posts_row.addWidget(QLabel("Количество постов:"))
        self.publish_posts_count_spin = QSpinBox()
        self.publish_posts_count_spin.setMinimum(1)
        self.publish_posts_count_spin.setMaximum(999)
        self.publish_posts_count_spin.setValue(1)
        self.publish_posts_count_spin.setSuffix(" постов")
        self.publish_posts_count_spin.setToolTip("Сколько раз опубликовать (по одному посту на аккаунт по кругу, интервал 30 сек)")
        posts_row.addWidget(self.publish_posts_count_spin)
        posts_row.addStretch()
        publish_layout.addLayout(posts_row)
        
        publish_layout.addWidget(QLabel("Доска и результат (CSV) для каждого аккаунта:"))
        self.publish_accounts_container = QWidget()
        self.publish_accounts_layout = QVBoxLayout(self.publish_accounts_container)
        self.publish_accounts_layout.setContentsMargins(0, 0, 0, 0)
        publish_layout.addWidget(self.publish_accounts_container)
        self.publish_account_board_combos = {}   # account_id -> QComboBox
        self.publish_account_csv_combos = {}      # account_id -> QComboBox (выбор результата/CSV для этого аккаунта)
        self.publish_account_link_inputs = {}    # account_id -> QLineEdit (своя ссылка для этого аккаунта)
        self.publish_account_refresh_btns = {}   # account_id -> QPushButton
        self._rebuilding_publish_accounts_list = False
        
        self.start_auto_publish_btn = QPushButton("Запустить автопубликацию")
        self.start_auto_publish_btn.clicked.connect(self.start_auto_publish)
        publish_layout.addWidget(self.start_auto_publish_btn)
        
        self.publish_progress = QProgressBar()
        self.publish_progress.setVisible(False)
        publish_layout.addWidget(self.publish_progress)
        
        self.publish_log = QTextEdit()
        self.publish_log.setReadOnly(True)
        self.publish_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        publish_layout.addWidget(self.publish_log, 1)
        
        publish_layout.addStretch()
        # Контент страницы публикации — в отдельном виджете для блюра при загрузке
        self.publish_content_widget = QWidget()
        self.publish_content_widget.setLayout(publish_layout)
        publish_page_main_layout = QVBoxLayout(self.publish_page)
        publish_page_main_layout.setContentsMargins(0, 0, 0, 0)
        publish_page_main_layout.addWidget(self.publish_content_widget)
        # Overlay загрузки досок (неактивное окно с блюром)
        self.publish_loading_overlay = QFrame(self.publish_page)
        self.publish_loading_overlay.setObjectName("publishLoadingOverlay")
        self.publish_loading_overlay.setStyleSheet("""
            QFrame#publishLoadingOverlay {
                background-color: rgba(255, 255, 255, 0.92);
                border: none;
            }
        """)
        overlay_layout = QVBoxLayout(self.publish_loading_overlay)
        overlay_label = QLabel("Загрузка досок для аккаунтов...")
        overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_label.setStyleSheet("font-size: 14px; color: #333;")
        overlay_layout.addWidget(overlay_label)
        self.publish_loading_overlay.setVisible(False)
        self.publish_loading_overlay.raise_()
        self.publish_page.installEventFilter(self)
        self.pages_stack.addWidget(self.publish_page)
        
        # === СТРАНИЦА НАСТРОЕК ===
        self.settings_page = QWidget()
        settings_layout = self._create_layout('vbox', 'large', 'large')
        
        ai_group = QGroupBox("ИИ API")
        ai_layout = QVBoxLayout()
        ai_layout.setContentsMargins(0, self.MARGIN_MEDIUM, 0, 0)
        ai_layout.setSpacing(self.SPACING_MEDIUM)
        
        self.ai_status_indicator = StatusIndicator(self, "Не подключен", "offline")
        self.ai_status_indicator.setStyleSheet("font-size: 11px;")
        ai_layout.addWidget(self.ai_status_indicator)
        
        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setPlaceholderText("API ключ OpenRouter...")
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_input.setMinimumWidth(280)
        self.ai_api_key_input.textChanged.connect(self.on_ai_key_changed)
        self.ai_api_key_input.setStyleSheet("""
            QLineEdit {
                font-size: 11px;
                padding: 8px 10px;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #000000;
            }
        """)
        ai_layout.addWidget(self.ai_api_key_input)
        
        self.ai_test_btn = QPushButton("Проверить подключение")
        self.ai_test_btn.setObjectName("compactButton")
        self.ai_test_btn.setMaximumHeight(32)
        self.ai_test_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ai_test_btn.clicked.connect(self.test_ai_connection)
        ai_layout.addWidget(self.ai_test_btn)
        
        ai_group.setLayout(ai_layout)
        settings_layout.addWidget(ai_group)
        
        # === ВХОД В PINTEREST (логин и пароль в приложении) ===
        login_group = QGroupBox("Вход в Pinterest")
        login_layout = QVBoxLayout()
        login_layout.setContentsMargins(0, self.MARGIN_MEDIUM, 0, 0)
        self.pinterest_login_input = QLineEdit()
        self.pinterest_login_input.setPlaceholderText("Email или логин")
        self.pinterest_login_input.setClearButtonEnabled(True)
        login_layout.addWidget(self.pinterest_login_input)
        self.pinterest_password_input = QLineEdit()
        self.pinterest_password_input.setPlaceholderText("Пароль")
        self.pinterest_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pinterest_password_input.setClearButtonEnabled(True)
        login_layout.addWidget(self.pinterest_password_input)
        self.pinterest_login_btn = QPushButton("Войти")
        self.pinterest_login_btn.clicked.connect(self._on_pinterest_login_clicked)
        login_layout.addWidget(self.pinterest_login_btn)
        login_group.setLayout(login_layout)
        settings_layout.addWidget(login_group)
        
        # === АККАУНТЫ (до 10) ===
        acc_group = QGroupBox("Аккаунты")
        acc_layout = QVBoxLayout()
        acc_layout.setContentsMargins(0, self.MARGIN_MEDIUM, 0, 0)
        self.accounts_list_label = QLabel(f"Аккаунтов: 0. Введите логин и пароль выше и нажмите «Войти» — каждый вход добавит аккаунт (до {MAX_ACCOUNTS}).")
        self.accounts_list_label.setWordWrap(True)
        acc_layout.addWidget(self.accounts_list_label)
        self.accounts_list_container = QWidget()
        self.accounts_list_layout = QVBoxLayout(self.accounts_list_container)
        self.accounts_list_layout.setContentsMargins(0, 8, 0, 0)
        self.accounts_list_layout.setSpacing(4)
        acc_layout.addWidget(self.accounts_list_container)
        acc_group.setLayout(acc_layout)
        settings_layout.addWidget(acc_group)
        settings_layout.addStretch()
        self.settings_page.setLayout(settings_layout)
        self.pages_stack.addWidget(self.settings_page)
        
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
        """Загружает стили из QSS файла или встроенный fallback. Применяет глобально к приложению (qApp)."""
        logger.debug("Начало load_styles()...")
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            logger.warning("load_styles: QApplication не найден, стили не применены")
            return
        try:
            style_path = get_styles_path()
            logger.warning(f"QSS PATH = {style_path}")
            logger.warning(f"QSS file exists = {style_path.exists()}")
            style_file = QFile(str(style_path))
            if style_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
                logger.debug("Файл стилей открыт, чтение...")
                stream = QTextStream(style_file)
                style = stream.readAll()
                style_file.close()
                logger.warning(f"QSS first 200 chars = {style[:200]!r}")
                app.setStyleSheet(style)  # глобально ко всему приложению
                logger.debug("Стили загружены из файла")
            else:
                logger.warning(f"Не удалось открыть файл стилей {style_path}, используем встроенные стили")
                from pinmaster.gui.embedded_styles import EMBEDDED_QSS
                style = EMBEDDED_QSS
                logger.warning(f"QSS (embedded) first 200 chars = {style[:200]!r}")
                app.setStyleSheet(EMBEDDED_QSS)
                logger.debug("Использованы встроенные стили")
        except Exception as e:
            logger.error(f"Ошибка в load_styles(): {e}", exc_info=True)
            try:
                from pinmaster.gui.embedded_styles import EMBEDDED_QSS
                app.setStyleSheet(EMBEDDED_QSS)
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
            except Exception:
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
        self.parse_btn.setChecked(False)
        self.results_btn.setChecked(False)
        self.publish_btn.setChecked(False)
        self.settings_btn.setChecked(False)
        
        if page_name == "parse":
            self.parse_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.parse_page)
        elif page_name == "results":
            self.results_btn.setChecked(True)
            already_on_results = self.pages_stack.currentWidget() is self.results_page
            self.pages_stack.setCurrentWidget(self.results_page)
            # Загружаем историю парсингов только при первом открытии вкладки (не при клике по элементу — иначе сбрасывается выделение)
            if not already_on_results:
                try:
                    logger.debug("show_page: загрузка истории парсингов для страницы результатов...")
                    self._load_parsing_history()
                    logger.debug("show_page: история парсингов загружена")
                except Exception as e:
                    logger.error(f"show_page: ошибка при загрузке истории парсингов: {e}", exc_info=True)
            # Обновляем информацию о CSV: один рабочий файл pinterest_results.csv
            try:
                results_csv = get_results_csv_path()
                if (not self.csv_file_path or not os.path.exists(self.csv_file_path)) and results_csv.exists():
                    self.csv_file_path = str(results_csv)
                    with open(results_csv, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        self.parsed_pins = self._pins_with_image(list(reader))
                    self._update_results_summary(self.parsed_pins)
                    self._update_results_path_display()
                    self._update_unique_btn_state()
                if self.csv_file_path and os.path.exists(self.csv_file_path):
                    self.csv_info_label.setText(f"CSV: {os.path.basename(self.csv_file_path)} | Пинов: {len(self.parsed_pins)}")
                    self.csv_info_label.setStyleSheet("color: #1a1a1a;")
                    self.export_csv_btn.setEnabled(True)
                    self._update_results_summary(self.parsed_pins)
                    self._update_results_path_display()
                    self._update_unique_btn_state()
            except Exception as e:
                logger.error(f"show_page: ошибка при обновлении информации о CSV: {e}", exc_info=True)
        elif page_name == "publish":
            self.publish_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.publish_page)
            # Надёжная загрузка результатов парсинга из файла перед построением строк аккаунтов
            self._load_parsing_history()
            self._rebuild_publish_accounts_list()
            self._on_publish_page_shown()
        elif page_name == "settings":
            self.settings_btn.setChecked(True)
            self.pages_stack.setCurrentWidget(self.settings_page)
    
    def eventFilter(self, obj, event):
        """Обновление геометрии overlay при изменении размера страницы Публикация."""
        if obj is self.publish_page and event.type() == QEvent.Type.Resize:
            if hasattr(self, 'publish_loading_overlay') and self.publish_loading_overlay.isVisible():
                self.publish_loading_overlay.setGeometry(self.publish_page.rect())
        return super().eventFilter(obj, event)
    
    def _show_publish_loading_overlay(self):
        """Показать overlay загрузки с блюром контента."""
        if not hasattr(self, 'publish_loading_overlay'):
            return
        self.publish_loading_overlay.setGeometry(self.publish_page.rect())
        self.publish_loading_overlay.raise_()
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(8)
        self.publish_content_widget.setGraphicsEffect(blur)
        self.publish_loading_overlay.setVisible(True)
    
    def _hide_publish_loading_overlay(self):
        """Скрыть overlay и убрать блюр."""
        if hasattr(self, 'publish_content_widget'):
            self.publish_content_widget.setGraphicsEffect(None)
        if hasattr(self, 'publish_loading_overlay'):
            self.publish_loading_overlay.setVisible(False)
    
    def _on_publish_page_shown(self):
        """При открытии вкладки Публикация: загрузить доски для аккаунтов без кэша (в т.ч. недавно добавленных)."""
        if not self.accounts:
            self._hide_publish_loading_overlay()
            return
        cached = getattr(self, '_cached_boards', {})
        # Проверяем по str(id) — кэш ключи строковые
        def _has_cache(acc):
            aid = acc.get("id") or ""
            return cached.get(aid) is not None or cached.get(str(aid)) is not None
        accounts_without_cache = [a for a in self.accounts if (a.get("id") or "") and not _has_cache(a)]
        if not accounts_without_cache:
            self._hide_publish_loading_overlay()
            return
        is_loading = getattr(self, '_load_all_boards_thread', None) and self._load_all_boards_thread.isRunning()
        if is_loading:
            self._show_publish_loading_overlay()
            return
        self._show_publish_loading_overlay()
        QTimer.singleShot(50, self._start_publish_boards_loading)
    
    def _maybe_start_boards_loading_for_new_accounts(self):
        """Если есть аккаунты без кэша досок (новые) — запустить загрузку в фоне (без overlay)."""
        if not self.accounts or not BOARD_SCRAPER_AVAILABLE:
            return
        cached = getattr(self, '_cached_boards', {})
        def _has_cache(acc):
            aid = acc.get("id") or ""
            return cached.get(aid) is not None or cached.get(str(aid)) is not None
        if all(_has_cache(a) for a in self.accounts if a.get("id")):
            return
        if getattr(self, '_load_all_boards_thread', None) and self._load_all_boards_thread.isRunning():
            return
        self._start_publish_boards_loading()
    
    def _start_publish_boards_loading(self):
        """Запускает поток загрузки досок через Playwright + cookies (без Selenium)."""
        if not self.accounts:
            self._hide_publish_loading_overlay()
            return
        if not BOARD_SCRAPER_AVAILABLE or not board_scraper_get_boards:
            self._hide_publish_loading_overlay()
            for acc in self.accounts:
                aid = acc.get("id") or ""
                combo = self.publish_account_board_combos.get(aid)
                if combo:
                    combo.clear()
                    if is_frozen():
                        combo.addItem("Браузер не найден — скачайте полную версию приложения")
                    else:
                        combo.addItem("Установите: pip install playwright && playwright install chromium")
            return

        class LoadAllBoardsThread(QThread):
            boards_loaded = pyqtSignal(str, list, object)   # account_id, boards, resolved_username (или None)
            boards_error = pyqtSignal(str, str)     # account_id, error_msg
            all_boards_loaded = pyqtSignal()

            def __init__(self, accounts, get_cookies_path_fn):
                super().__init__()
                self.accounts = accounts
                self.get_cookies_path_fn = get_cookies_path_fn

            def run(self):
                """Для каждого аккаунта: cookies из файла → board_scraper.get_boards()."""
                logger.info("LoadAllBoardsThread: запуск загрузки досок для %d аккаунтов", len(self.accounts))
                for acc in self.accounts:
                    aid = acc.get("id") or ""
                    if not aid:
                        continue
                    cookies_path = self.get_cookies_path_fn(aid)
                    logger.debug("LoadAllBoardsThread: аккаунт %s, cookies: %s", aid, cookies_path)
                    if not cookies_path.exists():
                        logger.warning("LoadAllBoardsThread: cookies не найден для %s", aid)
                        self.boards_error.emit(aid, "Нет cookies для аккаунта")
                        continue
                    try:
                        cookies = CookiesManager.load_from_json_file(str(cookies_path))
                    except Exception as e:
                        logger.exception("LoadAllBoardsThread: ошибка загрузки cookies")
                        self.boards_error.emit(aid, f"Ошибка загрузки cookies: {e}")
                        continue
                    if not cookies:
                        self.boards_error.emit(aid, "Не удалось загрузить cookies")
                        continue
                    # Всегда передаём None — board_scraper сам определит username из cookies.
                    # Иначе старый pinterest_username из конфига (Codesign_, etc.) мог загружать чужие доски.
                    try:
                        boards, _, resolved_username = board_scraper_get_boards(cookies, None)
                        logger.info("LoadAllBoardsThread: аккаунт %s — загружено %d досок", aid, len(boards or []))
                        self.boards_loaded.emit(aid, boards or [], resolved_username)
                    except Exception as e:
                        logger.exception("LoadAllBoardsThread: ошибка board_scraper для %s", aid)
                        self.boards_error.emit(aid, str(e))
                logger.info("LoadAllBoardsThread: завершён")
                self.all_boards_loaded.emit()

        self._load_all_boards_thread = LoadAllBoardsThread(self.accounts, get_cookies_path)
        self._load_all_boards_thread.boards_loaded.connect(self.on_boards_loaded)
        self._load_all_boards_thread.boards_error.connect(self.on_boards_error_account)
        self._load_all_boards_thread.all_boards_loaded.connect(self._on_all_boards_loaded)
        self._load_all_boards_thread.start()
    
    def _on_all_boards_loaded(self):
        """Все доски загружены — скрыть overlay."""
        self._hide_publish_loading_overlay()
    
    def setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()
        
        # Меню "Аккаунт" убрано — вход и аккаунты только в Настройках
        
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
                except Exception:
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
            # Список аккаунтов (до 10), каждый: {"id": "1", "name": "Аккаунт 1", "cookies_file": "account_1_cookies.json"}
            self.accounts = config.get("accounts", [])
            if not isinstance(self.accounts, list):
                self.accounts = []
            self.accounts = self.accounts[:MAX_ACCOUNTS]
            # Время последней проверки браузера на логин (чтобы не чекать каждый раз)
            self.last_login_check_timestamp = config.get("last_login_check_timestamp", "")
            self._pending_login = None  # (email, password) если вход запрошен до готовности парсера
            if hasattr(self, 'pinterest_login_input'):
                self.pinterest_login_input.setText(config.get("pinterest_login", ""))
            
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
            # headless не сбрасываем при enable_login: для фона (парсинг, инфо) используем headless;
            # окно браузера показываем только при нажатии «Войти» (там передаём headless=False явно)
            
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
            
            # Обновляем список аккаунтов на странице публикации и в настройках
            if hasattr(self, 'publish_accounts_layout'):
                QTimer.singleShot(0, self._rebuild_publish_accounts_list)
            if hasattr(self, 'accounts_list_layout'):
                QTimer.singleShot(0, self._update_accounts_list_display)
            # Загрузка досок в фоне при старте (board_scraper по каждому account_N_cookies.json)
            if self.accounts and BOARD_SCRAPER_AVAILABLE:
                QTimer.singleShot(300, self._start_publish_boards_loading)
            # При добавлении аккаунта через настройки загрузка досок инициируется при заходе на Публикацию
            # Загружаем историю парсингов
            QTimer.singleShot(1000, self._load_parsing_history)
            # Загружаем последний парсинг если есть
            QTimer.singleShot(1500, self._load_last_parsing)
            # Обновляем состояние кнопки «Уникализировать все» (API ключ + результаты)
            QTimer.singleShot(2000, self._update_unique_btn_state)
            
            # Браузер при старте не открываем — парсер создаётся только при «Войти» или парсинге
        except Exception as e:
            logger.error(f"Ошибка в load_config(): {e}", exc_info=True)
            # Устанавливаем значения по умолчанию при ошибке
            self.openrouter_api_key = ""
            self.ai_tokens_used = 0
            self.ai_cost = 0.0
            self.accounts = []
            self.last_login_check_timestamp = ""
            self.parser = None
            self.login_completed = False
            self._pending_login = None
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
        # Парсер уже есть и браузер жив — используем его
        if self.parser and getattr(self.parser, 'driver', None):
            is_alive = getattr(self.parser, 'is_driver_alive', lambda: True)
            if is_alive():
                return True
            try:
                self.parser.close()
            except Exception:
                pass
            self.parser = None
        
        # Парсера нет — запускаем инициализацию в фоне (без окна браузера)
        config = self.parser_config
        if getattr(self, 'parser_init_thread', None) and self.parser_init_thread.isRunning():
            self.statusBar().showMessage("Парсер уже запускается, подождите...")
            return False
        self.statusBar().showMessage("Запуск парсера в фоне...")
        # headless=True для фоновых задач (парсинг, инфо об аккаунте); окно только при «Войти»
        self._init_parser_with_login(False, True, config['download_images'], None)
        return False

    def _ensure_parser_sync(self) -> bool:
        """Синхронная инициализация парсера (только для внутреннего использования, когда поток уже не подходит)."""
        if self.parser and self.parser.driver:
            return True
        try:
            config = self.parser_config
            self.statusBar().showMessage("Инициализация парсера...")
            self.parser = PinterestSeleniumParser(
                headless=config['headless'],
                download_images=config['download_images'],
                auto_login=False
            )
            if not self.parser.driver:
                raise RuntimeError("Chrome драйвер не был создан")
            try:
                from path_utils import get_cookies_path
                from cookies_manager import load_cookies_from_file
                cookies_file = get_cookies_path()
                if cookies_file.exists():
                    print("📋 Загружаю cookies для работы в headless режиме...")
                    if config['headless']:
                        cookies = load_cookies_from_file(str(cookies_file))
                        if cookies:
                            self.parser.driver.get("https://www.pinterest.com")
                            import time
                            time.sleep(2)
                            cookies_set = 0
                            for name, value in cookies.items():
                                try:
                                    self.parser.driver.add_cookie({
                                        'name': name, 'value': value,
                                        'domain': '.pinterest.com', 'path': '/'
                                    })
                                    cookies_set += 1
                                except Exception:
                                    pass
                            print(f"  ✓ Установлено {cookies_set} из {len(cookies)} cookies")
                            self.parser.driver.refresh()
                            time.sleep(2)
                    else:
                        self.parser._ensure_authentication()
            except Exception as e:
                print(f"⚠ Не удалось загрузить cookies: {e}")
            self.statusBar().showMessage("Парсер готов")
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
            # Код выхода -9 (SIGKILL) — система блокирует неподписанный chromedriver
            if "-9" in error_msg or "Status code was: -9" in error_msg:
                main_text += "Код -9: macOS заблокировал Chrome драйвер (не от проверенного разработчика).\n\n"
                main_text += "Что сделать (в Терминале, подставьте путь из сообщения ниже):\n"
                main_text += "  codesign --force --sign - '/путь/к/chromedriver'\n"
                main_text += "После этого перезапустите приложение.\n\n"
            main_text += "Также можно попробовать снять карантин (см. команды ниже).\n\n"
            
            # Пробуем найти путь к драйверу
            driver_path = None
            try:
                from chromedriver_helper import get_chromedriver_path
                driver_path = get_chromedriver_path()
            except Exception:
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
                main_text += "или\n"
                main_text += f"xattr -c '{driver_path}'\n"
                main_text += "или\n"
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
        except Exception:
            pass
        
        # Попытка 2: Установить права на выполнение
        try:
            os.chmod(driver_path, 0o755)
            fixes_applied.append("✓ Права доступа установлены")
        except Exception:
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
    
    def _init_parser_with_login(self, enable_login: bool, headless: bool, download_images: bool, target_cookies_path: Optional[str] = None):
        """Инициализирует парсер с логином в отдельном потоке. target_cookies_path — id аккаунта для сохранения cookies (при добавлении аккаунта)."""
        if hasattr(self, 'parser_init_thread') and self.parser_init_thread is not None and self.parser_init_thread.isRunning():
            logger.warning("_init_parser_with_login: парсер уже инициализируется, пропускаем повторный вызов")
            return
        
        # Пропускаем только если парсер уже есть и браузер жив; иначе (driver=None после закрытия) — перезапускаем
        if self.parser is not None and target_cookies_path is None and getattr(self.parser, 'driver', None) is not None:
            logger.warning("_init_parser_with_login: парсер уже создан, пропускаем повторную инициализацию")
            return
        if self.parser is not None and getattr(self.parser, 'driver', None) is None:
            self.parser = None  # браузер закрыт — создаём парсер заново
        
        logger.info(f"_init_parser_with_login: запуск инициализации парсера, enable_login={enable_login}, headless={headless}")
        try:
            cookies_file_str = str(get_cookies_path(target_cookies_path)) if target_cookies_path else None
            self.parser_init_thread = ParserInitThread(enable_login, headless, download_images, cookies_file_str)
            self.parser_init_thread.parser_ready.connect(self.on_parser_ready)
            self.parser_init_thread.login_completed.connect(self.on_login_completed)
            self.parser_init_thread.error_occurred.connect(self.on_parser_error)
            self.parser_init_thread.start()
            logger.info("_init_parser_with_login: поток инициализации парсера запущен")
            # Кнопка «Парсить» неактивна с индикатором загрузки на время инициализации в фоне
            if hasattr(self, 'search_btn'):
                self.search_btn.setEnabled(False)
                self.search_btn.setText("Загрузка...")
                self.statusBar().showMessage("Инициализация парсера в фоне...")
        except Exception as e:
            logger.error(f"_init_parser_with_login: ошибка при запуске потока: {e}", exc_info=True)
            self.statusBar().showMessage(f"Ошибка инициализации парсера: {str(e)}")
    
    def on_parser_error(self, error_msg: str):
        """Обработчик ошибки инициализации парсера"""
        logger.error(f"on_parser_error: {error_msg}")
        self.statusBar().showMessage(f"Ошибка парсера: {error_msg}")
        if hasattr(self, 'search_btn'):
            self.search_btn.setEnabled(True)
            self.search_btn.setText("Парсить")
        if self.toast_manager:
            self.toast_manager.show_error(f"Ошибка парсера: {error_msg}")
        if getattr(self, '_pending_parse', False):
            self._pending_parse = False
        if getattr(self, '_pending_auto_publish', False):
            self._pending_auto_publish = False
        if hasattr(self, 'start_auto_publish_btn'):
            self.start_auto_publish_btn.setEnabled(True)
    
    def on_parser_ready(self, parser: PinterestSeleniumParser):
        """Обработчик готовности парсера"""
        logger.info("on_parser_ready: парсер готов")
        self.parser = parser
        self.statusBar().showMessage("Парсер готов")
        
        self._block_parse_button(10)
        self._update_browser_mode_indicator()
        
        # Если был запрос входа по логину/паролю до готовности парсера — выполняем сейчас
        pending = getattr(self, '_pending_login', None)
        if pending:
            self._pending_login = None
            email, password = pending[0], pending[1]
            target_id = pending[2] if len(pending) > 2 else None
            QTimer.singleShot(300, lambda: self._run_login_with_credentials(email, password, target_id))
            return
        if self.parser:
            cookies_file = get_cookies_path()
            if cookies_file.exists():
                self.refresh_account_info()
        # Если открыта вкладка Публикация и ждали парсер — запускаем загрузку досок
        if getattr(self, '_publish_waiting_for_parser', False):
            self._publish_waiting_for_parser = False
            if self.pages_stack.currentWidget() == self.publish_page and self.accounts:
                QTimer.singleShot(100, self._start_publish_boards_loading)
        if getattr(self, '_pending_parse', False):
            self._pending_parse = False
            if hasattr(self, 'start_auto_publish_btn'):
                self.start_auto_publish_btn.setEnabled(True)
            self.statusBar().showMessage("Парсер готов. Запуск парсинга...")
            QTimer.singleShot(200, self.on_search_clicked)
        elif getattr(self, '_pending_auto_publish', False):
            self._pending_auto_publish = False
            if hasattr(self, 'start_auto_publish_btn'):
                self.start_auto_publish_btn.setEnabled(True)
            self.statusBar().showMessage("Парсер готов. Запуск автопубликации...")
            QTimer.singleShot(200, self.start_auto_publish)
    
    def _update_browser_mode_indicator(self):
        """Обновляет индикатор режима браузера (убрано из сайдбара, теперь в меню)"""
        # Метод оставлен для совместимости, но больше не обновляет UI в сайдбаре
        # Режим браузера теперь управляется через меню "Настройки" -> "Работать в фоне"
        pass
    
    def on_login_completed(self):
        """Обработчик завершения логина - сохраняем время чека, загружаем информацию об аккаунте"""
        self.login_completed = True
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            config['last_login_check_timestamp'] = datetime.now().isoformat()
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Не удалось сохранить last_login_check_timestamp: {e}")
        self.statusBar().showMessage("Логин завершен, загрузка информации об аккаунте...")
        if self.parser:
            QTimer.singleShot(2000, self.refresh_account_info)
    
    def _block_parse_button(self, seconds: int = 10):
        """Блокирует кнопку парсинга на указанное количество секунд (после готовности парсера)"""
        if not hasattr(self, 'search_btn'):
            return
        
        self.search_btn.setEnabled(False)
        
        # Обновляем текст кнопки с обратным отсчетом; по окончании всегда восстанавливаем «Парсить»
        def update_button_text(remaining):
            if remaining > 0:
                self.search_btn.setText(f"Ожидание... ({remaining}с)")
                QTimer.singleShot(1000, lambda: update_button_text(remaining - 1))
            else:
                self.search_btn.setEnabled(True)
                self.search_btn.setText("Парсить")
                self.statusBar().showMessage("Парсер готов к работе")
        
        self.statusBar().showMessage(f"Парсер готов. Парсинг будет доступен через {seconds} сек.")
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
            self._update_unique_btn_state()
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
                    response.json()
                    logger.info("ConnectionTestThread: подключение к ИИ API успешно")
                    self.finished.emit(True, "Подключение успешно")
                except requests.exceptions.HTTPError as e:
                    error_msg = str(e)
                    if "402" in error_msg or "Payment Required" in error_msg:
                        logger.warning("ConnectionTestThread: на счёте OpenRouter недостаточно средств (402)")
                        self.finished.emit(False, "Недостаточно средств на счёте OpenRouter")
                    elif "401" in error_msg or "Unauthorized" in error_msg:
                        logger.warning("ConnectionTestThread: неверный API ключ")
                        self.finished.emit(False, "Неверный API ключ")
                    elif "429" in error_msg:
                        logger.warning("ConnectionTestThread: превышен лимит запросов")
                        self.finished.emit(False, "Превышен лимит запросов")
                    else:
                        logger.error(f"ConnectionTestThread: ошибка запроса: {error_msg}")
                        self.finished.emit(False, f"Ошибка: {error_msg[:80]}")
                except requests.exceptions.RequestException as e:
                    error_msg = str(e)
                    logger.warning(f"ConnectionTestThread: ошибка запроса: {error_msg}")
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
                self._update_unique_btn_state()
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
            if self.toast_manager:
                self.toast_manager.show_info("Парсер запускается в фоне. Нажмите «Обновить» через несколько секунд.")
            return
        
        # Подключаем cookies из списка аккаунтов (или основной файл), чтобы парсер был «залогинен»
        cookies_loaded = False
        if self.accounts:
            for acc in self.accounts:
                aid = acc.get("id")
                if not aid:
                    continue
                cookies_path = get_cookies_path(aid)
                if cookies_path.exists() and self.parser.load_cookies_from_file_path(str(cookies_path)):
                    cookies_loaded = True
                    break
        if not cookies_loaded:
            main_cookies = get_cookies_path()
            if main_cookies.exists():
                cookies_loaded = self.parser.load_cookies_from_file_path(str(main_cookies))
        if not cookies_loaded and self.toast_manager:
            self.toast_manager.show_warning("Нет cookies для аккаунта. Войдите в Настройках.")
            return
        
        self.statusBar().showMessage("Загрузка информации об аккаунте...")
        self.account_info_widget.refresh_btn.setEnabled(False)
        
        # Защита от вечной загрузки: через 20 сек снова включаем кнопку
        def _reenable_refresh():
            if getattr(self, 'account_info_thread', None) and self.account_info_thread.isRunning():
                self.account_info_widget.refresh_btn.setEnabled(True)
                self.statusBar().showMessage("Таймаут загрузки. Нажмите «Обновить» снова.")
        QTimer.singleShot(20000, _reenable_refresh)
        
        # Запускаем в отдельном потоке
        self.account_info_thread = AccountInfoThread(self.parser)
        self.account_info_thread.account_info_ready.connect(self.on_account_info_ready)
        self.account_info_thread.error_occurred.connect(self.on_account_info_error)
        self.account_info_thread.start()
    
    def on_account_info_ready(self, account_info: Dict[str, str]):
        """Обработчик успешного получения информации об аккаунте"""
        # Обновляем виджет с информацией об аккаунте
        self.account_info_widget.update_account_info(account_info)
        
        username = account_info.get('username', '')
        # Обновить имя первого аккаунта по username с Pinterest (если вошли по логину/паролю)
        if self.accounts and len(self.accounts) == 1 and username:
            try:
                self.accounts[0]['name'] = username
                config_path = get_config_path()
                config = {}
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['accounts'] = self.accounts
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                if hasattr(self, 'publish_accounts_layout'):
                    QTimer.singleShot(0, self._rebuild_publish_accounts_list)
                    QTimer.singleShot(100, self._maybe_start_boards_loading_for_new_accounts)
            except Exception as e:
                logger.warning(f"Не удалось обновить имя аккаунта: {e}")
        # Раньше: первый логин без списка аккаунтов — добавляли первый; теперь добавляем в _on_login_thread_done
        if not self.accounts and username:
            try:
                default_cookies = get_cookies_path()
                acc1_cookies = get_cookies_path("1")
                acc1_cookies.parent.mkdir(parents=True, exist_ok=True)
                if default_cookies.exists():
                    import shutil
                    shutil.copy2(default_cookies, acc1_cookies)
                new_acc = {"id": "1", "name": username or "Аккаунт 1", "cookies_file": "account_1_cookies.json"}
                self.accounts = [new_acc]
                config_path = get_config_path()
                config = {}
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['accounts'] = self.accounts
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                if hasattr(self, 'publish_accounts_layout'):
                    QTimer.singleShot(0, self._rebuild_publish_accounts_list)
                    QTimer.singleShot(100, self._maybe_start_boards_loading_for_new_accounts)
                if hasattr(self, 'accounts_list_label'):
                    self.accounts_list_label.setText(f"Аккаунтов: {len(self.accounts)}. Добавьте через кнопку ниже (логин в браузере).")
                if hasattr(self, 'accounts_list_layout'):
                    self._update_accounts_list_display()
                logger.info("Первый аккаунт добавлен в настройки после логина")
            except Exception as e:
                logger.warning(f"Не удалось добавить первый аккаунт в config: {e}")
        
        # Обновляем индикатор в сайдбаре
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
        if hasattr(self, 'auth_status_indicator'):
            self.auth_status_indicator.set_text("Не авторизован")
            self.auth_status_indicator.update_status("offline")
        if hasattr(self, 'auth_username_label'):
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
            if not getattr(self, '_pending_parse', False):
                self._pending_parse = True
                if hasattr(self, 'start_auto_publish_btn'):
                    self.start_auto_publish_btn.setEnabled(False)
                if hasattr(self, 'publish_log'):
                    self.publish_log.append("Парсер запускается... парсинг начнётся автоматически после готовности.")
                self.statusBar().showMessage("Парсер запускается... парсинг стартует после готовности.")
                if self.toast_manager:
                    self.toast_manager.show_info("Парсер запускается — парсинг начнётся автоматически.")
            else:
                self.statusBar().showMessage("Парсер всё ещё запускается... дождитесь готовности.")
            return
        
        # Подключаем cookies из аккаунта (парсинг в фоне под залогиненным аккаунтом)
        cookies_loaded = False
        has_any_cookie_file = False
        if self.accounts:
            for acc in self.accounts:
                aid = acc.get("id")
                if not aid:
                    continue
                cookies_path = get_cookies_path(aid)
                if cookies_path.exists():
                    has_any_cookie_file = True
                    if self.parser.load_cookies_from_file_path(str(cookies_path)):
                        cookies_loaded = True
                        break
        if not cookies_loaded:
            main_cookies = get_cookies_path()
            if main_cookies.exists():
                has_any_cookie_file = True
                cookies_loaded = self.parser.load_cookies_from_file_path(str(main_cookies))
        if not cookies_loaded:
            if has_any_cookie_file:
                # Файлы cookies есть, но загрузка не удалась — скорее всего сессия браузера закрыта
                try:
                    if self.parser:
                        self.parser.close()
                except Exception:
                    pass
                self.parser = None
                if self.toast_manager:
                    self.toast_manager.show_warning(
                        "Сессия браузера закрыта. Нажмите «Парсинг» снова — откроется новый браузер и загрузятся cookies."
                    )
            else:
                if self.toast_manager:
                    self.toast_manager.show_warning("Нет cookies. Добавьте аккаунт в Настройках и войдите.")
            return
        
        # Не запускаем второй парсинг, пока первый ещё идёт (один драйвер — один поток)
        if getattr(self, 'search_parse_thread', None) and self.search_parse_thread.isRunning():
            self.statusBar().showMessage("Парсинг уже выполняется, дождитесь завершения.")
            if self.toast_manager:
                self.toast_manager.show_warning("Дождитесь окончания текущего парсинга.")
            return
        
        # Получаем количество пинов
        max_pins = self.pins_count_spin.value()
        
        # Очищаем сводку результатов
        self._update_results_summary([])
        
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
    
    def _pins_with_image(self, pins: list) -> list:
        """Оставляет только пины с изображением (image_url или image_path)."""
        if not pins:
            return []
        return [p for p in pins if (p.get('image_url') or p.get('image_path') or '').strip()]
    
    def _update_results_summary(self, pins: list) -> None:
        """Обновляет сводку на вкладке Результаты (без превью карточек)."""
        if not hasattr(self, 'results_summary_label'):
            return
        n = len(pins) if pins else 0
        if n == 0:
            self.results_summary_label.setText("Пинов: 0. Выберите запись в истории или выполните парсинг.")
        else:
            self.results_summary_label.setText(
                f"Пинов: {n}. Данные сохранены в CSV. Для публикации перейдите на вкладку «Публикация»."
            )
        if hasattr(self, 'pin_grid'):
            self.pin_grid.hide()
    
    def _update_results_path_display(self) -> None:
        """Обновляет отображение пути к файлу результата и кнопку «Открыть в Finder»."""
        if not hasattr(self, 'results_path_label') or not hasattr(self, 'open_results_folder_btn'):
            return
        path = getattr(self, 'csv_file_path', None)
        if path and os.path.exists(path):
            folder = os.path.dirname(path)
            self.results_path_label.setText(f"Расположение: {folder}")
            self.results_path_label.setToolTip(path)
            self.open_results_folder_btn.setEnabled(True)
        else:
            self.results_path_label.setText("Расположение: не выбрано")
            self.results_path_label.setToolTip("")
            self.open_results_folder_btn.setEnabled(False)
    
    def _open_results_folder_in_finder(self) -> None:
        """Открывает папку с выбранным файлом результата и в Finder (macOS) выделяет сам CSV файл."""
        path = getattr(self, 'csv_file_path', None)
        if not path or not os.path.exists(path):
            if self.toast_manager:
                self.toast_manager.show_warning("Файл результата не выбран или не найден.")
            return
        path = os.path.abspath(path)
        folder = os.path.dirname(path)
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", path], check=True)
            elif sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder], check=True)
            self.statusBar().showMessage(f"Открыта папка: {folder}")
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось открыть папку: {e}")
    
    def on_parse_completed(self, pins: list):
        """Обработчик завершения парсинга"""
        # Только пины с изображением (обязательно для публикации)
        pins = self._pins_with_image(pins)
        self.parsed_pins = pins
        
        # Сохраняем в отдельный CSV для этого парсинга (уникальный файл на запрос + дата + время)
        try:
            from datetime import datetime
            import csv
            
            query = self.search_input.text().strip()
            self.last_parsing_query = query  # для уникализации пустых названий/описаний
            current_date = datetime.now().strftime("%Y-%m-%d")
            csv_path = get_unique_results_csv_path(query)
            
            if pins:
                fieldnames = ['title', 'description', 'pin_link', 'image_url', 'author', 'board_name', 'board_url',
                    'repin_count', 'comments_disabled', 'saves', 'done', 'comment_count', 'likes', 'created_at', 'share_count', 'search_query']
                rows = [{**p, 'search_query': query} for p in pins]
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(rows)
            self.csv_file_path = str(csv_path)
            
            # Сохраняем в историю парсингов (для списка парсингов)
            self._save_parsing_to_history(query, len(pins), str(csv_path), current_date)
            
            # Переключаемся на страницу результатов
            self.show_page("results")
            
            # Обновляем сводку (без превью карточек)
            self._update_results_summary(pins)
            
            # Обновляем информацию
            self.csv_info_label.setText(f"Найдено пинов: {len(pins)} | CSV: {csv_path.name}")
            self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
            self._update_results_path_display()
            self._update_unique_btn_state()
            self.export_csv_btn.setEnabled(True)
            
            self.statusBar().showMessage(f"Парсинг завершен. Найдено {len(pins)} пинов. Сохранено в {csv_path.name}")
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
        
        # Версия и сборка приложения
        version_label = QLabel(f"Версия: {APP_VERSION}  |  Сборка: {APP_BUILD}")
        version_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(version_label)
        
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
        
        # Прокси по аккаунтам (опционально)
        proxy_group = QGroupBox("Прокси для аккаунтов (по желанию)")
        proxy_layout = QVBoxLayout()
        proxy_layout.setSpacing(6)
        proxy_hint = QLabel("Для каждого аккаунта можно указать прокси для автопостинга (например http://host:port или socks5://host:port). Оставьте пустым, если прокси не нужен.")
        proxy_hint.setWordWrap(True)
        proxy_hint.setStyleSheet("color: #666; font-size: 11px;")
        proxy_layout.addWidget(proxy_hint)
        proxy_inputs = {}  # account_id -> QLineEdit
        for acc in self.accounts:
            aid = str(acc.get("id") or "")
            if not aid:
                continue
            name = acc.get("name") or f"Аккаунт {aid}"
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{name}:"), 0)
            le = QLineEdit()
            le.setPlaceholderText("http://host:port или пусто")
            le.setClearButtonEnabled(True)
            proxy_val = (acc.get("proxy") or "").strip()
            if proxy_val:
                le.setText(proxy_val)
            row.addWidget(le, 1)
            proxy_inputs[aid] = le
            proxy_layout.addLayout(row)
        if not proxy_inputs:
            proxy_layout.addWidget(QLabel("Нет добавленных аккаунтов. Добавьте аккаунты через «Войти» на странице Настроек."))
        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        
        def save_config():
            self.openrouter_api_key = api_key_input.text().strip()
            new_headless = headless_checkbox.isChecked()
            # Обновляем прокси по аккаунтам из полей ввода
            for aid, le in proxy_inputs.items():
                acc = next((a for a in self.accounts if str(a.get("id") or "") == aid), None)
                if acc is not None:
                    val = le.text().strip()
                    if val:
                        acc["proxy"] = val
                    elif "proxy" in acc:
                        del acc["proxy"]
            # Сохраняем в config.json
            try:
                config_path = get_config_path()
                config = {}
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                
                config['openrouter_api_key'] = self.openrouter_api_key
                config['headless'] = new_headless
                config['accounts'] = self.accounts
                
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
                            except Exception:
                                pass
                            self.parser = None
                            
                            # Перезапускаем парсер с новыми настройками (закроет старые браузеры)
                            QTimer.singleShot(500, self._restart_parser_with_config)
                
                if self.toast_manager:
                    self.toast_manager.show_success("Настройки сохранены")
                self._update_unique_btn_state()
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
            
            self.parser = None
            self.statusBar().showMessage("Перезапуск парсера в фоне...")
            self._init_parser_with_login(enable_login, headless, download_images, None)
            if self.toast_manager:
                self.toast_manager.show_info("Парсер перезапускается в фоне. Подождите несколько секунд.")
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка перезапуска: {e}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось перезапустить парсер: {e}")
    
    
    def load_boards(self):
        """Загружает доски (для обратной совместимости; для мультиаккаунта используйте load_boards_for_account)."""
        if self.accounts:
            aid = self.accounts[0].get("id")
            if aid:
                self.load_boards_for_account(aid)
        return
    
    def _do_load_boards(self, account_id: str):
        """Внутренний запуск потока загрузки досок через Playwright + cookies."""
        self._loading_boards_for_account = account_id
        if account_id in self.publish_account_refresh_btns:
            self.publish_account_refresh_btns[account_id].setEnabled(False)
        combo = self.publish_account_board_combos.get(account_id)
        if combo:
            combo.clear()
            combo.addItem("Загрузка досок...")

        class LoadSingleBoardsThread(QThread):
            boards_loaded = pyqtSignal(list)
            error_occurred = pyqtSignal(str)

            def __init__(self, account_id, accounts, get_cookies_path_fn):
                super().__init__()
                self.account_id = account_id
                self.accounts = accounts
                self.get_cookies_path_fn = get_cookies_path_fn

            def run(self):
                acc = next((a for a in self.accounts if a.get("id") == self.account_id), None)
                cookies_path = self.get_cookies_path_fn(self.account_id)
                try:
                    cookies = CookiesManager.load_from_json_file(str(cookies_path))
                except Exception as e:
                    self.error_occurred.emit(str(e))
                    return
                if not cookies:
                    self.error_occurred.emit("Не удалось загрузить cookies")
                    return
                acc_name = (acc.get("name") or "").strip() if acc else ""
                username = acc_name.split()[0] if acc_name and "@" not in acc_name and len(acc_name) >= 2 else None
                try:
                    boards, _, _ = board_scraper_get_boards(cookies, username)
                    self.boards_loaded.emit(boards or [])
                except Exception as e:
                    self.error_occurred.emit(str(e))

        def on_done():
            if account_id in self.publish_account_refresh_btns:
                self.publish_account_refresh_btns[account_id].setEnabled(True)

        self._load_single_boards_thread = LoadSingleBoardsThread(
            account_id, self.accounts, get_cookies_path
        )
        self._load_single_boards_thread.boards_loaded.connect(
            lambda b: (on_done(), self.on_boards_loaded(b))
        )
        self._load_single_boards_thread.error_occurred.connect(
            lambda e: (on_done(), self.on_boards_error(e))
        )
        self._load_single_boards_thread.start()
    
    def load_boards_for_account(self, account_id: str):
        """Загружает доски для одного аккаунта (по кнопке ↻) через Playwright + cookies."""
        if not BOARD_SCRAPER_AVAILABLE:
            if self.toast_manager:
                if is_frozen():
                    self.toast_manager.show_error("Модуль загрузки досок недоступен. Скачайте полную версию приложения с сайта.")
                else:
                    self.toast_manager.show_error("Установите: pip install playwright && playwright install chromium")
            return
        cookies_path = get_cookies_path(account_id)
        if not cookies_path.exists():
            if self.toast_manager:
                self.toast_manager.show_error("Нет cookies для этого аккаунта. Добавьте аккаунт в Настройках.")
            return
        self._do_load_boards(account_id)
    
    def _clear_layout_contents(self, layout):
        """Рекурсивно удаляет все виджеты и вложенные layout, чтобы не дублировались строки при перестроении."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout_contents(item.layout())
                item.layout().deleteLater()
    
    def _update_accounts_list_display(self):
        """Обновляет список аккаунтов в настройках с кнопками удаления."""
        if not hasattr(self, 'accounts_list_layout'):
            return
        self._clear_layout_contents(self.accounts_list_layout)
        for acc in self.accounts:
            aid = str(acc.get("id") or "")
            name = acc.get("name") or f"Аккаунт {aid}"
            row = QHBoxLayout()
            lbl = QLabel(f"• {name}")
            lbl.setStyleSheet("color: #333;")
            row.addWidget(lbl)
            row.addStretch()
            rm_btn = QPushButton("Удалить")
            rm_btn.setObjectName("compactButton")
            rm_btn.setStyleSheet("min-width: 70px;")
            rm_btn.setToolTip(f"Удалить аккаунт «{name}» из списка")
            rm_btn.clicked.connect(lambda checked, a=aid: self._remove_account(a))
            row.addWidget(rm_btn)
            self.accounts_list_layout.addLayout(row)

    def _remove_account(self, account_id: str):
        """Удаляет аккаунт из списка и сохраняет конфиг."""
        aid = str(account_id or "").strip()
        if not aid:
            return
        acc = next((a for a in self.accounts if str(a.get("id") or "") == aid), None)
        if not acc:
            return
        name = acc.get("name") or f"Аккаунт {aid}"
        reply = QMessageBox.question(
            self,
            "Удалить аккаунт",
            f"Удалить аккаунт «{name}» из списка? (Файл cookies не удаляется.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.accounts = [a for a in self.accounts if str(a.get("id") or "") != aid]
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            config["accounts"] = self.accounts
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Не удалось сохранить конфиг при удалении аккаунта: {e}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка сохранения: {e}")
            return
        self._update_accounts_list_display()
        if hasattr(self, 'publish_accounts_layout'):
            QTimer.singleShot(0, self._rebuild_publish_accounts_list)
        if hasattr(self, 'accounts_list_label'):
            self.accounts_list_label.setText(
                f"Аккаунтов: {len(self.accounts)}. Введите логин и пароль выше и нажмите «Войти» для добавления (до {MAX_ACCOUNTS})."
            )
        if self.toast_manager:
            self.toast_manager.show_success(f"Аккаунт «{name}» удалён")
        logger.info(f"Аккаунт {aid} («{name}») удалён из списка")

    def _rebuild_publish_accounts_list(self):
        """Перестраивает список аккаунтов на странице Публикация (доска по каждому). Доски подгружаются автоматически при открытии вкладки."""
        if getattr(self, '_rebuilding_publish_accounts_list', False):
            return
        # Проверяем — если combo уже созданы для текущих аккаунтов, просто обновим их из кэша (не пересоздаём)
        current_aids = {str(a.get("id") or "") for a in self.accounts if a.get("id")}
        existing_aids = set(self.publish_account_board_combos.keys())
        if current_aids and current_aids == existing_aids:
            # Combo уже созданы, просто обновим из кэша
            _cache = getattr(self, '_cached_boards', {})
            for aid, combo in self.publish_account_board_combos.items():
                cached = _cache.get(aid) or _cache.get(str(aid))
                if cached and combo.count() <= 1:  # Ещё не заполнен (только placeholder или пусто)
                    combo.blockSignals(True)
                    combo.clear()
                    combo.setPlaceholderText("")
                    for b in cached:
                        name = (b.get('name') or b.get('board_name') or '').strip() or 'Доска'
                        combo.addItem(name, b)
                    if combo.count() > 0:
                        combo.setCurrentIndex(0)
                    combo.blockSignals(False)
                    logger.debug(f"_rebuild: обновлён combo для aid='{aid}' из кэша, items={combo.count()}")
            return
        self._rebuilding_publish_accounts_list = True
        # Всегда подгружаем историю из файла, чтобы в комбо «Результат» были все парсинги
        self._load_parsing_history()
        logger.debug(f"_rebuild: полный rebuild, current_aids={current_aids}, existing_aids={existing_aids}")
        try:
            self.publish_account_board_combos.clear()
            if hasattr(self, 'publish_account_csv_combos'):
                self.publish_account_csv_combos.clear()
            if hasattr(self, 'publish_account_link_inputs'):
                self.publish_account_link_inputs.clear()
            if hasattr(self, 'publish_account_refresh_btns'):
                self.publish_account_refresh_btns.clear()
            self._clear_layout_contents(self.publish_accounts_layout)
            from PyQt6.QtWidgets import QApplication, QFrame
            QApplication.processEvents()
            entries_for_csv = list(getattr(self, '_all_history_entries', [])) or []
            csv_path_norm = os.path.normpath(os.path.abspath(self.csv_file_path or '')) if getattr(self, 'csv_file_path', None) else ''
            for idx, acc in enumerate(self.accounts):
                # Минималистичный разделитель между аккаунтами (не перед первым)
                if idx > 0:
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.HLine)
                    line.setStyleSheet("background-color: #e0e0e0; max-height: 1px;")
                    line.setFixedHeight(1)
                    self.publish_accounts_layout.addWidget(line)
                aid = str(acc.get("id") or "")
                name = acc.get("name") or f"Аккаунт {aid}"
                row = QHBoxLayout()
                row.addWidget(QLabel(name))
                combo = QComboBox()
                combo.setPlaceholderText("Загрузка...")
                combo.setMinimumWidth(220)
                combo.setMaximumWidth(400)
                row.addWidget(combo)
                refresh_btn = QPushButton("↻")
                refresh_btn.setToolTip("Обновить список досок")
                refresh_btn.setFixedWidth(32)
                refresh_btn.clicked.connect(lambda checked, a=aid: self.load_boards_for_account(a))
                row.addWidget(refresh_btn)
                self.publish_account_refresh_btns[aid] = refresh_btn
                row.addWidget(QLabel("  Результат:"))
                csv_combo = QComboBox()
                csv_combo.setMinimumWidth(240)
                csv_combo.setPlaceholderText("Выберите результат...")
                for entry in reversed(entries_for_csv):
                    date = entry.get('_date', '')
                    query = entry.get('query', 'Неизвестно')
                    pins_count = entry.get('pins_count', 0)
                    time = entry.get('time', '')
                    unique = entry.get('unique', False)
                    lbl = "Уник." if unique else "Не уник."
                    disp = f"{query[:25]}… | {pins_count} пинов ({lbl})" if len((query or '')) > 25 else f"{query} | {pins_count} пинов ({lbl})"
                    csv_combo.addItem(disp, entry)
                if csv_path_norm and csv_combo.count() > 0:
                    for i in range(csv_combo.count()):
                        e = csv_combo.itemData(i)
                        if e and os.path.normpath(os.path.abspath((e.get('csv_path') or '').strip() or '')) == csv_path_norm:
                            csv_combo.setCurrentIndex(i)
                            break
                self.publish_account_csv_combos[aid] = csv_combo
                row.addWidget(csv_combo)
                row.addWidget(QLabel("  Ссылка:"))
                link_edit = QLineEdit()
                link_edit.setPlaceholderText("https://... — ссылка для постов этого аккаунта")
                link_edit.setMinimumWidth(180)
                self.publish_account_link_inputs[aid] = link_edit
                row.addWidget(link_edit)
                row.addStretch()
                self.publish_accounts_layout.addLayout(row)
                self.publish_account_board_combos[aid] = combo
                logger.debug(f"_rebuild: создан combo для aid='{aid}', combos keys={list(self.publish_account_board_combos.keys())}")
                _cache = getattr(self, '_cached_boards', {})
                cached = _cache.get(aid) or _cache.get(str(aid))
                if cached:
                    combo.clear()
                    combo.setPlaceholderText("")
                    def _disp(b):
                        return (b.get('name') or b.get('board_name') or '').strip() or 'Доска'
                    filtered = [b for b in cached if (b.get('name') or b.get('board_name') or '').strip()]
                    if not filtered and cached:
                        filtered = cached
                    if filtered:
                        for b in filtered:
                            combo.addItem(_disp(b), b)
                        combo.setCurrentIndex(0)
            if hasattr(self, 'accounts_list_label'):
                self.accounts_list_label.setText(f"Аккаунтов: {len(self.accounts)}. Введите логин и пароль выше и нажмите «Войти» — каждый вход добавит аккаунт (до {MAX_ACCOUNTS}).")
        finally:
            self._rebuilding_publish_accounts_list = False
    
    def _on_pinterest_login_clicked(self):
        """Войти и добавить аккаунт в список (до 10). Повторный ввод других данных и «Войти» — добавит другой аккаунт."""
        email = (self.pinterest_login_input.text() or "").strip()
        password = (self.pinterest_password_input.text() or "").strip()
        if not email or not password:
            if self.toast_manager:
                self.toast_manager.show_warning("Введите логин (email) и пароль")
            return
        # Проверка дубликата: такой логин уже добавлен
        email_lower = email.lower()
        if any((a.get("name") or "").strip().lower() == email_lower for a in self.accounts):
            if self.toast_manager:
                self.toast_manager.show_warning("Этот аккаунт уже добавлен. Введите другие данные для нового аккаунта.")
            return
        if len(self.accounts) >= MAX_ACCOUNTS:
            if self.toast_manager:
                self.toast_manager.show_warning(f"Достигнут лимит: максимум {MAX_ACCOUNTS} аккаунтов")
            return
        # Свободный id для нового аккаунта (1..MAX_ACCOUNTS)
        used = {str(a.get("id") or "") for a in self.accounts if a.get("id")}
        new_id = None
        for i in range(1, MAX_ACCOUNTS + 1):
            if str(i) not in used:
                new_id = str(i)
                break
        if not new_id:
            return
        if not self.parser or not getattr(self.parser, 'driver', None):
            self._pending_login = (email, password, new_id)
            self.pinterest_login_btn.setEnabled(False)
            self.statusBar().showMessage("Запуск браузера для входа...")
            self._init_parser_with_login(False, False, True, None)
            if self.toast_manager:
                self.toast_manager.show_info("Браузер запускается. После загрузки выполнится вход.")
            return
        self._run_login_with_credentials(email, password, new_id)
    
    def _run_login_with_credentials(self, email: str, password: str, target_account_id: Optional[str] = None):
        """Вход в Pinterest в потоке; при успехе добавляет аккаунт в список (до 10)."""
        save_path = str(get_cookies_path(target_account_id)) if target_account_id else None
        class LoginThread(QThread):
            login_done = pyqtSignal(bool, str, object)
            def __init__(self, parser, email, password, save_cookies_to):
                super().__init__()
                self.parser = parser
                self.email = email
                self.password = password
                self.save_cookies_to = save_cookies_to
            def run(self):
                try:
                    ok = self.parser.login_with_credentials(
                        self.email, self.password, save_cookies_to=self.save_cookies_to
                    )
                    self.login_done.emit(ok, self.email, self.save_cookies_to)
                except Exception as e:
                    logger.exception("LoginThread")
                    self.login_done.emit(False, str(e), None)
        self.pinterest_login_btn.setEnabled(False)
        self.statusBar().showMessage("Вход в Pinterest...")
        self._login_target_account_id = target_account_id
        self._login_thread = LoginThread(self.parser, email, password, save_path)
        self._login_thread.login_done.connect(self._on_login_thread_done)
        self._login_thread.start()
    
    def _on_login_thread_done(self, success: bool, email_or_error: str, save_cookies_to_path):
        """После входа: сохраняем конфиг и добавляем аккаунт в список."""
        self.pinterest_login_btn.setEnabled(True)
        target_id = getattr(self, '_login_target_account_id', None)
        self._login_target_account_id = None
        if not success:
            self.statusBar().showMessage("Ошибка входа")
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось войти: {email_or_error}")
            return
        # Закрываем браузер — cookies уже сохранены
        if self.parser and getattr(self.parser, 'driver', None):
            try:
                self.parser.close_browser()
            except Exception:
                pass
        try:
            config_path = get_config_path()
            config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            config['last_login_check_timestamp'] = datetime.now().isoformat()
            config['pinterest_login'] = email_or_error
            # Добавляем аккаунт в список (первый или следующий до 10)
            if target_id:
                name = email_or_error or f"Аккаунт {target_id}"
                new_acc = {"id": target_id, "name": name, "cookies_file": f"account_{target_id}_cookies.json"}
                if not any(a.get("id") == target_id for a in self.accounts):
                    self.accounts.append(new_acc)
                config['accounts'] = self.accounts
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Не удалось сохранить конфиг после входа: {e}")
        if hasattr(self, 'publish_accounts_layout'):
            QTimer.singleShot(0, self._rebuild_publish_accounts_list)
            QTimer.singleShot(100, self._maybe_start_boards_loading_for_new_accounts)
        if hasattr(self, 'accounts_list_label'):
            self.accounts_list_label.setText(f"Аккаунтов: {len(self.accounts)}. Введите другие данные и нажмите «Войти» для добавления ещё одного (до {MAX_ACCOUNTS}).")
        if hasattr(self, 'accounts_list_layout'):
            self._update_accounts_list_display()
        self.statusBar().showMessage("Аккаунт добавлен")
        if self.toast_manager:
            self.toast_manager.show_success("Аккаунт добавлен в список")
        # Обновить инфо об аккаунте, если это единственный — загрузить имя с Pinterest
        if len(self.accounts) == 1 and self.parser:
            QTimer.singleShot(1500, self.refresh_account_info)
    
    def on_boards_loaded(self, account_id_or_boards, boards=None, resolved_username=None):
        """Обработчик загрузки досок. LoadAllBoardsThread: (account_id, boards, resolved_username); LoadBoardsThread: (boards,) только."""
        if boards is not None:
            account_id = account_id_or_boards
        else:
            account_id = getattr(self, '_loading_boards_for_account', None)
            boards = account_id_or_boards if isinstance(account_id_or_boards, list) else []
        if account_id:
            self._loading_boards_for_account = None
        aid_key = str(account_id).strip() if account_id is not None and account_id != "" else None
        logger.debug("on_boards_loaded: account_id=%r, boards=%d, combos keys=%s", account_id, len(boards or []), list(self.publish_account_board_combos.keys()))
        if aid_key and boards is not None:
            self._cached_boards[aid_key] = boards
            if resolved_username and account_id:
                acc = next((a for a in self.accounts if str(a.get("id") or "") == str(account_id)), None)
                if acc and (acc.get("name") or "").strip().find("@") >= 0 and acc.get("pinterest_username") != resolved_username:
                    try:
                        acc["pinterest_username"] = resolved_username
                        config_path = get_config_path()
                        if config_path.exists():
                            with open(config_path, "r", encoding="utf-8") as f:
                                config = json.load(f)
                            for a in config.get("accounts", []):
                                if str(a.get("id") or "") == str(account_id):
                                    a["pinterest_username"] = resolved_username
                                    break
                            with open(config_path, "w", encoding="utf-8") as f:
                                json.dump(config, f, indent=2, ensure_ascii=False)
                            logger.info("pinterest_username сохранён для аккаунта %s: %s", account_id, resolved_username)
                    except Exception as e:
                        logger.warning("Не удалось сохранить pinterest_username: %s", e)
        combo = self.publish_account_board_combos.get(aid_key) if aid_key else None
        # Проверяем что combo не был удалён (Qt виджеты могут стать невалидными после deleteLater)
        try:
            import sip
            if combo and sip.isdeleted(combo):
                logger.warning(f"on_boards_loaded: combo для aid_key='{aid_key}' был удалён (sip.isdeleted=True)")
                combo = None
        except (ImportError, RuntimeError):
            pass
        logger.debug(f"on_boards_loaded: lookup combo by aid_key='{aid_key}', combo={combo}, combo is None={combo is None}")
        if combo is None and aid_key and self.publish_account_board_combos:
            for k, c in self.publish_account_board_combos.items():
                if str(k).strip() == str(aid_key).strip():
                    combo = c
                    break
        if combo is None and aid_key and self.publish_account_board_combos:
            combo = self.publish_account_board_combos.get(int(aid_key)) if str(aid_key).isdigit() else None
        # НЕ берём первый попавшийся combo — это перезапишет данные другого аккаунта!
        if combo is None:
            logger.warning("on_boards_loaded: combo не найден для account_id=%r (aid_key=%r), вызываю _rebuild", account_id, aid_key)
            if hasattr(self, 'publish_accounts_layout'):
                self._rebuild_publish_accounts_list()
            return
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            combo.setPlaceholderText("")
            if boards:
                def _display_name(b):
                    return (b.get('name') or b.get('board_name') or '').strip() or 'Доска'
                filtered = [b for b in boards if (b.get('name') or b.get('board_name') or '').strip()]
                if not filtered and boards:
                    filtered = boards
                if filtered:
                    for b in filtered:
                        combo.addItem(_display_name(b), b)
                    combo.setCurrentIndex(0)
                    who = f" ({resolved_username})" if resolved_username else ""
                    self.publish_log.append(f"Загружено досок: {len(filtered)}{who}")
                else:
                    combo.addItem("Нет доступных досок")
                    combo.setCurrentIndex(0)
            else:
                combo.addItem("Доски не найдены")
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
            combo.setEnabled(True)
            combo.update()
            combo.repaint()
            logger.debug("on_boards_loaded: combo обновлён, items=%d", combo.count())
    
    def on_boards_error_account(self, account_id: str, error: str):
        """Обработчик ошибки загрузки досок для одного аккаунта (LoadAllBoardsThread)."""
        combo = self.publish_account_board_combos.get(account_id) if account_id else None
        if combo:
            combo.clear()
            combo.addItem("Ошибка загрузки")
        self.publish_log.append(f"Ошибка ({account_id}): {error}")
        if self.toast_manager:
            self.toast_manager.show_error(f"Доски для аккаунта {account_id}: {error}")
    
    def on_boards_error(self, error: str):
        """Обработчик ошибки загрузки досок (одиночный вызов от LoadBoardsThread)."""
        aid = getattr(self, '_loading_boards_for_account', None)
        if aid:
            self.on_boards_error_account(aid, error)
        else:
            self.publish_log.append(f"Ошибка: {error}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось загрузить доски: {error}")
    
    def _unique_pins_for_publish(self, pins_data: list) -> Optional[list]:
        """Уникализирует пины перед публикацией"""
        if not self.openrouter_api_key:
            return None
        
        try:
            unique_pins = []
            
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
        """Запускает автопубликацию: для каждого аккаунта — своя доска, свой результат (CSV) и своя ссылка; N постов по аккаунтам по кругу, 30 сек между постами."""
        if not self.accounts:
            if self.toast_manager:
                self.toast_manager.show_error("Нет добавленных аккаунтов. Добавьте хотя бы один в Настройках (логин и пароль → Войти).")
            return
        # Собираем (account_id, board_name), свою ссылку и результат (CSV) для каждого аккаунта
        account_boards = []
        account_pins = {}   # account_id -> list of pins
        account_links = {}  # account_id -> ссылка для постов этого аккаунта (обязательно)
        default_csv = getattr(self, "csv_file_path", None)
        for acc in self.accounts:
            aid = str(acc.get("id") or "").strip()
            if not aid:
                continue
            combo = self.publish_account_board_combos.get(aid)
            if not combo or combo.currentIndex() < 0:
                continue
            board_data = combo.currentData()
            if not board_data:
                continue
            board_name = board_data.get("name") or board_data.get("board_name") or combo.currentText()
            # Результат (CSV) для этого аккаунта: из комбо или общий csv_file_path
            csv_combo = getattr(self, "publish_account_csv_combos", {}).get(aid)
            entry = None
            csv_path = None
            if csv_combo and csv_combo.currentIndex() >= 0:
                entry = csv_combo.currentData()
                if entry and isinstance(entry, dict):
                    csv_path = (entry.get("csv_path") or "").strip()
            if not csv_path and default_csv and os.path.exists(default_csv):
                csv_path = default_csv
                # Найти запись в истории для проверки unique
                for e in (getattr(self, "_all_history_entries", None) or []):
                    if (e.get("csv_path") or "").strip() and os.path.normpath(os.path.abspath((e.get("csv_path") or "").strip())) == os.path.normpath(os.path.abspath(default_csv)):
                        entry = e
                        break
            if not csv_path or not os.path.exists(csv_path):
                if self.toast_manager:
                    self.toast_manager.show_error(f"Для аккаунта {aid} выберите результат (CSV) в колонке «Результат» или выберите запись на вкладке «Результаты».")
                return
            if entry is None:
                for e in (getattr(self, "_all_history_entries", None) or []):
                    if (e.get("csv_path") or "").strip() and os.path.normpath(os.path.abspath((e.get("csv_path") or "").strip())) == os.path.normpath(os.path.abspath(csv_path)):
                        entry = e
                        break
            if entry is None:
                if self.toast_manager:
                    self.toast_manager.show_error("Выберите для каждого аккаунта результат из списка на вкладке «Результаты» (уникализированный).")
                return
            if not entry.get("unique", False):
                if self.toast_manager:
                    self.toast_manager.show_error("Выбран результат без уникализации. Уникализируйте его на вкладке «Результаты» (кнопка «Уникализировать все») — без этого нельзя начать автопостинг.")
                return
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    pins_list = self._pins_with_image(list(csv.DictReader(f))) if hasattr(self, "_pins_with_image") else list(csv.DictReader(f))
            except Exception as e:
                logger.warning(f"Не удалось загрузить пины из {csv_path}: {e}")
                if self.toast_manager:
                    self.toast_manager.show_error(f"Не удалось прочитать CSV для аккаунта {aid}.")
                return
            if not pins_list:
                if self.toast_manager:
                    self.toast_manager.show_error(f"В выбранном результате для аккаунта {aid} нет пинов с изображениями.")
                return
            link_edit = getattr(self, "publish_account_link_inputs", {}).get(aid)
            link_text = (link_edit.text() or "").strip() if link_edit else ""
            if not link_text:
                if self.toast_manager:
                    self.toast_manager.show_error(f"Укажите ссылку для аккаунта {aid} в поле «Ссылка» (у каждого аккаунта должна быть своя ссылка).")
                return
            account_links[aid] = link_text
            account_boards.append((aid, board_name))
            account_pins[aid] = pins_list
            logger.info(f"Аккаунт {aid}: доска '{board_name}', пинов: {len(pins_list)}, ссылка: {link_text[:50]}…")
        if not account_boards:
            if self.toast_manager:
                self.toast_manager.show_error("Добавьте аккаунты в Настройках и выберите доску, результат и ссылку для каждого (↻)")
            return

        logger.info(f"Подготовка к автопостингу: {len(account_boards)} аккаунтов, пары (account_id, board_name): {account_boards}")

        max_posts = self.publish_posts_count_spin.value()
        # Путь к CSV для каждого аккаунта (для удаления опубликованной строки из правильного файла в прод)
        account_csv_paths = {}
        for aid, board_name in account_boards:
            csv_combo = getattr(self, "publish_account_csv_combos", {}).get(str(aid))
            csv_path = None
            if csv_combo and csv_combo.currentIndex() >= 0:
                entry = csv_combo.currentData()
                if entry and isinstance(entry, dict):
                    csv_path = (entry.get("csv_path") or "").strip()
            account_csv_paths[str(aid)] = csv_path or getattr(self, "csv_file_path", None)
        
        # Резолвер путей cookies: использует cookies_file из конфига аккаунта (без хардкода)
        acc_map = {str(a.get("id") or ""): a for a in self.accounts if a.get("id")}
        def resolve_cookies_path(aid):
            aid_str = str(aid)
            acc = acc_map.get(aid_str)
            if acc and acc.get("cookies_file"):
                cf = str(acc["cookies_file"])
                if "/" in cf or "\\" in cf:
                    return Path(cf)
                return get_accounts_dir() / cf
            return get_cookies_path(aid_str)
        
        # В прод: задать PLAYWRIGHT_BROWSERS_PATH до старта потока (распаковка из bundle при необходимости)
        try:
            import board_scraper
            board_scraper._configure_playwright_browsers_path()
        except Exception:
            pass
        
        # Поток: Playwright с постоянными профилями по аккаунтам (до 10), прокси, пул контекстов
        class AutoPublishThread(QThread):
            publish_progress = pyqtSignal(str)
            publish_completed = pyqtSignal(bool, str)
            pin_published = pyqtSignal(str, str)  # (image_url, csv_path) — удалить строку из этого CSV
            publish_session_died = pyqtSignal()

            def __init__(self, account_boards, account_pins, account_links, account_csv_paths, max_posts, get_cookies_path_fn, headless=False, accounts=None):
                super().__init__()
                self.account_boards = account_boards
                self.account_pins = dict(account_pins)  # account_id -> list of pins
                self.account_links = dict(account_links)  # account_id -> link для пинов этого аккаунта
                self.account_csv_paths = dict(account_csv_paths or {})  # account_id -> путь к CSV (для удаления строки)
                self.max_posts = max_posts
                self.get_cookies_path_fn = get_cookies_path_fn
                self.headless = headless
                self.accounts = list(accounts) if accounts else []
                self._context_pool = {}  # account_id -> persistent BrowserContext
                self._page_pool = {}  # account_id -> Page (одна вкладка pin-builder на аккаунт, ultra-fast без reload)
                self._pin_index_per_account = {}  # account_id -> индекс следующего пина для этого аккаунта

            def _get_user_data_dir(self, account_id: str):
                """Путь к директории профиля Chrome для аккаунта (profiles/pw_profile_{account_id})."""
                return get_playwright_profile_dir(str(account_id or "").strip())

            def _get_account_proxy(self, account_id: str):
                """Прокси для аккаунта из config accounts[].proxy или None."""
                aid = str(account_id or "").strip()
                acc = next((a for a in self.accounts if str(a.get("id") or "") == aid), None)
                if not acc:
                    return None
                proxy = (acc.get("proxy") or "").strip()
                return proxy if proxy else None

            def _get_or_create_context(self, playwright, account_id: str):
                """Получить или создать постоянный контекст для account_id (пул, один браузер на аккаунт)."""
                aid = str(account_id or "").strip() or "default"
                if aid in self._context_pool:
                    return self._context_pool[aid]
                try:
                    import board_scraper
                    board_scraper._configure_playwright_browsers_path()
                except Exception:
                    pass
                import random
                user_data_dir = self._get_user_data_dir(account_id)
                user_data_dir.mkdir(parents=True, exist_ok=True)
                proxy = self._get_account_proxy(account_id)
                viewport = {"width": random.randint(1360, 1440), "height": random.randint(860, 940)}
                kwargs = {
                    "user_data_dir": str(user_data_dir),
                    "headless": self.headless,
                    "viewport": viewport,
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "accept_downloads": True,
                }
                if proxy:
                    kwargs["proxy"] = {"server": proxy}
                ctx = playwright.chromium.launch_persistent_context(**kwargs)
                ctx.add_init_script("document.documentElement.style.zoom = '100%';")
                self._context_pool[aid] = ctx
                return ctx

            def run(self):
                """Очередь: plan — по одному посту на аккаунт по кругу (acc1, acc2, acc1, …). У каждого аккаунта свой список пинов (account_pins), своя ссылка (account_links) и свой счётчик пина (_pin_index_per_account)."""
                import time
                import random
                INTERVAL_SEC = 30
                total = self.max_posts
                success_count = 0
                error_count = 0
                plan = [self.account_boards[i % len(self.account_boards)] for i in range(total)]
                self.publish_progress.emit(f"Автопубликация (Playwright): {total} постов, {len(self.account_boards)} аккаунтов, интервал {INTERVAL_SEC} сек")
                image_cache = {}
                temp_files_to_remove = []
                try:
                    from playwright.sync_api import sync_playwright
                    from cookies_manager import load_cookies_from_file
                    from pinterest_publisher import create_pin_playwright, _cookies_to_playwright
                except ImportError as e:
                    if is_frozen():
                        self.publish_progress.emit("✗ Модуль публикации недоступен. Переустановите приложение (полная версия).")
                        self.publish_completed.emit(False, "Playwright не найден в сборке")
                    else:
                        self.publish_progress.emit(f"✗ Playwright не установлен: {e}")
                        self.publish_completed.emit(False, str(e))
                    return
                try:
                    with sync_playwright() as p:
                        try:
                            for i, (account_id, board_name) in enumerate(plan, 1):
                                pins_for_account = self.account_pins.get(str(account_id)) or []
                                if not pins_for_account:
                                    self.publish_progress.emit(f"✗ Нет пинов для аккаунта {account_id}")
                                    error_count += 1
                                    continue
                                idx = self._pin_index_per_account.get(str(account_id), 0)
                                pin_index = idx % len(pins_for_account)
                                pin = pins_for_account[pin_index]
                                self._pin_index_per_account[str(account_id)] = idx + 1
                                image_url_or_path = (pin.get("image_url") or pin.get("image_path") or "").strip()
                                # Те же правила, что и в CLI: title/Title, description/Description, fallback «Без названия»
                                title = (pin.get("title") or pin.get("Title") or "").strip()
                                description = (pin.get("description") or pin.get("Description") or "").strip()
                                if not title and description:
                                    title = (description[:80] + "…") if len(description) > 80 else description
                                if not title:
                                    title = "Без названия"

                                if i > 1:
                                    self.publish_progress.emit(f"\n⏱ Ожидание {INTERVAL_SEC} сек...")
                                    time.sleep(INTERVAL_SEC)
                                self.publish_progress.emit(f"\n--- Пост {i}/{total} | Аккаунт {account_id}, доска: '{board_name}' | пин {pin_index + 1}/{len(pins_for_account)} ---")

                                cookies_path = self.get_cookies_path_fn(str(account_id))
                                if not cookies_path or not cookies_path.exists():
                                    self.publish_progress.emit(f"✗ Нет cookies для аккаунта {account_id}")
                                    error_count += 1
                                    continue

                                cookies = load_cookies_from_file(str(cookies_path))
                                if not cookies:
                                    self.publish_progress.emit("✗ Не удалось загрузить cookies")
                                    error_count += 1
                                    continue
                                pw_cookies = _cookies_to_playwright(cookies)

                                if not image_url_or_path:
                                    self.publish_progress.emit("✗ У пина нет изображения (image_url/image_path)")
                                    error_count += 1
                                    continue
                                image_path = image_cache.get(image_url_or_path)
                                if not image_path or not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
                                    image_path = self.download_image(image_url_or_path)
                                    if image_path and os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                                        image_cache[image_url_or_path] = image_path
                                        import tempfile
                                        if image_path.startswith(tempfile.gettempdir()):
                                            temp_files_to_remove.append(image_path)
                                if not image_path or not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
                                    self.publish_progress.emit("✗ Не удалось загрузить изображение пина")
                                    error_count += 1
                                    continue

                                if i > 1:
                                    time.sleep(2)

                                aid_str = str(account_id)
                                try:
                                    context = self._get_or_create_context(p, aid_str)
                                    reuse_page = aid_str in self._page_pool
                                    if reuse_page:
                                        page = self._page_pool[aid_str]
                                        context.add_cookies(pw_cookies)
                                    else:
                                        context.add_cookies(pw_cookies)
                                        page = context.new_page()
                                        page.set_default_timeout(30000)
                                        self._page_pool[aid_str] = page
                                    error_out = []
                                    link = self.account_links.get(str(account_id), "")
                                    ok = create_pin_playwright(
                                        page,
                                        image_path=image_path,
                                        title=title,
                                        description=description,
                                        link=link,
                                        board_name=board_name,
                                        logger=logging.getLogger("PinMaster"),
                                        error_out=error_out,
                                        reuse_page=reuse_page,
                                    )
                                    if ok:
                                        success_count += 1
                                        self.publish_progress.emit(f"✓ Опубликовано в доску «{board_name}» (аккаунт {account_id})")
                                        csv_to_remove = self.account_csv_paths.get(aid_str, "")
                                        self.pin_published.emit(image_url_or_path, csv_to_remove or "")
                                    else:
                                        error_count += 1
                                        self.publish_progress.emit("✗ Ошибка публикации (Playwright)")
                                        if error_out:
                                            self.publish_progress.emit(f"  Детали: {error_out[0][:300]}")
                                    # Страницу не закрываем — переиспользуем для следующего пина (ultra-fast)
                                except Exception as e:
                                    error_count += 1
                                    self.publish_progress.emit(f"✗ {str(e)}")
                                    if aid_str in getattr(self, "_page_pool", {}):
                                        try:
                                            self._page_pool[aid_str].close()
                                        except Exception:
                                            pass
                                        del self._page_pool[aid_str]

                            for fp in temp_files_to_remove:
                                try:
                                    if os.path.exists(fp):
                                        os.remove(fp)
                                except Exception:
                                    pass
                            msg = f"Автопубликация завершена. Успешных публикаций: {success_count}. Ошибок: {error_count}."
                            self.publish_completed.emit(success_count > 0, msg)
                        finally:
                            self._page_pool.clear()
                            for ctx in self._context_pool.values():
                                try:
                                    ctx.close()
                                except Exception:
                                    pass
                            self._context_pool.clear()
                except Exception as e:
                    logger.exception("AutoPublishThread")
                    msg = f"Автопубликация прервана. Ошибка: {e}. Успешных публикаций: {success_count}, ошибок: {error_count}."
                    self.publish_completed.emit(success_count > 0, msg)

            def download_image(self, image_url: str) -> Optional[str]:
                """Загружает изображение по URL или из локального файла"""
                try:
                    # Если это относительный путь, проверяем локальный файл
                    if not image_url.startswith('http://') and not image_url.startswith('https://'):
                        # Это локальный файл — пробуем разные варианты путей
                        pm_images = get_user_data_dir() / "images"
                        possible_paths = [
                            image_url,
                            os.path.join(os.getcwd(), image_url),
                            os.path.abspath(image_url),
                        ]
                        if pm_images.exists():
                            possible_paths.append(str(pm_images / image_url))
                        
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
        self.publish_progress.setRange(0, max_posts)
        self.publish_progress.setValue(0)
        self.publish_log.clear()
        self.publish_log.append(f"Начало автопубликации: {max_posts} постов, интервал 30 сек, аккаунты по кругу...")
        
        # Режим браузера: из конфига (меню «Работать в фоне»), по умолчанию headless
        headless = self.parser_config.get('headless', True)
        self.auto_publish_thread = AutoPublishThread(
            account_boards,
            account_pins,
            account_links,
            account_csv_paths,
            max_posts,
            resolve_cookies_path,
            headless=headless,
            accounts=self.accounts,
        )
        self.auto_publish_thread.publish_progress.connect(self.on_auto_publish_progress)
        self.auto_publish_thread.publish_completed.connect(self.on_auto_publish_completed)
        self.auto_publish_thread.pin_published.connect(self._remove_published_row_from_csv)
        self.auto_publish_thread.publish_session_died.connect(self._on_publish_session_died)
        self.auto_publish_thread.start()
    
    def _remove_published_row_from_csv(self, published_link: str, csv_path_arg: str = ""):
        """Удаляет из указанного CSV (или текущего) строку с опубликованным изображением (по image_url или pin_link). В прод при разных CSV на аккаунт передаётся csv_path_arg."""
        csv_path = None
        if csv_path_arg and os.path.exists(csv_path_arg):
            csv_path = Path(csv_path_arg)
        if not csv_path:
            csv_path = getattr(self, "csv_file_path", None)
        if csv_path and isinstance(csv_path, str):
            csv_path = Path(csv_path) if os.path.exists(csv_path) else None
        if not csv_path or not csv_path.exists() or not published_link:
            return
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                fieldnames = reader.fieldnames or []
            if not rows or not fieldnames:
                return
            link_norm = (published_link or "").strip()
            remaining = [
                r for r in rows
                if (r.get('image_url') or '').strip() != link_norm and (r.get('pin_link') or '').strip() != link_norm
            ]
            if len(remaining) == len(rows):
                return
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(remaining)
            self.parsed_pins = remaining
            self._update_results_summary(remaining)
            if hasattr(self, 'csv_info_label'):
                self.csv_info_label.setText(f"Пинов в таблице: {len(remaining)} (опубликованные удалены)")
            logger.info(f"Из CSV удалена строка с ссылкой: {(published_link or '')[:60]}...")
        except Exception as e:
            logger.warning(f"Не удалось удалить строку из CSV: {e}")
    
    def on_auto_publish_progress(self, message: str):
        """Обработчик прогресса автопубликации"""
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
        # Обновляем прогресс-бар по формату "Пост i/total"
        if "/" in message:
            try:
                match = re.search(r'Пост\s+(\d+)/(\d+)', message)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    self.publish_progress.setMaximum(total)
                    self.publish_progress.setValue(current)
            except Exception:
                pass
    
    def _on_publish_session_died(self):
        """Сессия браузера прервана во время автопостинга — переинициализируем парсер; следующий пост возьмёт его через get_parser_fn()."""
        logger.info("Сессия браузера прервана при автопостинге — переинициализация парсера")
        self.publish_log.append("Сессия браузера прервана — переинициализация парсера...")
        self.statusBar().showMessage("Переинициализация парсера после обрыва сессии...")
        self.parser = None
        config = getattr(self, 'parser_config', {})
        headless = config.get('headless', True)
        download_images = config.get('download_images', True)
        self._init_parser_with_login(False, headless, download_images, None)
    
    def on_auto_publish_completed(self, success: bool, message: str):
        """Обработчик завершения автопубликации"""
        self.publish_progress.setVisible(False)
        self.start_auto_publish_btn.setEnabled(True)
        self.publish_log.append("")
        self.publish_log.append("=" * 50)
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
        
        if success:
            if self.toast_manager:
                self.toast_manager.show_success(message)
        else:
            if self.toast_manager:
                self.toast_manager.show_error(message)
    
    
    def _update_unique_btn_state(self):
        """Включает кнопку «Уникализировать все» только при подключённом ИИ API и наличии результатов."""
        if not hasattr(self, 'unique_results_btn'):
            return
        api_ok = bool((getattr(self, 'openrouter_api_key', None) or "").strip())
        has_pins = bool(getattr(self, 'parsed_pins', None)) and len(self.parsed_pins) > 0
        self.unique_results_btn.setEnabled(api_ok and has_pins)

    def unique_results_csv(self):
        """Уникализирует все названия и описания пинов из CSV результатов через OpenRouter API (один раз)."""
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
        
        # Тема парсинга: сначала из CSV (колонка search_query), потом last_parsing_query, потом история
        search_query = ''
        if pins_data:
            search_query = (pins_data[0].get('search_query') or '').strip()
        if not search_query:
            search_query = (getattr(self, 'last_parsing_query', None) or '').strip()
        if not search_query and csv_file:
            try:
                history_path = get_parsing_history_path()
                if history_path.exists():
                    with open(history_path, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                    csv_norm = os.path.normpath(os.path.abspath(csv_file))
                    for date in history.keys():
                        for entry in history.get(date, []):
                            ep = (entry.get('csv_path') or '').strip()
                            if ep and os.path.normpath(os.path.abspath(ep)) == csv_norm:
                                search_query = (entry.get('query') or '').strip()
                                if search_query:
                                    break
                        if search_query:
                            break
            except Exception:
                pass
        
        # Запускаем уникализацию в отдельном потоке
        class UniquePinsThread(QThread):
            progress = pyqtSignal(str)
            completed = pyqtSignal(str)
            error = pyqtSignal(str)
            tokens_used = pyqtSignal(int, float)  # токены, стоимость
            
            def __init__(self, api_key, pins_data, csv_file_path, search_query: str = ""):
                super().__init__()
                self.api_key = api_key
                self.pins_data = pins_data
                self.csv_file_path = csv_file_path
                self.search_query = (search_query or "").strip()
            
            def run(self):
                logger.info(f"UniquePinsThread: запуск уникализации, пинов: {len(self.pins_data)}, запрос: {self.search_query or '(нет)'}")
                try:
                    unique_pins = []
                    total = len(self.pins_data)
                    
                    for i, pin in enumerate(self.pins_data, 1):
                        title = (pin.get('title') or pin.get('Title') or '').strip()
                        description = (pin.get('description') or pin.get('Description') or '').strip()
                        
                        progress_label = (title[:50] + "...") if title else "пин без названия"
                        logger.debug(f"UniquePinsThread: уникализация {i}/{total}: {progress_label}")
                        self.progress.emit(f"Уникализация {i}/{total}: {progress_label}")
                        
                        # Уникализируем заголовок и описание отдельно для каждого пина (контекст «пин i из total» чтобы ИИ давал разный текст)
                        unique_title = self.unique_text(title, "заголовок", pin_index=i, total_pins=total)
                        unique_description = self.unique_text(description, "описание", pin_index=i, total_pins=total)
                        
                        # Создаем новый пин с уникализированными данными
                        unique_pin = pin.copy()
                        unique_pin['title'] = unique_title
                        unique_pin['description'] = unique_description
                        unique_pins.append(unique_pin)
                    
                    logger.info(f"UniquePinsThread: уникализация завершена, сохранение в файл {self.csv_file_path}...")
                    # Перезаписываем CSV с едиными ключами (включая search_query для будущей уникализации)
                    fieldnames = ['title', 'description', 'pin_link', 'image_url', 'author', 'board_name', 'board_url',
                        'repin_count', 'comments_disabled', 'saves', 'done', 'comment_count', 'likes', 'created_at', 'share_count', 'search_query']
                    with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as f:
                        if unique_pins:
                            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                            writer.writeheader()
                            for up in unique_pins:
                                row = {}
                                for k in fieldnames:
                                    v = up.get(k) or up.get(k.capitalize())
                                    if v is None:
                                        v = ''
                                    else:
                                        v = str(v).strip() if k in ('title', 'description') else str(v)
                                    row[k] = v
                                writer.writerow(row)
                    
                    logger.info(f"UniquePinsThread: файл сохранен, уникализировано {len(unique_pins)} пинов")
                    self.completed.emit(f"Уникализация завершена. Файл {os.path.basename(self.csv_file_path)} обновлен.")
                except ValueError as e:
                    if "OPENROUTER_402" in str(e):
                        msg = "На счёте OpenRouter недостаточно средств (402). Пополните баланс на openrouter.ai"
                        logger.warning("UniquePinsThread: %s", msg)
                        self.error.emit(msg)
                    else:
                        logger.error(f"UniquePinsThread: ошибка: {e}", exc_info=True)
                        self.error.emit(str(e))
                except Exception as e:
                    logger.error(f"UniquePinsThread: ошибка: {e}", exc_info=True)
                    self.error.emit(str(e))
            
            def unique_text(self, text: str, field_type: str, pin_index: int = 0, total_pins: int = 0) -> str:
                """Уникализирует текст через OpenRouter API для одного пина. pin_index/total_pins — чтобы каждый пин получил свой вариант, не один и тот же."""
                text = (text or "").strip()
                ctx = f" (пин {pin_index} из {total_pins} — текст должен отличаться от других пинов)" if total_pins > 1 else ""
                if not text:
                    if self.search_query:
                        theme = self.search_query.strip()
                        if field_type == "заголовок":
                            prompt = f"""Придумай один короткий заголовок для Pinterest (тема парсинга: «{theme}»). Одна короткая фраза, до 80 символов. Только по теме, без общих слов.{ctx} Ответь только заголовком, без кавычек."""
                        else:
                            prompt = f"""Придумай краткое описание для Pinterest (тема: «{theme}»). 1–2 коротких предложения, до 150 символов. Про тематику «{theme}».{ctx} Без кавычек."""
                        logger.debug(f"UniquePinsThread.unique_text: пустой {field_type}, генерация по теме: {self.search_query[:40]}...")
                    else:
                        if field_type == "заголовок":
                            prompt = f"""Придумай короткий привлекающий заголовок для Pinterest — одна фраза, до 80 символов.{ctx} Без кавычек."""
                        else:
                            prompt = f"""Придумай краткое описание для Pinterest — 1–2 предложения, до 150 символов.{ctx} Без кавычек."""
                        logger.debug(f"UniquePinsThread.unique_text: пустой {field_type}, генерация без темы")
                    # Выполняем запрос к API с промптом генерации
                    try:
                        response = requests.post(
                            url="https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "mistralai/mistral-nemo",
                                "messages": [{"role": "user", "content": prompt}]
                            },
                            timeout=30
                        )
                        if response.status_code == 402:
                            logger.warning("UniquePinsThread.unique_text: на счёте OpenRouter недостаточно средств (402)")
                            raise ValueError("OPENROUTER_402_PAYMENT_REQUIRED")
                        response.raise_for_status()
                        result = response.json()
                        out = result['choices'][0]['message']['content'].strip().strip('"\'')
                        max_len = 80 if field_type == "заголовок" else 150
                        if len(out) > max_len:
                            out = out[:max_len]
                            if out and out[-1] not in ' \t':
                                out = (out.rsplit(maxsplit=1)[0] or out)
                        usage = result.get('usage', {})
                        total_tokens = usage.get('total_tokens', usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0))
                        cost_per_1k = 0.0001
                        cost = (total_tokens / 1000.0) * cost_per_1k
                        self.tokens_used.emit(total_tokens, cost)
                        return out
                    except ValueError as e:
                        if "OPENROUTER_402" in str(e):
                            raise
                        logger.error(f"UniquePinsThread.unique_text: ошибка генерации {field_type}: {e}", exc_info=True)
                        return ""
                    except Exception as e:
                        logger.error(f"UniquePinsThread.unique_text: ошибка генерации {field_type}: {e}", exc_info=True)
                        return ""
                
                logger.debug(f"UniquePinsThread.unique_text: уникализация {field_type}, длина текста: {len(text)}")
                length_hint = "Заголовок: одна короткая фраза, до 80 символов." if field_type == "заголовок" else "Описание: 1–2 коротких предложения, до 150 символов."
                prompt = f"""Перепиши {field_type} для Pinterest: уникально и по смыслу как оригинал, но коротко. {length_hint} Синонимы и перефразирование. Это пин {pin_index} из {total_pins} — формулировка должна отличаться от других пинов.{ctx}
Ответь только переписанным текстом, без кавычек и пояснений.

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
                    if response.status_code == 402:
                        logger.warning("UniquePinsThread.unique_text: на счёте OpenRouter недостаточно средств (402)")
                        raise ValueError("OPENROUTER_402_PAYMENT_REQUIRED")
                    response.raise_for_status()
                    result = response.json()
                    unique_text = result['choices'][0]['message']['content'].strip().strip('"\'')
                    max_len = 80 if field_type == "заголовок" else 150
                    if len(unique_text) > max_len:
                        unique_text = unique_text[:max_len]
                        if unique_text and unique_text[-1] not in ' \t':
                            unique_text = (unique_text.rsplit(maxsplit=1)[0] or unique_text)
                    
                    usage = result.get('usage', {})
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)
                    total_tokens = usage.get('total_tokens', prompt_tokens + completion_tokens)
                    cost_per_1k = 0.0001
                    cost = (total_tokens / 1000.0) * cost_per_1k
                    logger.debug(f"UniquePinsThread.unique_text: {field_type} уникализирован, токены: {total_tokens}, стоимость: ${cost:.6f}")
                    self.tokens_used.emit(total_tokens, cost)
                    return unique_text
                except ValueError as e:
                    if "OPENROUTER_402" in str(e):
                        raise
                    logger.error(f"UniquePinsThread.unique_text: ошибка при уникализации {field_type}: {e}", exc_info=True)
                    return text
                except Exception as e:
                    logger.error(f"UniquePinsThread.unique_text: ошибка при уникализации {field_type}: {e}", exc_info=True)
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
                self._update_unique_btn_state()
                return
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show_error(f"Не удалось прочитать CSV файл: {e}")
            self._update_unique_btn_state()
            return
        
        self.unique_thread = UniquePinsThread(api_key, pins_data, csv_file, search_query)
        self.unique_thread.progress.connect(self.on_unique_progress)
        self.unique_thread.completed.connect(self.on_unique_completed)
        self.unique_thread.error.connect(self.on_unique_error)
        self.unique_thread.tokens_used.connect(self.on_tokens_used)
        self.unique_thread.finished.connect(self._update_unique_btn_state)
        self.unique_thread.start()
    
    def on_unique_progress(self, message: str):
        """Обработчик прогресса уникализации"""
        self.statusBar().showMessage(message)
    
    def _mark_csv_unique_in_history(self, csv_path: str):
        """Помечает запись в истории парсингов по csv_path как уникализированную."""
        if not csv_path or not os.path.exists(csv_path):
            return
        try:
            history_path = get_parsing_history_path()
            if not history_path.exists():
                return
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            csv_norm = os.path.normpath(os.path.abspath(csv_path))
            for date in history.keys():
                for entry in history.get(date, []):
                    ep = (entry.get('csv_path') or '').strip()
                    if ep and os.path.normpath(os.path.abspath(ep)) == csv_norm:
                        entry['unique'] = True
                        with open(history_path, 'w', encoding='utf-8') as f:
                            json.dump(history, f, indent=2, ensure_ascii=False)
                        self._load_parsing_history()
                        return
        except Exception as e:
            logger.warning(f"_mark_csv_unique_in_history: {e}")

    def on_unique_completed(self, message: str):
        """Обработчик завершения уникализации"""
        self.statusBar().showMessage(message)
        if self.toast_manager:
            self.toast_manager.show_success(message)
        if self.csv_file_path:
            self._mark_csv_unique_in_history(self.csv_file_path)
        # Обновляем информацию о файле
        if self.csv_file_path:
            self.csv_info_label.setText(f"CSV файл: {os.path.basename(self.csv_file_path)} (уникализирован)")
        # Перезагружаем parsed_pins из CSV и обновляем сетку — чтобы при публикации использовались уникализированные title/description
        if self.csv_file_path and os.path.exists(self.csv_file_path):
            try:
                with open(self.csv_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.parsed_pins = self._pins_with_image(list(reader))
                self._update_results_summary(self.parsed_pins)
                if hasattr(self, 'pins_list_widget') and self.pins_list_widget:
                    self.pins_list_widget.blockSignals(True)
                    self.pins_list_widget.clear()
                    for i, pin in enumerate(self.parsed_pins):
                        title = (pin.get('title') or pin.get('Title') or '').strip() or 'Без названия'
                        if len(title) > 60:
                            title = title[:57] + "..."
                        item = QListWidgetItem(f"{i+1}. {title}")
                        item.setData(Qt.ItemDataRole.UserRole, i)
                        item.setCheckState(Qt.CheckState.Unchecked)
                        self.pins_list_widget.addItem(item)
                    self.pins_list_widget.blockSignals(False)
                if getattr(self, 'publish_current_csv_path', None) and os.path.normpath(self.csv_file_path) == os.path.normpath(self.publish_current_csv_path):
                    self.publish_current_pins_data = self.parsed_pins
                logger.info(f"После уникализации перезагружено {len(self.parsed_pins)} пинов из CSV")
            except Exception as e:
                logger.warning(f"Не удалось перезагрузить пины после уникализации: {e}")
    
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
        """Обновляет отображение списка пинов (фильтры убраны)"""
        if not hasattr(self, 'parsed_pins') or not self.parsed_pins:
            return
        try:
            self._update_results_summary(self.parsed_pins)
        except Exception as e:
            logger.error(f"_apply_filters: ошибка при обновлении отображения: {e}", exc_info=True)
    
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
            
            # Только пины с изображением
            pins_data = self._pins_with_image(pins_data)
            self.parsed_pins = pins_data
            self.csv_file_path = path
            query_from_csv = (pins_data[0].get('search_query') or '').strip() if pins_data else ''
            self._ensure_csv_in_history(path, query=query_from_csv or 'Импорт', pins_count=len(pins_data))
            
            # Обновляем интерфейс
            self._update_results_summary(pins_data)
            
            if hasattr(self, 'csv_info_label'):
                self.csv_info_label.setText(f"Импортировано пинов: {len(pins_data)} | Файл: {os.path.basename(path)}")
                self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
            self._update_results_path_display()
            
            if hasattr(self, 'unique_results_btn'):
                self._update_unique_btn_state()
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
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Экспортировать в Excel",
                str(get_csv_dir()),
                "Excel файлы (*.xlsx);;Все файлы (*)"
            )
            if not path:
                return
            
            try:
                from openpyxl import Workbook
            except ImportError:
                if self.toast_manager:
                    self.toast_manager.show_error("Для экспорта в Excel требуется библиотека openpyxl.\nУстановите: pip install openpyxl")
                return
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
                'time': datetime.now().strftime("%H:%M:%S"),
                'unique': False,
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
    
    def _ensure_csv_in_history(self, csv_path: str, query: str = "", pins_count: int = 0):
        """Добавляет CSV в историю парсингов, если его там ещё нет (чтобы в «Истории» были записи при загрузке/импорте)."""
        if not csv_path or not os.path.exists(csv_path):
            return
        try:
            from datetime import datetime
            history_path = get_parsing_history_path()
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            csv_norm = os.path.normpath(os.path.abspath(csv_path))
            for date in history.keys():
                for entry in history.get(date, []):
                    ep = (entry.get('csv_path') or '').strip()
                    if ep and os.path.normpath(os.path.abspath(ep)) == csv_norm:
                        return
            query = (query or "").strip() or "Загруженный файл"
            if pins_count <= 0 and hasattr(self, 'parsed_pins') and self.parsed_pins:
                pins_count = len(self.parsed_pins)
            current_date = datetime.now().strftime("%Y-%m-%d")
            if current_date not in history:
                history[current_date] = []
            entry = {
                'query': query,
                'pins_count': pins_count,
                'csv_path': csv_path,
                'timestamp': datetime.now().isoformat(),
                'time': datetime.now().strftime("%H:%M:%S"),
                'unique': False,
            }
            history[current_date].append(entry)
            if len(history[current_date]) > 100:
                history[current_date] = history[current_date][-100:]
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            self._load_parsing_history()
        except Exception as e:
            logger.debug(f"_ensure_csv_in_history: {e}")
    
    def _load_parsing_history(self):
        """Загружает историю парсингов из файла и обновляет список (вкладка Результаты) и _all_history_entries для комбо на вкладке Автопостинг."""
        logger.debug("_load_parsing_history: начало загрузки истории...")
        try:
            logger.debug("_load_parsing_history: чтение файла истории...")
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                logger.debug(f"_load_parsing_history: история загружена, дат: {len(history)}")
            else:
                logger.debug("_load_parsing_history: файл истории не существует")
            # Один плоский список: все парсинги по всем датам (новые сверху)
            all_entries = []
            for date in sorted(history.keys(), reverse=True):
                for entry in history.get(date, []):
                    all_entries.append({**entry, '_date': date})
            # Всегда обновляем кэш для комбо «Результат» на вкладке Автопостинг
            self._all_history_entries = all_entries.copy()
            if hasattr(self, 'history_list'):
                self._update_history_list(all_entries)
            logger.debug("_load_parsing_history: загрузка истории завершена успешно")
        except Exception as e:
            logger.error(f"_load_parsing_history: ошибка при загрузке истории парсинга: {e}", exc_info=True)
            print(f"Ошибка при загрузке истории парсинга: {e}")
    
    def _update_history_list(self, entries: list):
        """Обновляет список парсингов на вкладке Результаты (один список без даты)."""
        logger.debug(f"_update_history_list: записей: {len(entries)}")
        try:
            if not hasattr(self, 'history_list'):
                return
            self._all_history_entries = entries.copy()
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
            
            # Добавляем отфильтрованные записи (дата в тексте + пометка уникализации)
            for entry in reversed(filtered_entries):  # Новые первыми
                date = entry.get('_date', '')
                query = entry.get('query', 'Неизвестно')
                pins_count = entry.get('pins_count', 0)
                time = entry.get('time', '')
                unique = entry.get('unique', False)
                unique_label = " | Уникализировано" if unique else " | Не уникализировано"
                item_text = (f"{date} {time} | {query} | {pins_count} пинов" if date else f"{time} | {query} | {pins_count} пинов") + unique_label
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.history_list.addItem(item)
            
            # Восстанавливаем выделение записи, соответствующей текущему CSV (чтобы не пропадало после перезагрузки списка)
            csv_path = getattr(self, 'csv_file_path', None)
            if csv_path and os.path.exists(csv_path):
                csv_norm = os.path.normpath(os.path.abspath(csv_path))
                for i in range(self.history_list.count()):
                    item = self.history_list.item(i)
                    entry = item.data(Qt.ItemDataRole.UserRole) if item else None
                    if entry:
                        ep = (entry.get('csv_path') or '').strip()
                        if ep and os.path.normpath(os.path.abspath(ep)) == csv_norm:
                            self.history_list.setCurrentItem(item)
                            break
            
            logger.debug(f"_filter_history: отфильтровано {len(filtered_entries)} из {len(self._all_history_entries)} записей")
        except Exception as e:
            logger.error(f"_filter_history: ошибка при фильтрации истории: {e}", exc_info=True)
    
    def _remove_entry_from_history(self, entry: dict):
        """Удаляет одну запись из файла истории (по csv_path и time). Используется для очистки устаревших записей."""
        try:
            csv_path = (entry.get('csv_path') or '').strip()
            time_val = entry.get('time', '')
            date = entry.get('_date', '')
            history_path = get_parsing_history_path()
            if not history_path.exists():
                return
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            if date:
                if date not in history:
                    return
                new_entries = [
                    e for e in history[date]
                    if (e.get('csv_path') or '').strip() != csv_path or (e.get('time') or '') != time_val
                ]
                if len(new_entries) == len(history[date]):
                    return
                history[date] = new_entries
                if not history[date]:
                    del history[date]
            else:
                for d in list(history.keys()):
                    new_entries = [
                        e for e in history[d]
                        if (e.get('csv_path') or '').strip() != csv_path or (e.get('time') or '') != time_val
                    ]
                    if len(new_entries) < len(history[d]):
                        history[d] = new_entries
                        if not history[d]:
                            del history[d]
                        break
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            self._load_parsing_history()
        except Exception as e:
            logger.warning(f"_remove_entry_from_history: {e}")
    
    def _load_parsing_from_entry(self, entry: dict):
        """Загружает парсинг из записи истории"""
        logger.debug("_load_parsing_from_entry: загрузка парсинга из записи...")
        try:
            csv_path = entry.get('csv_path', '')
            if not csv_path or not os.path.exists(csv_path):
                logger.warning(f"_load_parsing_from_entry: CSV файл не найден: {csv_path}")
                self._remove_entry_from_history(entry)
                return False
            
            # Загружаем данные из CSV
            logger.debug(f"_load_parsing_from_entry: чтение CSV файла {csv_path}...")
            pins_data = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                logger.warning("_load_parsing_from_entry: CSV файл пуст")
                self._remove_entry_from_history(entry)
                return False
            
            pins_data = self._pins_with_image(pins_data)
            logger.debug(f"_load_parsing_from_entry: загружено {len(pins_data)} пинов (только с изображением)")
            self.parsed_pins = pins_data
            self.csv_file_path = csv_path
            
            # Обновляем сводку результатов
            try:
                self._update_results_summary(pins_data)
            except Exception as e:
                logger.error(f"_load_parsing_from_entry: ошибка при обновлении сводки: {e}", exc_info=True)
            
            self.last_parsing_query = (entry.get('query') or '').strip()  # для уникализации пустых пинов
            pins_count = entry.get('pins_count', len(pins_data))
            
            # Обновляем информацию о CSV
            if hasattr(self, 'csv_info_label'):
                try:
                    self.csv_info_label.setText(f"Найдено пинов: {pins_count} | CSV файл: {os.path.basename(csv_path)}")
                    self.csv_info_label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
                except Exception as e:
                    logger.error(f"_load_parsing_from_entry: ошибка при обновлении csv_info_label: {e}", exc_info=True)
            self._update_results_path_display()
            
            # Включаем кнопки
            if hasattr(self, 'unique_results_btn'):
                try:
                    self._update_unique_btn_state()
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
    
    def _show_history_list_context_menu(self, pos):
        """Показывает контекстное меню по правому клику на записи в списке результатов."""
        item = self.history_list.itemAt(pos)
        if item:
            self.history_list.setCurrentItem(item)
        menu = QMenu(self)
        delete_action = menu.addAction("Удалить запись")
        delete_action.triggered.connect(self._delete_selected_history_entry)
        menu.exec(self.history_list.mapToGlobal(pos))

    def _delete_selected_history_entry(self):
        """Удаляет выбранную запись парсинга из истории (общий парсинг, не карточки)."""
        if not hasattr(self, 'history_list'):
            return
        item = self.history_list.currentItem()
        if not item:
            if self.toast_manager:
                self.toast_manager.show_warning("Выберите запись в списке истории")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        date = entry.get('_date', '')
        csv_path = (entry.get('csv_path') or '').strip()
        time_val = entry.get('time', '')
        try:
            history_path = get_parsing_history_path()
            history = {}
            if history_path.exists():
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            if date not in history:
                return
            # Удаляем запись, совпадающую по csv_path и time
            new_entries = [
                e for e in history[date]
                if (e.get('csv_path') or '').strip() != csv_path or (e.get('time') or '') != time_val
            ]
            if len(new_entries) == len(history[date]):
                return
            history[date] = new_entries
            if not history[date]:
                del history[date]
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            # Если удалили запись, которая сейчас загружена — очищаем карточки и данные (нормализуем пути)
            deleted_norm = os.path.normpath(os.path.abspath(csv_path)) if csv_path else ""
            current_norm = os.path.normpath(os.path.abspath(self.csv_file_path or "")) if getattr(self, "csv_file_path", None) else ""
            if deleted_norm and current_norm and deleted_norm == current_norm:
                self.parsed_pins = []
                self.csv_file_path = None
                self._update_results_summary([])
                self._update_results_path_display()
                if hasattr(self, "csv_info_label"):
                    self.csv_info_label.setText("CSV не создан")
                if getattr(self, "publish_current_csv_path", None) and os.path.normpath(os.path.abspath(self.publish_current_csv_path)) == current_norm:
                    self.publish_current_pins_data = []
                    self.publish_current_csv_path = None
                if hasattr(self, "pins_list_widget") and self.pins_list_widget:
                    self.pins_list_widget.clear()
                self._update_unique_btn_state()
            self._load_parsing_history()
            self.statusBar().showMessage("Парсинг удалён из истории")
            if self.toast_manager:
                self.toast_manager.show_success("Запись удалена из истории")
        except Exception as e:
            logger.warning(f"Не удалось удалить запись из истории: {e}")
            if self.toast_manager:
                self.toast_manager.show_error(f"Ошибка: {e}")
    
    def on_history_item_selected(self, item: QListWidgetItem):
        """Обработчик выбора парсинга из истории"""
        if item and hasattr(self, 'history_list'):
            self.history_list.setCurrentItem(item)  # явно фиксируем выбор, чтобы удаление работало
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not entry:
            return
        
        if not self._load_parsing_from_entry(entry):
            if self.toast_manager:
                self.toast_manager.show_error("Не удалось загрузить парсинг")
            return
        
        query = entry.get('query', 'Неизвестно')
        pins_count = entry.get('pins_count', 0)
        
        # Переключаемся на страницу результатов
        self.show_page("results")
        
        self.statusBar().showMessage(f"Загружен парсинг: {query} ({pins_count} пинов)")
    
    def _load_publish_history(self):
        """Загружает историю парсингов для вкладки автопубликации (отключено при упрощённой публикации)."""
        try:
            if not hasattr(self, 'publish_date_combo') or getattr(self, 'publish_date_combo', None) is None:
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
        if not hasattr(self, 'publish_parsing_combo'):
            return
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
        if not hasattr(self, 'publish_parsing_combo'):
            return
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
        if not hasattr(self, 'pins_list_widget'):
            return
        self._update_selected_pins_count()
    
    def _select_pins(self, select_all: bool):
        """Выбирает или снимает выбор со всех пинов"""
        if not hasattr(self, 'pins_list_widget'):
            return
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
        if not hasattr(self, 'pins_list_widget') or not hasattr(self, 'selected_pins_count_label'):
            return
        selected_count = 0
        self.publish_selected_pins = []
        
        for i in range(self.pins_list_widget.count()):
            item = self.pins_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_count += 1
                pin_index = item.data(Qt.ItemDataRole.UserRole)
                self.publish_selected_pins.append(pin_index)
        
        self.selected_pins_count_label.setText(f"Выбрано: {selected_count}")


def main():
    """Точка входа: создаёт QApplication и главное окно."""
    from PyQt6.QtWidgets import QApplication, QMessageBox
    import traceback

    logger.info("=" * 80)
    logger.info("ТОЧКА ВХОДА: Запуск приложения")
    logger.info("=" * 80)

    try:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
        app = QApplication(sys.argv)
        app.setApplicationName("PinMaster")
        app.setApplicationDisplayName("PinMaster")
        app.setStyle("Fusion")
        window = PinterestMainWindow()
        window.showMaximized()
        QTimer.singleShot(100, window.load_styles)
        def lock_window_size():
            window.setMinimumSize(window.size())
            window.setMaximumSize(window.size())
        QTimer.singleShot(50, lock_window_size)
        exit_code = app.exec()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА при запуске: %s", e, exc_info=True)
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Ошибка запуска")
            msg.setText("Не удалось запустить приложение:\n%s" % str(e))
            msg.setDetailedText(traceback.format_exc())
            msg.exec()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
