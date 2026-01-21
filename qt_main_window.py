"""
Главное окно Qt-приложения для парсера Pinterest.
Информация об аккаунте отображается в главном меню/окне.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox,
    QStatusBar, QMenuBar, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from typing import Optional, Dict
import json

from pinterest_selenium_parser import PinterestSeleniumParser
from cache_manager import CacheManager


class AccountInfoWidget(QGroupBox):
    """Виджет для отображения информации об аккаунте"""
    
    def __init__(self, parent=None):
        super().__init__("Информация об аккаунте", parent)
        self.setup_ui()
        self.account_info = None
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Имя пользователя
        self.username_label = QLabel("Не авторизован")
        self.username_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(self.username_label)
        
        # Дополнительная информация
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #666;")
        layout.addWidget(self.info_label)
        
        # Кнопка обновления
        self.refresh_btn = QPushButton("Обновить информацию")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        layout.addWidget(self.refresh_btn)
        
        self.setLayout(layout)
    
    def update_account_info(self, account_info: Optional[Dict[str, str]]):
        """Обновляет отображаемую информацию об аккаунте"""
        self.account_info = account_info
        
        if account_info:
            username = account_info.get('username', 'Неизвестно')
            self.username_label.setText(f"👤 {username}")
            
            # Формируем дополнительную информацию
            info_parts = []
            if account_info.get('display_name'):
                info_parts.append(f"Имя: {account_info['display_name']}")
            if account_info.get('pins_count'):
                info_parts.append(f"Пинов: {account_info['pins_count']}")
            if account_info.get('boards_count'):
                info_parts.append(f"Досок: {account_info['boards_count']}")
            
            if info_parts:
                self.info_label.setText(" | ".join(info_parts))
            else:
                self.info_label.setText("Авторизован")
            
            self.refresh_btn.setEnabled(True)
        else:
            self.username_label.setText("Не авторизован")
            self.info_label.setText("Войдите в аккаунт для отображения информации")
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
            # Получаем базовую информацию об аккаунте
            account_info = self.parser.get_account_info()
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
        self.setMinimumSize(800, 600)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Главный layout
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # === ИНФОРМАЦИЯ ОБ АККАУНТЕ (вверху главного окна) ===
        self.account_info_widget = AccountInfoWidget()
        main_layout.addWidget(self.account_info_widget)
        
        # === ОСНОВНЫЕ ФУНКЦИИ ===
        functions_group = QGroupBox("Парсинг")
        functions_layout = QVBoxLayout()
        
        # Поиск
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Тематика:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("например: python programming")
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("Парсить")
        self.search_btn.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.search_btn)
        functions_layout.addLayout(search_layout)
        
        
        functions_group.setLayout(functions_layout)
        main_layout.addWidget(functions_group)
        
        # === РЕЗУЛЬТАТЫ ===
        results_group = QGroupBox("Результаты")
        results_layout = QVBoxLayout()
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        results_layout.addWidget(self.results_text)
        
        results_group.setLayout(results_layout)
        main_layout.addWidget(results_group)
        
        # === МЕНЮ ===
        self.setup_menu()
        
        # === СТАТУС БАР ===
        self.statusBar().showMessage("Готово")
    
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
    
    def on_parser_ready(self, parser: PinterestSeleniumParser):
        """Обработчик готовности парсера"""
        self.parser = parser
        self.statusBar().showMessage("Парсер готов")
    
    def on_login_completed(self):
        """Обработчик завершения логина - загружаем информацию об аккаунте"""
        self.login_completed = True
        self.statusBar().showMessage("Логин завершен, загрузка информации об аккаунте...")
        # Загружаем информацию об аккаунте после успешного логина
        if self.parser:
            self.refresh_account_info()
    
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
        
        # Формируем сообщение о результатах парсинга
        pins_count = account_info.get('pins_count', 'Неизвестно')
        boards_count = account_info.get('boards_count', 'Неизвестно')
        status_msg = f"Информация обновлена: {pins_count}, {boards_count}"
        self.statusBar().showMessage(status_msg)
        
        # Выводим информацию в результаты
        self.results_text.clear()
        self.results_text.append("=" * 80)
        self.results_text.append("ИНФОРМАЦИЯ ОБ АККАУНТЕ")
        self.results_text.append("=" * 80)
        self.results_text.append(f"Пользователь: {account_info.get('username', 'Неизвестно')}")
        self.results_text.append(f"Пинов: {pins_count}")
        self.results_text.append(f"Досок: {boards_count}")
        
        # Показываем список досок
        boards = account_info.get('boards', [])
        if boards:
            self.results_text.append("\n" + "-" * 80)
            self.results_text.append("ДОСКИ:")
            self.results_text.append("-" * 80)
            for i, board in enumerate(boards[:10], 1):  # Показываем первые 10
                board_name = board.get('board_name', 'Без названия')
                pins_count_board = board.get('pins_count', '')
                self.results_text.append(f"{i}. {board_name} {pins_count_board}")
        
        self.account_info_widget.refresh_btn.setEnabled(True)
    
    def on_account_info_error(self, error: str):
        """Обработчик ошибки при получении информации об аккаунте"""
        self.account_info_widget.update_account_info(None)
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
            self.results_text.append(f"\n✓ Данные сохранены в файл: {filename}")
            self.statusBar().showMessage(f"Парсинг завершен. Сохранено в {filename}")
        except Exception as e:
            self.results_text.append(f"\n⚠ Ошибка при сохранении CSV: {e}")
            self.statusBar().showMessage(f"Парсинг завершен, но ошибка при сохранении: {e}")
        
        self.search_btn.setEnabled(True)
    
    def on_parse_error(self, error: str):
        """Обработчик ошибки парсинга"""
        self.results_text.append(f"\n⚠ Ошибка: {error}")
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
