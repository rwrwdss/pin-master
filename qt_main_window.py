"""
Главное окно Qt-приложения для парсера Pinterest.
Информация об аккаунте отображается в главном меню/окне.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox,
    QStatusBar, QMenuBar, QMenu, QMessageBox, QSplitter,
    QComboBox, QFileDialog, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QFile, QTextStream, QTimer
from PyQt6.QtGui import QFont, QIcon
from typing import Optional, Dict
import json
import os

from pinterest_selenium_parser import PinterestSeleniumParser
from cache_manager import CacheManager
from pinterest_publisher import PinterestPublisher


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
    
    def __init__(self, enable_login: bool, headless: bool, download_images: bool):
        super().__init__()
        self.enable_login = enable_login
        self.headless = headless
        self.download_images = download_images
    
    def run(self):
        """Инициализирует парсер и ждет завершения логина"""
        try:
            # Инициализируем парсер (это может занять время, особенно при логине)
            parser = PinterestSeleniumParser(
                headless=self.headless,
                download_images=self.download_images,
                auto_login=self.enable_login
            )
            
            # Если был включен логин, парсер уже дождался его завершения в _ensure_authentication
            # Отправляем сигнал о готовности парсера
            self.parser_ready.emit(parser)
            
            # Если был логин, отправляем сигнал о его завершении
            if self.enable_login:
                self.login_completed.emit()
                
        except Exception as e:
            print(f"Ошибка при инициализации парсера: {e}")
            import traceback
            traceback.print_exc()


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
        self.setup_ui()
        self.load_config()
    
    def setup_ui(self):
        self.setWindowTitle("Pinterest Parser")
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
        
        functions_group.setLayout(functions_layout)
        parse_layout.addWidget(functions_group)
        parse_layout.addStretch()
        self.parse_page.setLayout(parse_layout)
        
        # === СТРАНИЦА РЕЗУЛЬТАТОВ ===
        self.results_page = QWidget()
        results_layout = QVBoxLayout()
        results_layout.setSpacing(16)
        
        results_group = QGroupBox("Результаты")
        results_group_layout = QVBoxLayout()
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        results_group_layout.addWidget(self.results_text)
        
        results_group.setLayout(results_group_layout)
        results_layout.addWidget(results_group)
        self.results_page.setLayout(results_layout)
        
        # === СТРАНИЦА АВТОПУБЛИКАЦИИ ===
        self.publish_page = QWidget()
        publish_layout = QVBoxLayout()
        publish_layout.setSpacing(16)
        
        publish_group = QGroupBox("Публикация пина")
        publish_group_layout = QVBoxLayout()
        publish_group_layout.setSpacing(12)
        
        # Изображение
        image_layout = QHBoxLayout()
        image_layout.setSpacing(12)
        image_layout.addWidget(QLabel("Изображение:"))
        self.image_path_input = QLineEdit()
        self.image_path_input.setPlaceholderText("Выберите файл изображения...")
        image_layout.addWidget(self.image_path_input)
        self.browse_image_btn = QPushButton("Обзор...")
        self.browse_image_btn.clicked.connect(self.browse_image_file)
        image_layout.addWidget(self.browse_image_btn)
        publish_group_layout.addLayout(image_layout)
        
        # Заголовок
        title_layout = QHBoxLayout()
        title_layout.setSpacing(12)
        title_layout.addWidget(QLabel("Заголовок:"))
        self.pin_title_input = QLineEdit()
        self.pin_title_input.setPlaceholderText("Введите заголовок пина...")
        title_layout.addWidget(self.pin_title_input)
        publish_group_layout.addLayout(title_layout)
        
        # Описание
        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(4)
        desc_layout.addWidget(QLabel("Описание:"))
        self.pin_description_input = QTextEdit()
        self.pin_description_input.setPlaceholderText("Введите описание пина...")
        self.pin_description_input.setMaximumHeight(100)
        desc_layout.addWidget(self.pin_description_input)
        publish_group_layout.addLayout(desc_layout)
        
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
        
        # Кнопка публикации
        self.publish_pin_btn = QPushButton("Опубликовать пин")
        self.publish_pin_btn.clicked.connect(self.publish_pin)
        publish_group_layout.addWidget(self.publish_pin_btn)
        
        # Прогресс бар
        self.publish_progress = QProgressBar()
        self.publish_progress.setVisible(False)
        publish_group_layout.addWidget(self.publish_progress)
        
        # Лог публикации
        self.publish_log = QTextEdit()
        self.publish_log.setReadOnly(True)
        self.publish_log.setMaximumHeight(150)
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
        """Загружает стили из QSS файла"""
        style_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        style_file = QFile(style_path)
        if style_file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
            stream = QTextStream(style_file)
            style = stream.readAll()
            self.setStyleSheet(style)
            style_file.close()
        else:
            # Если файл не найден, используем базовые стили
            print(f"Предупреждение: файл стилей не найден: {style_path}")
    
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
        elif page_name == "publish":
            self.publish_btn.setChecked(True)
            self.publish_page.show()
            # Загружаем доски при открытии страницы
            if self.parser:
                self.load_boards()
    
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
        try:
            with open("config.json", 'r', encoding='utf-8') as f:
                config = json.load(f)
        except:
            config = {}
        
        enable_login = config.get("enable_login", False)
        headless = config.get("headless", True)
        download_images = config.get("download_images", True)
        
        # Если включен логин, headless должен быть False
        if enable_login:
            headless = False
        
        # Инициализируем парсер в отдельном потоке, чтобы не блокировать UI
        # и дождаться завершения логина перед загрузкой информации об аккаунте
        self.parser = None
        self.login_completed = False
        
        if enable_login:
            # Запускаем инициализацию парсера в отдельном потоке
            self.init_parser_thread = ParserInitThread(enable_login, headless, download_images)
            self.init_parser_thread.parser_ready.connect(self.on_parser_ready)
            self.init_parser_thread.login_completed.connect(self.on_login_completed)
            self.init_parser_thread.start()
            self.statusBar().showMessage("Инициализация парсера и авторизация...")
        else:
            # Если логин не нужен, инициализируем сразу
            self.parser = PinterestSeleniumParser(
                headless=headless,
                download_images=download_images,
                auto_login=False
            )
            # Проверяем наличие cookies и загружаем информацию об аккаунте
            cookies_file = "pinterest_cookies.json"
            if os.path.exists(cookies_file):
                # Небольшая задержка для инициализации парсера
                QTimer.singleShot(1000, self.refresh_account_info)
    
    def on_parser_ready(self, parser: PinterestSeleniumParser):
        """Обработчик готовности парсера"""
        self.parser = parser
        self.statusBar().showMessage("Парсер готов")
        
        # Если парсер готов и есть cookies, загружаем информацию об аккаунте
        if self.parser:
            # Проверяем наличие cookies файла
            import os
            cookies_file = "pinterest_cookies.json"
            if os.path.exists(cookies_file):
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
        if not self.parser:
            QMessageBox.warning(self, "Ошибка", "Парсер не инициализирован. Дождитесь завершения авторизации.")
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
        
        if not self.parser:
            QMessageBox.warning(self, "Ошибка", "Парсер не инициализирован. Дождитесь завершения авторизации.")
            return
        
        # Очищаем результаты
        self.results_text.clear()
        self.results_text.append(f"Начинаем парсинг: {query}")
        
        # Блокируем кнопку на время парсинга
        self.search_btn.setEnabled(False)
        self.statusBar().showMessage("Парсинг в процессе...")
        
        # Запускаем парсинг в отдельном потоке
        self.search_parse_thread = SearchParseThread(self.parser, query, max_pins=20)
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
        # Переключаемся на страницу результатов
        self.show_page("results")
        
        self.results_text.append("\n" + "=" * 80)
        self.results_text.append("РЕЗУЛЬТАТЫ ПАРСИНГА")
        self.results_text.append("=" * 80)
        self.results_text.append(f"Найдено пинов: {len(pins)}\n")
        
        for i, pin in enumerate(pins, 1):
            title = pin.get('title', 'Без названия') or 'Без названия'
            author = pin.get('author', 'Неизвестно') or 'Неизвестно'
            media_type = pin.get('media_type', 'image')
            pin_link = pin.get('pin_link', '')
            
            self.results_text.append(f"{i}. {title}")
            self.results_text.append(f"   Автор: {author}")
            self.results_text.append(f"   Тип: {media_type}")
            if pin_link:
                self.results_text.append(f"   Ссылка: {pin_link[:80]}...")
            self.results_text.append("")
        
        # Сохраняем в CSV
        try:
            from pinterest_parser import PinterestParser
            csv_parser = PinterestParser()
            filename = f"pinterest_pins_{self.search_input.text().strip().replace(' ', '_').replace('/', '_')[:50]}.csv"
            csv_parser.save_to_csv(pins, filename)
            self.results_text.append(f"\nДанные сохранены в файл: {filename}")
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
        QMessageBox.information(self, "Настройки", "Окно настроек будет реализовано")
    
    def browse_image_file(self):
        """Открывает диалог выбора файла изображения"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Изображения (*.png *.jpg *.jpeg *.gif *.webp);;Все файлы (*)"
        )
        if file_path:
            self.image_path_input.setText(file_path)
    
    def load_boards(self):
        """Загружает список досок пользователя"""
        if not self.parser:
            QMessageBox.warning(self, "Ошибка", "Парсер не инициализирован. Дождитесь завершения авторизации.")
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
    
    def publish_pin(self):
        """Публикует пин на Pinterest"""
        if not self.parser:
            QMessageBox.warning(self, "Ошибка", "Парсер не инициализирован. Дождитесь завершения авторизации.")
            return
        
        # Проверяем заполненность полей
        image_path = self.image_path_input.text().strip()
        if not image_path:
            QMessageBox.warning(self, "Ошибка", "Выберите изображение для публикации")
            return
        
        if not os.path.exists(image_path):
            QMessageBox.warning(self, "Ошибка", f"Файл не найден: {image_path}")
            return
        
        title = self.pin_title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Ошибка", "Введите заголовок пина")
            return
        
        description = self.pin_description_input.toPlainText().strip()
        link = self.pin_link_input.text().strip()
        
        board_index = self.board_combo.currentIndex()
        if board_index < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите доску для публикации")
            return
        
        board_data = self.board_combo.currentData()
        if not board_data:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить информацию о доске")
            return
        
        board_name = board_data.get('board_name', self.board_combo.currentText())
        
        # Создаем поток для публикации
        class PublishPinThread(QThread):
            publish_progress = pyqtSignal(str)
            publish_completed = pyqtSignal(bool, str)
            
            def __init__(self, parser, image_path, title, description, link, board_name):
                super().__init__()
                self.parser = parser
                self.image_path = image_path
                self.title = title
                self.description = description
                self.link = link
                self.board_name = board_name
            
            def run(self):
                try:
                    self.publish_progress.emit("Инициализация публикатора...")
                    publisher = PinterestPublisher(parser=self.parser)
                    
                    self.publish_progress.emit(f"Публикация пина в доску '{self.board_name}'...")
                    success = publisher.create_pin(
                        image_path=self.image_path,
                        title=self.title,
                        description=self.description,
                        link=self.link,
                        board_name=self.board_name
                    )
                    
                    if success:
                        self.publish_completed.emit(True, f"Пин успешно опубликован в доску '{self.board_name}'")
                    else:
                        self.publish_completed.emit(False, "Не удалось опубликовать пин")
                except Exception as e:
                    self.publish_completed.emit(False, f"Ошибка при публикации: {str(e)}")
        
        # Блокируем кнопку и показываем прогресс
        self.publish_pin_btn.setEnabled(False)
        self.publish_progress.setVisible(True)
        self.publish_progress.setRange(0, 0)  # Неопределенный прогресс
        self.publish_log.clear()
        self.publish_log.append("Начало публикации...")
        
        self.publish_thread = PublishPinThread(
            self.parser,
            image_path,
            title,
            description,
            link,
            board_name
        )
        self.publish_thread.publish_progress.connect(self.on_publish_progress)
        self.publish_thread.publish_completed.connect(self.on_publish_completed)
        self.publish_thread.start()
    
    def on_publish_progress(self, message: str):
        """Обработчик прогресса публикации"""
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
    
    def on_publish_completed(self, success: bool, message: str):
        """Обработчик завершения публикации"""
        self.publish_progress.setVisible(False)
        self.publish_pin_btn.setEnabled(True)
        self.publish_log.append(message)
        self.statusBar().showMessage(message)
        
        if success:
            QMessageBox.information(self, "Успех", message)
            # Очищаем форму
            self.image_path_input.clear()
            self.pin_title_input.clear()
            self.pin_description_input.clear()
            self.pin_link_input.clear()
        else:
            QMessageBox.warning(self, "Ошибка", message)
    
    def closeEvent(self, event):
        """Обработчик закрытия окна"""
        if self.parser:
            self.parser.close()
        event.accept()


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    window = PinterestMainWindow()
    window.show()
    sys.exit(app.exec())
