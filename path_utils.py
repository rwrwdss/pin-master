"""
Утилита для управления путями к файлам в продакшене.
Обеспечивает правильные пути для конфигов, cookies, изображений и CSV файлов.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def get_app_name() -> str:
    """Возвращает название приложения"""
    return "PinMaster"


def get_app_data_dir() -> Path:
    """
    Возвращает директорию для данных приложения.
    Для macOS: ~/Library/Application Support/PinMaster
    Для Windows: %APPDATA%/PinMaster
    Для Linux: ~/.config/PinMaster
    """
    if sys.platform == "darwin":  # macOS
        base_dir = Path.home() / "Library" / "Application Support" / get_app_name()
    elif sys.platform == "win32":  # Windows
        base_dir = Path(os.getenv("APPDATA", Path.home())) / get_app_name()
    else:  # Linux и другие
        base_dir = Path.home() / ".config" / get_app_name()
    
    # Создаем директорию если не существует
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_user_data_dir() -> Path:
    """
    Возвращает директорию для пользовательских данных (CSV, изображения).
    По умолчанию: ~/Documents/PinMaster
    """
    base_dir = Path.home() / "Documents" / get_app_name()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def is_frozen() -> bool:
    """Проверяет, запущено ли приложение из исполняемого файла (PyInstaller)"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_base_dir() -> Path:
    """
    Возвращает базовую директорию приложения.
    Для frozen приложения - директория с исполняемым файлом.
    Для разработки - директория со скриптом.
    """
    if is_frozen():
        # PyInstaller: директория с исполняемым файлом (.app/Contents/MacOS)
        return Path(sys.executable).parent
    else:
        # В режиме разработки - директория со скриптом
        return Path(__file__).parent


def get_meipass_dir() -> Path:
    """Путь к папке с ресурсами PyInstaller (datas, иконки и т.д.)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return get_base_dir()


def get_config_path() -> Path:
    """Возвращает путь к файлу конфигурации"""
    if is_frozen():
        # В продакшене конфиг в AppData
        return get_app_data_dir() / "config.json"
    else:
        # В разработке - рядом со скриптом
        return get_base_dir() / "config.json"


def get_cookies_path() -> Path:
    """Возвращает путь к файлу cookies"""
    if is_frozen():
        # В продакшене cookies в AppData
        return get_app_data_dir() / "pinterest_cookies.json"
    else:
        # В разработке - рядом со скриптом
        return get_base_dir() / "pinterest_cookies.json"


def get_images_dir() -> Path:
    """Возвращает директорию для сохранения изображений"""
    # Изображения всегда в пользовательской директории
    images_dir = get_user_data_dir() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def get_csv_dir(date: Optional[str] = None) -> Path:
    """
    Возвращает директорию для CSV файлов.
    Если указана дата (YYYY-MM-DD), создает подпапку с этой датой.
    Если дата не указана, использует текущую дату.
    """
    base_csv_dir = get_user_data_dir() / "csv"
    base_csv_dir.mkdir(parents=True, exist_ok=True)
    
    if date:
        csv_dir = base_csv_dir / date
    else:
        from datetime import datetime
        csv_dir = base_csv_dir / datetime.now().strftime("%Y-%m-%d")
    
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


def get_parsing_history_path() -> Path:
    """Возвращает путь к файлу истории парсингов"""
    if is_frozen():
        return get_app_data_dir() / "parsing_history.json"
    else:
        return get_base_dir() / "parsing_history.json"


def get_logs_dir() -> Path:
    """Возвращает директорию для логов"""
    if is_frozen():
        logs_dir = get_app_data_dir() / "logs"
    else:
        logs_dir = get_base_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_styles_path() -> Path:
    """Возвращает путь к файлу стилей. В frozen .app datas лежат в Contents/Resources."""
    if is_frozen():
        base = get_base_dir()  # .../Contents/MacOS
        candidates = [
            get_meipass_dir() / "styles.qss",
            base / "styles.qss",
            base.parent / "Resources" / "styles.qss",  # macOS .app: datas здесь
        ]
        for p in candidates:
            if p.exists():
                return p
        return candidates[0]
    return get_base_dir() / "styles.qss"


def migrate_old_files():
    """
    Мигрирует старые файлы из директории разработки в правильные места.
    Вызывается при первом запуске продакшен версии.
    """
    if not is_frozen():
        return  # Миграция только для frozen приложений
    
    base_dir = get_base_dir()
    app_data_dir = get_app_data_dir()
    
    # Мигрируем config.json
    old_config = base_dir / "config.json"
    new_config = get_config_path()
    if old_config.exists() and not new_config.exists():
        try:
            import shutil
            shutil.copy2(old_config, new_config)
            print(f"✓ Мигрирован config.json в {new_config}")
        except Exception as e:
            print(f"⚠ Ошибка миграции config.json: {e}")
    
    # Мигрируем cookies
    old_cookies = base_dir / "pinterest_cookies.json"
    new_cookies = get_cookies_path()
    if old_cookies.exists() and not new_cookies.exists():
        try:
            import shutil
            shutil.copy2(old_cookies, new_cookies)
            print(f"✓ Мигрированы cookies в {new_cookies}")
        except Exception as e:
            print(f"⚠ Ошибка миграции cookies: {e}")
    
    # Мигрируем старые папки с изображениями
    import glob
    import shutil
    old_images_pattern = base_dir / "pinterest_images_*"
    new_images_dir = get_images_dir()
    if base_dir.exists():
        for old_dir in glob.glob(str(old_images_pattern)):
            try:
                dir_name = Path(old_dir).name
                dest_dir = new_images_dir / dir_name
                if not dest_dir.exists():
                    shutil.copytree(old_dir, dest_dir)
                    print(f"✓ Мигрирована папка {dir_name} в {dest_dir}")
            except Exception as e:
                print(f"⚠ Ошибка миграции папки {old_dir}: {e}")


# Инициализация при импорте
if is_frozen():
    migrate_old_files()
