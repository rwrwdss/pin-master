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
    Базовая директория приложения (корень проекта).
    Frozen: директория с исполняемым файлом.
    Разработка: корень проекта (родитель пакета pinmaster).
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


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


def get_accounts_dir() -> Path:
    """Директория для хранения cookies по аккаунтам (accounts/)."""
    if is_frozen():
        acc_dir = get_app_data_dir() / "accounts"
    else:
        acc_dir = get_base_dir() / "accounts"
    acc_dir.mkdir(parents=True, exist_ok=True)
    return acc_dir


def get_playwright_profiles_dir() -> Path:
    """Директория для постоянных Chrome-профилей Playwright (profiles/)."""
    profiles_dir = get_app_data_dir() / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return profiles_dir


def get_playwright_profile_dir(account_id: str) -> Path:
    """
    Путь к профилю Playwright для аккаунта (profiles/pw_profile_{account_id}).
    До 10 аккаунтов: account_id "1".."10".
    """
    if not account_id or not str(account_id).strip():
        account_id = "default"
    safe_id = str(account_id).strip().replace(os.path.sep, "_").replace("..", "_")[:32]
    return get_playwright_profiles_dir() / f"pw_profile_{safe_id}"


def get_cookies_path(account_id: Optional[str] = None) -> Path:
    """
    Путь к файлу cookies.
    account_id=None — основной файл pinterest_cookies.json.
    account_id="1", "2" и т.д. — accounts/account_1_cookies.json (до 10 аккаунтов).
    """
    if not account_id:
        if is_frozen():
            return get_app_data_dir() / "pinterest_cookies.json"
        return get_base_dir() / "pinterest_cookies.json"
    return get_accounts_dir() / f"account_{account_id}_cookies.json"


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


def get_results_csv_path() -> Path:
    """Один рабочий CSV файл с результатами парсинга (для обратной совместимости)."""
    base_csv_dir = get_user_data_dir() / "csv"
    base_csv_dir.mkdir(parents=True, exist_ok=True)
    return base_csv_dir / "pinterest_results.csv"


def get_unique_results_csv_path(query: str) -> Path:
    """Уникальный путь к CSV для нового парсинга: каждый результат в своём файле (дата + время + запрос)."""
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in (query or "parse")[:50]).strip() or "parse"
    safe = safe.replace(" ", "_")[:40]
    csv_dir = get_csv_dir(date_str)
    return csv_dir / f"pinterest_{safe}_{time_str}.csv"


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
