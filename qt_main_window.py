"""
Главное окно Qt-приложения для парсера Pinterest.
Информация об аккаунте отображается в главном меню/окне.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox,
    QStatusBar, QMenuBar, QMenu, QMessageBox, QSplitter,
    QComboBox, QFileDialog, QProgressBar, QListWidget, QListWidgetItem,
    QDialog, QSpinBox, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QFile, QTextStream, QTimer
import requests
import csv
import re
from PyQt6.QtGui import QFont, QIcon, QAction
from typing import Optional, Dict, List
import json
import os

from pinterest_selenium_parser import PinterestSeleniumParser
from cache_manager import CacheManager
from pinterest_publisher import PinterestPublisher
from path_utils import (
    get_config_path, get_cookies_path, get_images_dir,
    get_csv_dir, get_styles_path, get_app_name,
)


class AccountInfoWidget(QGroupBox):
    """Виджет для отображения информации об аккаунте"""
    
    def __init__(self, parent=None):
        super().__init__("Авторизованный аккаунт", parent)
        self.setup_ui()
        self.account_info = None
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # Статус авторизации
        self.status_label = QLabel("Статус: Не авторизован")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #8e8e93;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 0px;
            }
        """)
        layout.addWidget(self.status_label)
        
        # Имя пользователя (крупно и заметно)
        self.username_label = QLabel("Не авторизован")
        self.username_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        self.username_label.setStyleSheet("""
            QLabel {
                color: #1d1d1f;
                padding: 8px 0px;
            }
        """)
        layout.addWidget(self.username_label)
        
        # Display name если есть
        self.display_name_label = QLabel("")
        self.display_name_label.setFont(QFont("Arial", 14))
        self.display_name_label.setStyleSheet("color: #6e6e73; padding: 4px 0px;")
        self.display_name_label.hide()
        layout.addWidget(self.display_name_label)
        
        # Разделитель
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #e5e5e7;")
        layout.addWidget(separator)
        
        # Дополнительная информация
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            QLabel {
                color: #6e6e73;
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
                color: #007aff;
                font-size: 11px;
                padding: 4px 0px;
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
            
            # Обновляем статус
            self.status_label.setText("Статус: Авторизован")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #e0e0e0;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 4px 0px;
                }
            """)
            
            # Обновляем имя пользователя
            self.username_label.setText(f"@{username}")
            self.username_label.setStyleSheet("""
                QLabel {
                    color: #e0e0e0;
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
            self.status_label.setText("Статус: Не авторизован")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #666666;
                    font-size: 11px;
                    font-weight: 500;
                    padding: 4px 0px;
                }
            """)
            
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


class AccountInfoThread(QThread):
    """Поток для получения информации об аккаунте и парсинга пинов/досок"""
    
    account_info_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, parser: PinterestSeleniumParser):
        super().__init__()
        self.parser = parser
    
    def run(self):
        try:
            # Проверяем что парсер доступен
            if not self.parser or not self.parser.driver:
                self.error_occurred.emit("Парсер не инициализирован")
                return
            
            # Получаем базовую информацию об аккаунте
            try:
                account_info = self.parser.get_account_info()
            except Exception as e:
                self.error_occurred.emit(f"Ошибка при получении информации об аккаунте: {str(e)}")
                return
                
            if not account_info:
                self.error_occurred.emit("Не удалось получить информацию об аккаунте")
                return
            
            username = account_info.get('username')
            if not username:
                self.error_occurred.emit("Не удалось определить имя пользователя")
                return
            
            # Парсим доски пользователя (с проверкой кэша)
            try:
                # Сначала проверяем кэш
                boards = CacheManager.load_boards(username)
                if boards is None:
                    # Кэша нет или он устарел - парсим заново
                    print(f"Кэш досок для {username} не найден или устарел, парсим...")
                    boards = self.parser.parse_user_boards(username=username)
                    if boards:
                        # Сохраняем в кэш
                        CacheManager.save_boards(username, boards)
                else:
                    print(f"Используем кэш досок для {username}")
                
                if boards:
                    account_info['boards_count'] = f"{len(boards)} досок"
                    account_info['boards'] = boards
                else:
                    account_info['boards_count'] = "0 досок"
                    account_info['boards'] = []
            except Exception as e:
                print(f"Ошибка при парсинге досок: {e}")
                account_info['boards_count'] = "Ошибка"
                account_info['boards'] = []
            
            # Парсим пины пользователя (ограничиваем до 10 для быстрой загрузки, с проверкой кэша)
            try:
                # Сначала проверяем кэш
                pins = CacheManager.load_pins(username)
                if pins is None:
                    # Кэша нет или он устарел - парсим заново
                    print(f"Кэш пинов для {username} не найден или устарел, парсим...")
                    pins = self.parser.parse_user_pins(username=username, max_pins=10)
                    if pins:
                        # Сохраняем в кэш
                        CacheManager.save_pins(username, pins)
                else:
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
                print(f"Ошибка при парсинге пинов: {e}")
                account_info['pins_count'] = "Ошибка"
                account_info['pins'] = []
            
            self.account_info_ready.emit(account_info)
            
        except Exception as e:
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
    
    def run(self):
        """Инициализирует парсер и ждет завершения логина"""
        print("\n" + "=" * 80)
        print("ИНИЦИАЛИЗАЦИЯ ПАРСЕРА В ПОТОКЕ")
        print("=" * 80)
        print(f"enable_login: {self.enable_login}")
        print(f"headless: {self.headless}")
        print(f"download_images: {self.download_images}")
        print("=" * 80 + "\n")
        
        try:
            # Инициализируем парсер (это может занять время, особенно при логине)
            print("Создание PinterestSeleniumParser...")
            parser = PinterestSeleniumParser(
                headless=self.headless,
                download_images=self.download_images,
                auto_login=self.enable_login
            )
            
            print("✓ Парсер создан успешно")
            
            # Проверяем что драйвер создан
            if not parser.driver:
                raise RuntimeError("Chrome драйвер не был создан после инициализации парсера")
            
            print("✓ Chrome драйвер доступен")
            
            # Если был включен логин, парсер уже дождался его завершения в _ensure_authentication
            # Отправляем сигнал о готовности парсера
            print("Отправка сигнала parser_ready...")
            self.parser_ready.emit(parser)
            print("✓ Сигнал parser_ready отправлен")
            
            # Если был логин, отправляем сигнал о его завершении
            if self.enable_login:
                print("Отправка сигнала login_completed...")
                self.login_completed.emit()
                print("✓ Сигнал login_completed отправлен")
            
            print("\n✓ Инициализация парсера завершена успешно\n")
                
        except RuntimeError as e:
            # Ошибка инициализации драйвера - отправляем специальный сигнал
            error_msg = str(e)
            print(f"\n❌ ОШИБКА при инициализации парсера (RuntimeError): {error_msg}")
            import traceback
            print("\nПолный traceback:")
            traceback.print_exc()
            # Отправляем ошибку через сигнал
            if hasattr(self, 'error_occurred'):
                self.error_occurred.emit(error_msg)
        except Exception as e:
            error_msg = str(e)
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
    
    def run(self):
        """Выполняет парсинг поиска"""
        try:
            self.parse_progress.emit(f"Начинаем парсинг: {self.query}")
            
            # Парсим результаты поиска
            pins = self.parser.parse_search_page(self.query, max_pins=self.max_pins)
            
            if pins:
                self.parse_progress.emit(f"Найдено пинов: {len(pins)}")
                self.parse_completed.emit(pins)
            else:
                self.parse_error.emit("Пины не найдены")
                
        except Exception as e:
            error_msg = f"Ошибка при парсинге: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.parse_error.emit(error_msg)


class PinterestMainWindow(QMainWindow):
    """Главное окно приложения"""
    
    def __init__(self):
        super().__init__()
        self.parser: Optional[PinterestSeleniumParser] = None
        self.account_info_thread: Optional[AccountInfoThread] = None
        self.search_parse_thread: Optional[SearchParseThread] = None
        self.parsed_pins: List[Dict] = []  # Сохраняем результаты парсинга
        self.csv_file_path: Optional[str] = None  # Путь к CSV файлу результатов
        self.openrouter_api_key: Optional[str] = None  # API ключ OpenRouter
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.setup_ui()
        self.setup_tray_icon()
        self.load_config()
    
    def setup_ui(self):
        self.setWindowTitle(get_app_name())
        self.setMinimumSize(1000, 700)
        
        # Загружаем стили
        self.load_styles()
        
        # Создаем главный splitter для сайдбара и центральной области
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)
        
        # === САЙДБАР ===
        sidebar_widget = QWidget()
        sidebar_widget.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(16, 20, 16, 20)
        sidebar_layout.setSpacing(12)
        
        # Заголовок сайдбара
        sidebar_title = QLabel("Навигация")
        sidebar_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        sidebar_layout.addWidget(sidebar_title)
        
        sidebar_layout.addSpacing(8)
        
        # Индикатор статуса авторизации
        self.auth_status_widget = QWidget()
        auth_status_layout = QVBoxLayout()
        auth_status_layout.setContentsMargins(0, 0, 0, 0)
        auth_status_layout.setSpacing(4)
        
        self.auth_status_label = QLabel("Не авторизован")
        self.auth_status_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
                background-color: #2a2a2a;
                border-radius: 6px;
            }
        """)
        auth_status_layout.addWidget(self.auth_status_label)
        
        self.auth_username_label = QLabel("")
        self.auth_username_label.setStyleSheet("""
            QLabel {
                color: #e0e0e0;
                font-size: 12px;
                font-weight: 600;
                padding: 2px 8px;
            }
        """)
        self.auth_username_label.hide()
        auth_status_layout.addWidget(self.auth_username_label)
        
        self.auth_status_widget.setLayout(auth_status_layout)
        sidebar_layout.addWidget(self.auth_status_widget)
        
        sidebar_layout.addSpacing(12)
        
        # Кнопки навигации в сайдбаре
        self.account_btn = QPushButton("Аккаунт")
        self.account_btn.setObjectName("sidebarButton")
        self.account_btn.setCheckable(True)
        self.account_btn.setChecked(True)
        self.account_btn.clicked.connect(lambda: self.show_page("account"))
        sidebar_layout.addWidget(self.account_btn)
        
        self.parse_btn = QPushButton("Парсинг")
        self.parse_btn.setObjectName("sidebarButton")
        self.parse_btn.setCheckable(True)
        self.parse_btn.clicked.connect(lambda: self.show_page("parse"))
        sidebar_layout.addWidget(self.parse_btn)
        
        self.results_btn = QPushButton("Результаты")
        self.results_btn.setObjectName("sidebarButton")
        self.results_btn.setCheckable(True)
        self.results_btn.clicked.connect(lambda: self.show_page("results"))
        sidebar_layout.addWidget(self.results_btn)
        
        self.publish_btn = QPushButton("Автопубликация")
        self.publish_btn.setObjectName("sidebarButton")
        self.publish_btn.setCheckable(True)
        self.publish_btn.clicked.connect(lambda: self.show_page("publish"))
        sidebar_layout.addWidget(self.publish_btn)
        
        sidebar_layout.addStretch()
        
        sidebar_widget.setLayout(sidebar_layout)
        main_splitter.addWidget(sidebar_widget)
        
        # === ЦЕНТРАЛЬНАЯ ОБЛАСТЬ ===
        central_area = QWidget()
        central_area.setObjectName("centralArea")
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        central_area.setLayout(main_layout)
        
        # === СТРАНИЦА АККАУНТА ===
        self.account_page = QWidget()
        account_layout = QVBoxLayout()
        account_layout.setSpacing(16)
        self.account_info_widget = AccountInfoWidget()
        account_layout.addWidget(self.account_info_widget)
        account_layout.addStretch()
        self.account_page.setLayout(account_layout)
        
        # === СТРАНИЦА ПАРСИНГА ===
        self.parse_page = QWidget()
        parse_layout = QVBoxLayout()
        parse_layout.setSpacing(16)
        
        functions_group = QGroupBox("Парсинг")
        functions_layout = QVBoxLayout()
        functions_layout.setSpacing(12)
        
        search_layout = QHBoxLayout()
        search_layout.setSpacing(12)
        search_layout.addWidget(QLabel("Тематика:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("например: python programming")
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("Парсить")
        self.search_btn.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.search_btn)
        functions_layout.addLayout(search_layout)
        
        # Количество пинов
        count_layout = QHBoxLayout()
        count_layout.setSpacing(12)
        count_layout.addWidget(QLabel("Количество пинов:"))
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
        
        # === СТРАНИЦА РЕЗУЛЬТАТОВ ===
        self.results_page = QWidget()
        results_layout = QVBoxLayout()
        results_layout.setSpacing(16)
        
        results_group = QGroupBox("Результаты парсинга (CSV таблица)")
        results_group_layout = QVBoxLayout()
        results_group_layout.setSpacing(12)
        
        # Информация о CSV файле
        self.csv_info_label = QLabel("CSV файл не создан")
        self.csv_info_label.setStyleSheet("color: #999999;")
        results_group_layout.addWidget(self.csv_info_label)
        
        # Текстовая область для отображения информации
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        results_group_layout.addWidget(self.results_text)
        
        # Кнопки: уникализация и экспорт
        results_buttons_layout = QHBoxLayout()
        results_buttons_layout.setSpacing(12)
        self.unique_results_btn = QPushButton("Уникализировать результаты")
        self.unique_results_btn.clicked.connect(self.unique_results_csv)
        self.unique_results_btn.setEnabled(False)
        results_buttons_layout.addWidget(self.unique_results_btn)
        self.export_csv_btn = QPushButton("Экспортировать CSV")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setToolTip("Сохранить копию CSV в выбранную папку")
        results_buttons_layout.addWidget(self.export_csv_btn)
        results_buttons_layout.addStretch()
        results_group_layout.addLayout(results_buttons_layout)
        
        results_group.setLayout(results_group_layout)
        results_layout.addWidget(results_group)
        self.results_page.setLayout(results_layout)
        
        # === СТРАНИЦА АВТОПУБЛИКАЦИИ ===
        self.publish_page = QWidget()
        publish_layout = QVBoxLayout()
        publish_layout.setSpacing(16)
        
        publish_group = QGroupBox("Автопубликация из CSV результатов")
        publish_group_layout = QVBoxLayout()
        publish_group_layout.setSpacing(12)
        
        # Информация о CSV файле
        csv_info_layout = QVBoxLayout()
        csv_info_layout.setSpacing(4)
        csv_info_layout.addWidget(QLabel("CSV файл результатов:"))
        self.publish_csv_info = QLabel("CSV файл не найден. Сначала выполните парсинг.")
        self.publish_csv_info.setStyleSheet("color: #999999;")
        csv_info_layout.addWidget(self.publish_csv_info)
        publish_group_layout.addLayout(csv_info_layout)
        
        # Ссылка
        link_layout = QHBoxLayout()
        link_layout.setSpacing(12)
        link_layout.addWidget(QLabel("Ссылка:"))
        self.pin_link_input = QLineEdit()
        self.pin_link_input.setPlaceholderText("https://example.com")
        link_layout.addWidget(self.pin_link_input)
        publish_group_layout.addLayout(link_layout)
        
        # Доска
        board_layout = QHBoxLayout()
        board_layout.setSpacing(12)
        board_layout.addWidget(QLabel("Доска:"))
        self.board_combo = QComboBox()
        self.board_combo.setPlaceholderText("Загрузка досок...")
        board_layout.addWidget(self.board_combo)
        self.refresh_boards_btn = QPushButton("Обновить")
        self.refresh_boards_btn.clicked.connect(self.load_boards)
        board_layout.addWidget(self.refresh_boards_btn)
        publish_group_layout.addLayout(board_layout)
        
        # Кнопка запуска автопубликации
        self.start_auto_publish_btn = QPushButton("Запустить автопубликацию")
        self.start_auto_publish_btn.clicked.connect(self.start_auto_publish)
        publish_group_layout.addWidget(self.start_auto_publish_btn)
        
        # Прогресс бар
        self.publish_progress = QProgressBar()
        self.publish_progress.setVisible(False)
        publish_group_layout.addWidget(self.publish_progress)
        
        # Лог публикации
        self.publish_log = QTextEdit()
        self.publish_log.setReadOnly(True)
        self.publish_log.setMaximumHeight(200)
        publish_group_layout.addWidget(self.publish_log)
        
        publish_group.setLayout(publish_group_layout)
        publish_layout.addWidget(publish_group)
        publish_layout.addStretch()
        self.publish_page.setLayout(publish_layout)
        
        
        # Добавляем все страницы в центральную область
        main_layout.addWidget(self.account_page)
        main_layout.addWidget(self.parse_page)
        main_layout.addWidget(self.results_page)
        main_layout.addWidget(self.publish_page)
        self.parse_page.hide()
        self.results_page.hide()
        self.publish_page.hide()
        
        main_splitter.addWidget(central_area)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([250, 750])
        
        # === МЕНЮ ===
        self.setup_menu()
        
        # === СТАТУС БАР ===
        self.statusBar().showMessage("Готово")
    
    def load_styles(self):
        """Загружает стили из QSS файла или встроенный fallback."""
        style_path = get_styles_path()
        style_file = QFile(str(style_path))
        if style_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
            stream = QTextStream(style_file)
            style = stream.readAll()
            self.setStyleSheet(style)
            style_file.close()
        else:
            from embedded_styles import EMBEDDED_QSS
            self.setStyleSheet(EMBEDDED_QSS)
    
    def setup_tray_icon(self):
        """Настраивает системный трей"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("Системный трей недоступен")
            return
        
        # Создаем иконку трея
        self.tray_icon = QSystemTrayIcon(self)
        # Используем стандартную иконку, можно заменить на кастомную
        self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        
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
        # Сбрасываем все кнопки
        self.account_btn.setChecked(False)
        self.parse_btn.setChecked(False)
        self.results_btn.setChecked(False)
        self.publish_btn.setChecked(False)
        
        # Скрываем все страницы
        self.account_page.hide()
        self.parse_page.hide()
        self.results_page.hide()
        self.publish_page.hide()
        
        # Показываем нужную страницу
        if page_name == "account":
            self.account_btn.setChecked(True)
            self.account_page.show()
        elif page_name == "parse":
            self.parse_btn.setChecked(True)
            self.parse_page.show()
        elif page_name == "results":
            self.results_btn.setChecked(True)
            self.results_page.show()
            # Обновляем информацию о CSV файле
            if self.csv_file_path and os.path.exists(self.csv_file_path):
                self.csv_info_label.setText(f"CSV файл: {os.path.basename(self.csv_file_path)}")
                self.csv_info_label.setStyleSheet("color: #e0e0e0;")
                self.unique_results_btn.setEnabled(True)
                self.export_csv_btn.setEnabled(True)
        elif page_name == "publish":
            self.publish_btn.setChecked(True)
            self.publish_page.show()
            # Загружаем доски при открытии страницы
            if self.parser:
                self.load_boards()
            # Обновляем информацию о CSV файле
            if self.csv_file_path and os.path.exists(self.csv_file_path):
                self.publish_csv_info.setText(f"CSV файл: {os.path.basename(self.csv_file_path)}")
                self.publish_csv_info.setStyleSheet("color: #e0e0e0;")
            else:
                self.publish_csv_info.setText("CSV файл не найден. Сначала выполните парсинг.")
                self.publish_csv_info.setStyleSheet("color: #999999;")
    
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
        
        # Меню "Настройки"
        settings_menu = menubar.addMenu("Настройки")
        
        config_action = settings_menu.addAction("Конфигурация")
        config_action.triggered.connect(self.show_config)
    
    def load_config(self):
        """Загружает конфигурацию и инициализирует парсер"""
        config_path = get_config_path()
        try:
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}
        except Exception as e:
            print(f"Ошибка загрузки конфига: {e}")
            config = {}
        
        # Загружаем API ключ OpenRouter
        self.openrouter_api_key = config.get("openrouter_api_key", "")
        
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
        
        # Если включен логин, инициализируем парсер в фоне
        if enable_login:
            # Запускаем инициализацию парсера в отдельном потоке
            self.init_parser_thread = ParserInitThread(enable_login, headless, download_images)
            self.init_parser_thread.parser_ready.connect(self.on_parser_ready)
            self.init_parser_thread.login_completed.connect(self.on_login_completed)
            self.init_parser_thread.error_occurred.connect(self.on_parser_init_error)
            self.init_parser_thread.start()
            self.statusBar().showMessage("Инициализация парсера и авторизация...")
        else:
            # Если логин не нужен, парсер будет создан при первом использовании
            # Проверяем наличие cookies и загружаем информацию об аккаунте после инициализации
            cookies_file = get_cookies_path()
            if cookies_file.exists():
                # Инициализируем парсер в фоне для загрузки информации об аккаунте
                QTimer.singleShot(500, self._lazy_init_parser)
    
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
            # Проверяем что драйвер действительно создан
            if not self.parser.driver:
                raise RuntimeError("Chrome драйвер не был создан")
            self.statusBar().showMessage("Парсер готов")
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
                from webdriver_manager.chrome import ChromeDriverManager
                driver_path = ChromeDriverManager().install()
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
    
    def on_parser_ready(self, parser: PinterestSeleniumParser):
        """Обработчик готовности парсера"""
        self.parser = parser
        self.statusBar().showMessage("Парсер готов")
        
        # Если парсер готов и есть cookies, загружаем информацию об аккаунте
        if self.parser:
            # Проверяем наличие cookies файла
            cookies_file = get_cookies_path()
            if cookies_file.exists():
                # Загружаем информацию об аккаунте автоматически
                self.refresh_account_info()
    
    def on_login_completed(self):
        """Обработчик завершения логина - загружаем информацию об аккаунте"""
        self.login_completed = True
        self.statusBar().showMessage("Логин завершен, загрузка информации об аккаунте...")
        # Загружаем информацию об аккаунте после успешного логина с небольшой задержкой
        if self.parser:
            # Небольшая задержка чтобы браузер успел полностью загрузиться
            QTimer.singleShot(2000, self.refresh_account_info)
    
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
            self.auth_status_label.setText("Авторизован")
            self.auth_status_label.setStyleSheet("""
                QLabel {
                    color: #e0e0e0;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 4px 8px;
                    background-color: #1a3a1a;
                    border-radius: 6px;
                }
            """)
            self.auth_username_label.setText(f"@{username}")
            self.auth_username_label.show()
        else:
            self.auth_status_label.setText("Не авторизован")
            self.auth_status_label.setStyleSheet("""
                QLabel {
                    color: #8e8e93;
                    font-size: 11px;
                    font-weight: 500;
                    padding: 4px 8px;
                    background-color: #f5f5f7;
                    border-radius: 6px;
                }
            """)
            self.auth_username_label.hide()
        
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
        self.auth_status_label.setText("Не авторизован")
        self.auth_status_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
                background-color: #2a2a2a;
                border-radius: 6px;
            }
        """)
        self.auth_username_label.hide()
        
        self.statusBar().showMessage(f"Ошибка: {error}")
        self.account_info_widget.refresh_btn.setEnabled(True)
        QMessageBox.warning(self, "Ошибка", error)
    
    def on_search_clicked(self):
        """Обработчик парсинга по поиску"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Ошибка", "Введите тематику для поиска")
            return
        
        if not self._ensure_parser():
            return
        
        # Получаем количество пинов
        max_pins = self.pins_count_spin.value()
        
        # Очищаем результаты
        self.results_text.clear()
        self.results_text.append(f"Начинаем парсинг: {query} (количество: {max_pins})")
        
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
        self.results_text.append(message)
        self.statusBar().showMessage(message)
    
    def on_parse_completed(self, pins: list):
        """Обработчик завершения парсинга"""
        # Сохраняем результаты парсинга
        self.parsed_pins = pins
        
        # Сохраняем в CSV
        try:
            from pinterest_parser import PinterestParser
            csv_parser = PinterestParser()
            csv_dir = get_csv_dir()
            filename = f"pinterest_pins_{self.search_input.text().strip().replace(' ', '_').replace('/', '_')[:50]}.csv"
            csv_path = csv_dir / filename
            csv_parser.save_to_csv(pins, str(csv_path))
            self.csv_file_path = str(csv_path)
            
            # Переключаемся на страницу результатов
            self.show_page("results")
            
            # Очищаем и заполняем информацию
            self.results_text.clear()
            self.results_text.append("=" * 80)
            self.results_text.append("РЕЗУЛЬТАТЫ ПАРСИНГА")
            self.results_text.append("=" * 80)
            self.results_text.append(f"Найдено пинов: {len(pins)}")
            self.results_text.append(f"CSV файл создан: {filename}")
            self.results_text.append("\nДанные сохранены в CSV таблицу.")
            self.results_text.append("Используйте кнопку 'Уникализировать результаты' для уникализации заголовков и описаний.")
            
            self.csv_info_label.setText(f"CSV файл: {os.path.basename(filename)}")
            self.csv_info_label.setStyleSheet("color: #e0e0e0;")
            self.unique_results_btn.setEnabled(True)
            self.export_csv_btn.setEnabled(True)
            
            self.statusBar().showMessage(f"Парсинг завершен. Сохранено в {filename}")
        except Exception as e:
            self.results_text.append(f"\nОшибка при сохранении CSV: {e}")
            self.statusBar().showMessage(f"Парсинг завершен, но ошибка при сохранении: {e}")
        
        self.search_btn.setEnabled(True)
    
    def on_parse_error(self, error: str):
        """Обработчик ошибки парсинга"""
        self.results_text.append(f"\nОшибка: {error}")
        self.statusBar().showMessage(f"Ошибка: {error}")
        self.search_btn.setEnabled(True)
        QMessageBox.warning(self, "Ошибка парсинга", error)
    
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
        dialog.setMinimumWidth(400)
        
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
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        
        def save_config():
            self.openrouter_api_key = api_key_input.text().strip()
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
                
                QMessageBox.information(dialog, "Успех", "Настройки сохранены")
                dialog.accept()
            except Exception as e:
                QMessageBox.warning(dialog, "Ошибка", f"Не удалось сохранить настройки: {e}")
        
        save_btn.clicked.connect(save_config)
        cancel_btn.clicked.connect(dialog.reject)
        
        buttons_layout.addWidget(save_btn)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    
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
                try:
                    # Сначала пробуем получить доски через pin-creation-tool (самый актуальный способ)
                    publisher = PinterestPublisher(parser=self.parser)
                    boards = publisher.get_boards_from_creation_tool()
                    
                    if boards:
                        # Сохраняем в кэш
                        account_info = self.parser.get_account_info()
                        if account_info:
                            username = account_info.get('username')
                            if username:
                                CacheManager.save_boards(username, boards)
                        self.boards_loaded.emit(boards)
                        return
                    
                    # Если не получилось через pin-creation-tool, используем парсер
                    account_info = self.parser.get_account_info()
                    if not account_info:
                        self.error_occurred.emit("Не удалось получить информацию об аккаунте")
                        return
                    
                    username = account_info.get('username')
                    if not username:
                        self.error_occurred.emit("Не удалось определить имя пользователя")
                        return
                    
                    # Получаем доски из кэша или парсим
                    boards = CacheManager.load_boards(username)
                    if boards is None:
                        boards = self.parser.parse_user_boards(username=username)
                        if boards:
                            CacheManager.save_boards(username, boards)
                    
                    self.boards_loaded.emit(boards or [])
                except Exception as e:
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
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить доски: {error}")
    
    def start_auto_publish(self):
        """Запускает автопубликацию из CSV результатов"""
        if not self._ensure_parser():
            return
        
        if not self.csv_file_path or not os.path.exists(self.csv_file_path):
            QMessageBox.warning(self, "Ошибка", "CSV файл результатов не найден. Сначала выполните парсинг.")
            return
        
        link = self.pin_link_input.text().strip()
        if not link:
            QMessageBox.warning(self, "Ошибка", "Введите ссылку для публикации")
            return
        
        board_index = self.board_combo.currentIndex()
        if board_index < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите доску для публикации")
            return
        
        board_data = self.board_combo.currentData()
        if not board_data:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить информацию о доске")
            return
        
        board_name = board_data.get('board_name', self.board_combo.currentText())
        
        # Читаем CSV файл
        try:
            pins_data = []
            with open(self.csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                QMessageBox.warning(self, "Ошибка", "CSV файл пуст")
                return
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать CSV файл: {e}")
            return
        
        # Создаем поток для автопубликации
        class AutoPublishThread(QThread):
            publish_progress = pyqtSignal(str)
            publish_completed = pyqtSignal(bool, str)
            
            def __init__(self, parser, pins_data, link, board_name):
                super().__init__()
                self.parser = parser
                self.pins_data = pins_data
                self.link = link
                self.board_name = board_name
            
            def run(self):
                try:
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
                    
                    self.publish_progress.emit("Инициализация публикатора...")
                    publisher = PinterestPublisher(parser=self.parser)
                    self.publish_progress.emit("✓ Публикатор инициализирован")
                    
                    total = len(self.pins_data)
                    success_count = 0
                    error_count = 0
                    self.publish_progress.emit(f"Всего пинов для публикации: {total}")
                    
                    # Перехватываем вывод для каждого пина
                    sys.stdout = print_capture
                    
                    try:
                        for i, pin in enumerate(self.pins_data, 1):
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
                                    self.publish_progress.emit(f"✗ Файл изображения не существует: {image_path}")
                                    continue
                                
                                # Проверяем размер файла
                                file_size = os.path.getsize(image_path)
                                if file_size == 0:
                                    error_count += 1
                                    self.publish_progress.emit(f"✗ Файл изображения пуст: {image_path}")
                                    continue
                                
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
                                    self.publish_progress.emit(f"✓ Успешно опубликовано {i}/{total}")
                                else:
                                    error_count += 1
                                    self.publish_progress.emit(f"✗ Ошибка публикации {i}/{total} (create_pin вернул False)")
                                    self.publish_progress.emit(f"  Проверьте логи в консоли для деталей")
                            except Exception as e:
                                error_count += 1
                                error_msg = f"✗ Исключение при публикации {i}/{total}: {str(e)}"
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
                                        os.remove(image_path)
                            except:
                                pass
                    finally:
                        # Восстанавливаем stdout
                        sys.stdout = old_stdout
                    
                    result_msg = f"Автопубликация завершена. Успешно: {success_count}, Ошибок: {error_count}"
                    self.publish_completed.emit(success_count > 0, result_msg)
                except Exception as e:
                    # Восстанавливаем stdout в случае ошибки
                    try:
                        if 'old_stdout' in locals():
                            sys.stdout = old_stdout
                    except:
                        pass
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
            board_name
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
            QMessageBox.information(self, "Завершено", message)
        else:
            QMessageBox.warning(self, "Ошибка", message)
    
    
    def unique_results_csv(self):
        """Уникализирует названия и описания пинов из CSV результатов через OpenRouter API"""
        if not self.csv_file_path or not os.path.exists(self.csv_file_path):
            QMessageBox.warning(self, "Ошибка", "CSV файл результатов не найден. Сначала выполните парсинг.")
            return
        
        # Используем сохраненный API ключ или запрашиваем
        api_key = self.openrouter_api_key
        if not api_key:
            from PyQt6.QtWidgets import QInputDialog
            api_key, ok = QInputDialog.getText(
                self,
                "OpenRouter API ключ",
                "Введите ваш OpenRouter API ключ:",
                echo=QLineEdit.EchoMode.Password
            )
            
            if not ok or not api_key.strip():
                return
            
            api_key = api_key.strip()
        
        csv_file = self.csv_file_path
        
        # Читаем CSV файл
        try:
            pins_data = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                QMessageBox.warning(self, "Ошибка", "CSV файл пуст")
                return
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать CSV файл: {e}")
            return
        
        # Запускаем уникализацию в отдельном потоке
        class UniquePinsThread(QThread):
            progress = pyqtSignal(str)
            completed = pyqtSignal(str)
            error = pyqtSignal(str)
            
            def __init__(self, api_key, pins_data, csv_file_path):
                super().__init__()
                self.api_key = api_key
                self.pins_data = pins_data
                self.csv_file_path = csv_file_path
            
            def run(self):
                try:
                    unique_pins = []
                    total = len(self.pins_data)
                    
                    for i, pin in enumerate(self.pins_data, 1):
                        title = pin.get('title', '') or ''
                        description = pin.get('description', '') or ''
                        
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
                    
                    # Перезаписываем исходный файл с уникализированными данными
                    with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as f:
                        if unique_pins:
                            writer = csv.DictWriter(f, fieldnames=unique_pins[0].keys())
                            writer.writeheader()
                            writer.writerows(unique_pins)
                    
                    self.completed.emit(f"Уникализация завершена. Файл {os.path.basename(self.csv_file_path)} обновлен.")
                except Exception as e:
                    self.error.emit(str(e))
            
            def unique_text(self, text: str, field_type: str) -> str:
                """Уникализирует текст через OpenRouter API"""
                if not text.strip():
                    return text
                
                prompt = f"""Перепиши следующий {field_type} для Pinterest поста, сделав его уникальным и оригинальным, но сохранив основной смысл и стиль. Используй синонимы и перефразирование. Ответь только переписанным текстом без дополнительных объяснений.

{field_type}: {text}"""
                
                try:
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
                    return unique_text
                except Exception as e:
                    # Если ошибка, возвращаем оригинальный текст
                    return text
        
        # Блокируем кнопку и показываем прогресс
        self.unique_results_btn.setEnabled(False)
        self.results_text.append("\n" + "=" * 80)
        self.results_text.append("НАЧАЛО УНИКАЛИЗАЦИИ")
        self.results_text.append("=" * 80)
        
        # Читаем CSV файл
        try:
            pins_data = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pins_data.append(row)
            
            if not pins_data:
                QMessageBox.warning(self, "Ошибка", "CSV файл пуст")
                self.unique_results_btn.setEnabled(True)
                return
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать CSV файл: {e}")
            self.unique_results_btn.setEnabled(True)
            return
        
        self.unique_thread = UniquePinsThread(api_key, pins_data, csv_file)
        self.unique_thread.progress.connect(self.on_unique_progress)
        self.unique_thread.completed.connect(self.on_unique_completed)
        self.unique_thread.error.connect(self.on_unique_error)
        self.unique_thread.finished.connect(lambda: self.unique_results_btn.setEnabled(True))
        self.unique_thread.start()
    
    def on_unique_progress(self, message: str):
        """Обработчик прогресса уникализации"""
        self.results_text.append(message)
        self.statusBar().showMessage(message)
    
    def on_unique_completed(self, message: str):
        """Обработчик завершения уникализации"""
        self.results_text.append(message)
        self.statusBar().showMessage(message)
        QMessageBox.information(self, "Успех", message)
        # Обновляем информацию о файле
        if self.csv_file_path:
            self.csv_info_label.setText(f"CSV файл: {os.path.basename(self.csv_file_path)} (уникализирован)")
    
    def export_csv(self):
        """Экспортирует текущий CSV в выбранную пользователем папку"""
        if not self.csv_file_path or not os.path.exists(self.csv_file_path):
            QMessageBox.warning(self, "Ошибка", "CSV файл не найден. Сначала выполните парсинг.")
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
            self.results_text.append(f"CSV экспортирован: {path}")
            self.statusBar().showMessage(f"Экспортировано: {path}")
            QMessageBox.information(self, "Успех", f"CSV сохранен:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось экспортировать CSV: {e}")
    
    def on_unique_error(self, error: str):
        """Обработчик ошибки уникализации"""
        self.results_text.append(f"Ошибка: {error}")
        self.statusBar().showMessage(f"Ошибка: {error}")
        QMessageBox.warning(self, "Ошибка", f"Ошибка при уникализации: {error}")
    
    def closeEvent(self, event):
        """Обработчик закрытия окна"""
        if self.parser:
            self.parser.close()
        event.accept()


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    import traceback
    
    try:
        app = QApplication(sys.argv)
        window = PinterestMainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Критическая ошибка при запуске приложения: {e}")
        traceback.print_exc()
        # Показываем диалог с ошибкой если возможно
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Ошибка запуска")
            msg.setText(f"Не удалось запустить приложение:\n{str(e)}")
            msg.setDetailedText(traceback.format_exc())
            msg.exec()
        except:
            pass
        sys.exit(1)
