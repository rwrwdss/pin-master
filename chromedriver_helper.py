"""
Хелпер для правильного получения пути к chromedriver
Исправляет проблему, когда ChromeDriverManager().install() возвращает путь к THIRD_PARTY_NOTICES.chromedriver
"""

import os
import sys
from pathlib import Path
from webdriver_manager.chrome import ChromeDriverManager


def is_frozen():
    """Проверяет, запущено ли приложение из исполняемого файла"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_chromedriver_path():
    """
    Получает правильный путь к chromedriver.
    Исправляет проблему, когда ChromeDriverManager возвращает путь к THIRD_PARTY_NOTICES.chromedriver
    """
    # В frozen режиме сначала проверяем bundle
    if is_frozen():
        meipass = Path(sys._MEIPASS)
        for possible_path in [
            meipass / "chromedriver",
            meipass / "chromedriver-mac-arm64" / "chromedriver",
            Path(sys.executable).parent / "chromedriver",
            Path(sys.executable).parent.parent / "Resources" / "chromedriver",
        ]:
            if possible_path.exists() and possible_path.is_file():
                try:
                    os.chmod(possible_path, 0o755)
                    return str(possible_path)
                except:
                    pass
    
    try:
        manager = ChromeDriverManager()
        returned_path = manager.install()
        
        # Проверяем, что это действительно chromedriver
        if os.path.basename(returned_path) == "chromedriver" and os.path.isfile(returned_path):
            # Убираем карантин для macOS
            if sys.platform == 'darwin':
                try:
                    import subprocess
                    subprocess.run(['xattr', '-d', 'com.apple.quarantine', returned_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    subprocess.run(['xattr', '-c', returned_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    os.chmod(returned_path, 0o755)
                except:
                    pass
            return returned_path
        
        # Если это не chromedriver, ищем его в той же директории
        driver_dir = os.path.dirname(returned_path)
        chromedriver_path = os.path.join(driver_dir, "chromedriver")
        
        if os.path.exists(chromedriver_path) and os.path.isfile(chromedriver_path):
            # Убираем карантин для macOS
            if sys.platform == 'darwin':
                try:
                    import subprocess
                    subprocess.run(['xattr', '-d', 'com.apple.quarantine', chromedriver_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    subprocess.run(['xattr', '-c', chromedriver_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    os.chmod(chromedriver_path, 0o755)
                except:
                    pass
            return chromedriver_path
        
        # Ищем в родительской директории
        parent_dir = os.path.dirname(driver_dir)
        if os.path.exists(parent_dir):
            for item in os.listdir(parent_dir):
                item_path = os.path.join(parent_dir, item)
                if item == "chromedriver" and os.path.isfile(item_path):
                    # Убираем карантин для macOS
                    if sys.platform == 'darwin':
                        try:
                            import subprocess
                            subprocess.run(['xattr', '-d', 'com.apple.quarantine', item_path], 
                                        stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                            subprocess.run(['xattr', '-c', item_path], 
                                        stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                            os.chmod(item_path, 0o755)
                        except:
                            pass
                    return item_path
        
        # Если не нашли, возвращаем исходный путь (может быть это правильный путь)
        return returned_path
        
    except Exception as e:
        print(f"⚠️  Ошибка при получении пути к chromedriver: {e}")
        # Пробуем найти chromedriver вручную
        home_dir = Path.home()
        wdm_dir = home_dir / ".wdm" / "drivers" / "chromedriver" / "mac64"
        
        if wdm_dir.exists():
            # Ищем последнюю версию
            versions = sorted([d for d in wdm_dir.iterdir() if d.is_dir()], reverse=True)
            for version_dir in versions:
                arm64_dir = version_dir / "chromedriver-mac-arm64"
                if arm64_dir.exists():
                    chromedriver = arm64_dir / "chromedriver"
                    if chromedriver.exists() and chromedriver.is_file():
                        # Убираем карантин
                        if sys.platform == 'darwin':
                            try:
                                import subprocess
                                subprocess.run(['xattr', '-d', 'com.apple.quarantine', str(chromedriver)], 
                                            stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                                subprocess.run(['xattr', '-c', str(chromedriver)], 
                                            stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                                os.chmod(chromedriver, 0o755)
                            except:
                                pass
                        return str(chromedriver)
        
        raise RuntimeError(f"Не удалось найти chromedriver: {e}")

