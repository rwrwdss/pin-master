"""
Патч для работы webdriver-manager в frozen приложении (PyInstaller)
Должен быть импортирован до использования ChromeDriverManager
"""

import sys
import os
from pathlib import Path

def is_frozen():
    """Проверяет, запущено ли приложение из исполняемого файла"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def patch_webdriver_manager():
    """Патчит webdriver-manager для работы в frozen режиме"""
    if not is_frozen():
        return  # Не нужно патчить в режиме разработки
    
    try:
        # Получаем путь к временной директории приложения
        if hasattr(sys, '_MEIPASS'):
            meipass = Path(sys._MEIPASS)
            
            # Проверяем, есть ли chromedriver в bundle
            chromedriver_in_bundle = None
            for possible_path in [
                meipass / "chromedriver",
                meipass / "chromedriver-mac-arm64" / "chromedriver",
                Path(sys.executable).parent / "chromedriver",
                Path(sys.executable).parent.parent / "Resources" / "chromedriver",
            ]:
                if possible_path.exists():
                    # Проверяем, что это исполняемый файл
                    if os.path.isfile(possible_path):
                        try:
                            os.chmod(possible_path, 0o755)
                            chromedriver_in_bundle = possible_path
                            break
                        except:
                            pass
            
            if chromedriver_in_bundle:
                # Создаем директорию для драйверов в пользовательской директории
                home_dir = Path.home()
                wdm_dir = home_dir / ".wdm" / "drivers" / "chromedriver" / "mac64"
                latest_version_dir = None
                
                # Находим или создаем директорию для последней версии
                if wdm_dir.exists():
                    # Ищем последнюю версию
                    versions = [d for d in wdm_dir.iterdir() if d.is_dir()]
                    if versions:
                        latest_version_dir = max(versions, key=lambda x: x.name)
                
                if not latest_version_dir:
                    # Создаем директорию для версии
                    import re
                    from webdriver_manager.chrome import ChromeDriverManager
                    try:
                        # Получаем версию Chrome
                        manager = ChromeDriverManager()
                        version = "144.0.7559.96"  # Примерная версия, можно получить динамически
                        latest_version_dir = wdm_dir / version / "chromedriver-mac-arm64"
                        latest_version_dir.mkdir(parents=True, exist_ok=True)
                    except:
                        latest_version_dir = wdm_dir / "latest" / "chromedriver-mac-arm64"
                        latest_version_dir.mkdir(parents=True, exist_ok=True)
                
                # Копируем chromedriver в доступное место
                target_driver = latest_version_dir / "chromedriver"
                if not target_driver.exists() or target_driver.stat().st_size != chromedriver_in_bundle.stat().st_size:
                    import shutil
                    shutil.copy2(chromedriver_in_bundle, target_driver)
                    os.chmod(target_driver, 0o755)
                    # Убираем карантин
                    try:
                        import subprocess
                        subprocess.run(['xattr', '-d', 'com.apple.quarantine', str(target_driver)], 
                                    stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                        subprocess.run(['xattr', '-c', str(target_driver)], 
                                    stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    except:
                        pass
                    print(f"✓ Chromedriver скопирован из bundle в {target_driver}")
                else:
                    print(f"✓ Chromedriver уже существует: {target_driver}")
                
    except Exception as e:
        print(f"⚠️  Не удалось применить патч для webdriver-manager: {e}")
        import traceback
        traceback.print_exc()

# Автоматически применяем патч при импорте
patch_webdriver_manager()

