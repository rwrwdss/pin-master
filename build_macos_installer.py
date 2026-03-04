#!/usr/bin/env python3
"""
Скрипт для сборки установщика для macOS на M процессоре (Apple Silicon)
Создает .app bundle и опционально .dmg установщик
"""

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

# Проверяем что мы на macOS
if platform.system() != 'Darwin':
    print("❌ Этот скрипт предназначен только для macOS")
    sys.exit(1)

# Проверяем архитектуру
arch = platform.machine()
if arch != 'arm64':
    print(f"⚠️  Предупреждение: обнаружена архитектура {arch}, ожидается arm64 (Apple Silicon)")

# Пути и версия
BASE_DIR = Path(__file__).parent
APP_NAME = "PinMaster"
VERSION = "1.0.0"
BUILD = "20250204"
ICON_FILE = BASE_DIR / "icon.icns"
STYLES_FILE = BASE_DIR / "styles.qss"
MAIN_SCRIPT = BASE_DIR / "qt_main_window.py"
BUILD_DIR = BASE_DIR / "build"
DIST_DIR = BASE_DIR / "dist"
SPEC_FILE = BASE_DIR / f"{APP_NAME}.spec"

def check_dependencies():
    """Проверяет наличие необходимых зависимостей"""
    print("🔍 Проверка зависимостей...")
    
    # Проверяем Python
    python_version = sys.version_info
    if python_version < (3, 8):
        print("❌ Требуется Python 3.8 или выше")
        sys.exit(1)
    print(f"✓ Python {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Проверяем архитектуру Python
    import platform
    python_arch = platform.machine()
    print(f"✓ Архитектура Python: {python_arch}")
    
    if python_arch != 'arm64':
        print(f"⚠️  Внимание: Python работает на {python_arch}, но нужен arm64 для Apple Silicon")
        print("   Рекомендуется использовать Python для arm64")
        print("   Установите Python для arm64 через Homebrew:")
        print("   brew install python@3.11")
        print("   или используйте python3 из системы (обычно arm64)")
    
    # Проверяем архитектуру установленных пакетов (если возможно)
    try:
        import lxml
        import struct
        # Пробуем загрузить бинарный модуль и проверить его архитектуру
        print("   Проверка архитектуры установленных пакетов...")
    except:
        pass
    
    # Проверяем критические зависимости
    critical_deps = {
        'PyQt6': 'PyQt6',
        'selenium': 'selenium',
        'requests': 'requests',
        'beautifulsoup4': 'bs4',
    }
    
    missing_deps = []
    for dep_name, import_name in critical_deps.items():
        try:
            __import__(import_name)
            print(f"✓ {dep_name} установлен")
        except ImportError:
            print(f"❌ {dep_name} не установлен")
            missing_deps.append(dep_name)
    
    if missing_deps:
        print(f"\n⚠️  Отсутствуют зависимости: {', '.join(missing_deps)}")
        print("   Устанавливаю автоматически...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing_deps, check=True)
            print("✓ Зависимости установлены")
        except subprocess.CalledProcessError:
            print("❌ Ошибка при установке зависимостей")
            print(f"   Установите вручную: pip install {' '.join(missing_deps)}")
            sys.exit(1)
    
    # Проверяем PyInstaller
    try:
        import PyInstaller
        print(f"✓ PyInstaller установлен")
    except ImportError:
        print("❌ PyInstaller не установлен. Устанавливаю...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"], check=True)
        print("✓ PyInstaller установлен")
    
    # Проверяем наличие иконки
    if not ICON_FILE.exists():
        print(f"⚠️  Иконка не найдена: {ICON_FILE}")
        print("   Приложение будет собрано без иконки")
    else:
        print(f"✓ Иконка найдена: {ICON_FILE}")
    
    # Проверяем наличие стилей
    if not STYLES_FILE.exists():
        print(f"⚠️  Файл стилей не найден: {STYLES_FILE}")
    else:
        print(f"✓ Файл стилей найден: {STYLES_FILE}")

def download_chromedriver():
    """Предварительно скачивает chromedriver для включения в bundle"""
    print("\n📥 Предварительная загрузка chromedriver...")
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        manager = ChromeDriverManager()
        driver_path = manager.install()
        print(f"✓ ChromeDriverManager вернул путь: {driver_path}")
        
        # Проверяем, что это действительно исполняемый файл
        driver_dir = os.path.dirname(driver_path)
        
        # Ищем chromedriver в той же директории (обычно это просто "chromedriver")
        actual_driver = os.path.join(driver_dir, "chromedriver")
        if os.path.exists(actual_driver) and os.path.isfile(actual_driver):
            driver_path = actual_driver
            print(f"✓ Найден chromedriver: {driver_path}")
        elif not os.path.exists(driver_path) or not os.path.isfile(driver_path):
            # Ищем в родительской директории
            parent_dir = os.path.dirname(driver_dir)
            if os.path.exists(parent_dir):
                for file in os.listdir(parent_dir):
                    full_path = os.path.join(parent_dir, file)
                    if file == "chromedriver" and os.path.isfile(full_path):
                        driver_path = full_path
                        print(f"✓ Найден chromedriver в родительской директории: {driver_path}")
                        break
        
        # Проверяем, что файл существует и исполняемый
        if os.path.exists(driver_path) and os.path.isfile(driver_path):
            # Убираем карантин для macOS
            import subprocess
            import platform
            if platform.system() == 'Darwin':
                try:
                    subprocess.run(['xattr', '-d', 'com.apple.quarantine', driver_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    subprocess.run(['xattr', '-c', driver_path], 
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    os.chmod(driver_path, 0o755)
                    print("✓ Карантин удален, права установлены")
                except:
                    pass
            return driver_path
        else:
            print(f"⚠️  Chromedriver не найден по пути: {driver_path}")
            return None
        
    except Exception as e:
        print(f"⚠️  Не удалось предварительно загрузить chromedriver: {e}")
        print("   webdriver-manager загрузит его при первом запуске")
        import traceback
        traceback.print_exc()
        return None

def create_spec_file():
    """Создает .spec файл для PyInstaller"""
    print("\n📝 Создание .spec файла...")
    
    # Собираем все Python файлы
    python_files = list(BASE_DIR.glob("*.py"))
    python_files_str = ",\n    ".join([f"'{f.name}'" for f in python_files])
    
    # Предварительно загружаем chromedriver
    chromedriver_path = download_chromedriver()
    
    # Собираем данные (datas)
    datas = []
    if STYLES_FILE.exists():
        datas.append(f"('{STYLES_FILE.name}', '.')")
    if ICON_FILE.exists():
        datas.append(f"('{ICON_FILE.name}', '.')")
    # Браузеры Playwright — при наличии архива пользователям не нужен интернет для публикации
    playwright_archive = BASE_DIR / "playwright-browsers.tar.gz"
    if playwright_archive.exists():
        datas.append(f"('{playwright_archive.name}', '.')")
        print(f"✓ Playwright браузеры будут в bundle (~{playwright_archive.stat().st_size // (1024*1024)} MB)")
    else:
        print("⚠️  playwright-browsers.tar.gz не найден — для автопубликации пользователю понадобится интернет при первом запуске или положите архив в корень проекта и пересоберите")
    
    # Добавляем chromedriver если он был загружен
    binaries = []
    if chromedriver_path and os.path.exists(chromedriver_path):
        # Включаем chromedriver как бинарный файл
        # Используем только имя файла, PyInstaller найдет его в системе
        driver_name = os.path.basename(chromedriver_path)
        binaries.append(f"('{chromedriver_path}', '.')")
        print(f"✓ Chromedriver будет включен в bundle: {driver_name}")
    
    datas_str = ",\n        ".join(datas) if datas else ""
    binaries_str = ",\n        ".join(binaries) if binaries else "[]"
    
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{MAIN_SCRIPT.name}'],
    pathex=[],
    binaries=[
        {binaries_str}
    ],
    datas=[
        {datas_str}
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'selenium.common.exceptions',
        'webdriver_manager',
        'webdriver_manager.chrome',
        'webdriver_manager.core',
        'webdriver_manager.core.driver',
        'webdriver_manager.core.driver_cache',
        'webdriver_manager.core.os_manager',
        'webdriver_manager.core.utils',
        'webdriver_frozen_patch',
        'chromedriver_helper',
        'requests',
        'beautifulsoup4',
        'bs4',
        'lxml',
        'lxml.etree',
        'lxml.html',
        'csv',
        'json',
        'pathlib',
        'typing',
        'subprocess',
        'platform',
        'time',
        'os',
        'sys',
        # Локальные модули (обязательно для прод, иначе возможны ImportError в .app)
        'cache_manager',
        'cookies_manager',
        'path_utils',
        'pinterest_publisher',
        'pinterest_selenium_parser',
        'pinterest_selectors',
        'status_indicator',
        'toast_notification',
        'board_scraper',
        'pinterest_auth',
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright._impl',
        'greenlet',
        'pyee',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Не показывать консоль
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',  # Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name='{APP_NAME}.app',
    icon={f"'{ICON_FILE.name}'" if ICON_FILE.exists() else "None"},
    bundle_identifier='com.pinmaster.app',
    version='{VERSION}',
    info_plist={{
        'CFBundleName': 'PinMaster',
        'CFBundleDisplayName': 'PinMaster',
        'CFBundleShortVersionString': '{VERSION}',
        'CFBundleVersion': '{BUILD}',
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'NSRequiresAquaSystemAppearance': 'False',
        'LSMinimumSystemVersion': '11.0',
        'NSHumanReadableCopyright': 'Copyright © 2024',
    }},
)
"""
    
    with open(SPEC_FILE, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"✓ .spec файл создан: {SPEC_FILE}")

def build_app():
    """Собирает приложение с помощью PyInstaller"""
    print("\n🔨 Сборка приложения...")
    
    # Очищаем предыдущие сборки
    if BUILD_DIR.exists():
        print("   Очистка старой сборки...")
        shutil.rmtree(BUILD_DIR)
    
    if DIST_DIR.exists():
        print("   Очистка старой дистрибуции...")
        shutil.rmtree(DIST_DIR)
    
    # Запускаем PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        SPEC_FILE.name
    ]
    
    print(f"   Выполняю: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR, check=False)
    
    if result.returncode != 0:
        print("❌ Ошибка при сборке приложения")
        sys.exit(1)
    
    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        print(f"❌ Приложение не найдено: {app_path}")
        sys.exit(1)
    
    # Удаляем карантин macOS (quarantine) для предотвращения блокировки Gatekeeper
    print("   Удаление карантина macOS...")
    try:
        subprocess.run(["xattr", "-cr", str(app_path)], check=False, capture_output=True)
        print("   ✓ Карантин удален")
    except Exception as e:
        print(f"   ⚠️  Не удалось удалить карантин: {e}")
    
    # Пробуем подписать приложение (если есть сертификат разработчика)
    print("   Попытка подписания приложения...")
    try:
        # Ищем сертификат разработчика
        cert_result = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"], 
                                    capture_output=True, text=True)
        if "Developer ID Application" in cert_result.stdout or "Apple Development" in cert_result.stdout:
            # Найден сертификат, подписываем
            cert_name = None
            for line in cert_result.stdout.split('\n'):
                if 'Developer ID Application' in line or 'Apple Development' in line:
                    # Извлекаем имя сертификата
                    parts = line.split('"')
                    if len(parts) >= 2:
                        cert_name = parts[1]
                        break
            
            if cert_name:
                sign_result = subprocess.run([
                    "codesign", "--force", "--deep", "--sign", cert_name, str(app_path)
                ], capture_output=True, text=True)
                if sign_result.returncode == 0:
                    print("   ✓ Приложение подписано")
                else:
                    print(f"   ⚠️  Не удалось подписать: {sign_result.stderr[:100]}")
            else:
                print("   ⚠️  Сертификат не найден, пропускаю подписание")
        else:
            print("   ⚠️  Сертификат разработчика не найден, пропускаю подписание")
            print("   💡 Приложение будет работать, но может потребоваться обход Gatekeeper")
    except Exception as e:
        print(f"   ⚠️  Ошибка при подписании: {e}")
    
    print(f"✓ Приложение собрано: {app_path}")
    return app_path

def _create_dmg_background(dest_dir: Path) -> bool:
    """Создаёт фоновое изображение для окна DMG (градиент). Возвращает True если создано."""
    bg_dir = dest_dir / ".background"
    bg_dir.mkdir(parents=True, exist_ok=True)
    bg_path = bg_dir / "background.png"
    try:
        from PIL import Image
        w, h = 540, 384
        img = Image.new("RGB", (w, h))
        pixels = img.load()
        for y in range(h):
            for x in range(w):
                # Градиент: тёмно-серый сверху → светлый снизу
                t = y / h
                r = int(45 + (220 - 45) * t)
                g = int(48 + (222 - 48) * t)
                b = int(52 + (225 - 52) * t)
                pixels[x, y] = (r, g, b)
        img.save(bg_path, "PNG")
        return True
    except Exception:
        try:
            # Минимальный фон: один цвет
            from PIL import Image
            img = Image.new("RGB", (540, 384), color=(240, 240, 242))
            img.save(bg_path, "PNG")
            return True
        except Exception:
            return False


def _style_dmg_with_applescript(mount_point: str) -> bool:
    """Применяет оформление окна DMG: позиции иконок и размер окна (без фона — избегаем ошибки AppleScript)."""
    vol_name = os.path.basename(mount_point.rstrip("/"))
    # Оформление: вид иконок, размер окна, позиции (PinMaster слева, Applications справа)
    script = (
        f'tell application "Finder"\n'
        f'  tell disk "{vol_name}"\n'
        '    open\n'
        '    set theWindow to container window\n'
        '    set current view of theWindow to icon view\n'
        '    set toolbar visible of theWindow to false\n'
        '    set statusbar visible of theWindow to false\n'
        '    set the bounds of theWindow to {100, 100, 640, 484}\n'
        '    set theOptions to icon view options of theWindow\n'
        '    set icon size of theOptions to 96\n'
        '    set arrangement of theOptions to not arranged\n'
        f'    set position of item "{APP_NAME}.app" of theWindow to {120, 170}\n'
        '    set position of item "Applications" of theWindow to {380, 170}\n'
        '    close\n'
        '    open\n'
        '    update without registering applications\n'
        '    delay 0.5\n'
        '    close\n'
        '  end tell\n'
        'end tell\n'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 and result.stderr:
            print(f"   ⚠️  AppleScript: {result.stderr.strip()}")
        return result.returncode == 0
    except Exception as e:
        print(f"   ⚠️  Оформление DMG: {e}")
        return False


def create_dmg(app_path):
    """Создает стилизованный .dmg установщик (фон, иконки, окно)."""
    print("\n💿 Создание .dmg установщика...")
    
    dmg_path = DIST_DIR / f"{APP_NAME}.dmg"
    
    if dmg_path.exists():
        print("   Удаление старого DMG...")
        dmg_path.unlink()
    
    dmg_temp = DIST_DIR / "dmg_temp"
    if dmg_temp.exists():
        shutil.rmtree(dmg_temp)
    dmg_temp.mkdir()
    
    print("   Копирование приложения...")
    shutil.copytree(app_path, dmg_temp / f"{APP_NAME}.app")
    
    print("   Ссылка на Applications...")
    try:
        os.symlink("/Applications", dmg_temp / "Applications")
    except FileExistsError:
        pass
    
    # Фон для окна DMG
    if _create_dmg_background(dmg_temp):
        print("   ✓ Фон DMG создан")
    
    print("   Создание DMG образа...")
    temp_dmg = DIST_DIR / f"{APP_NAME}_temp.dmg"
    if temp_dmg.exists():
        temp_dmg.unlink()
    
    cmd_create = [
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(dmg_temp),
        "-ov",
        "-format", "UDRW",
        str(temp_dmg)
    ]
    result = subprocess.run(cmd_create, check=False, capture_output=True)
    
    if result.returncode != 0:
        print(f"⚠️  Ошибка при создании DMG: {result.stderr.decode()}")
        if dmg_temp.exists():
            shutil.rmtree(dmg_temp)
        if temp_dmg.exists():
            temp_dmg.unlink()
        return None
    
    print("   Монтирование и оформление окна...")
    mount_cmd = ["hdiutil", "attach", "-readwrite", "-noverify", "-noautoopen", str(temp_dmg)]
    mount_result = subprocess.run(mount_cmd, capture_output=True, text=True)
    
    if mount_result.returncode != 0:
        print(f"⚠️  Не удалось смонтировать DMG: {mount_result.stderr}")
        if dmg_temp.exists():
            shutil.rmtree(dmg_temp)
        if temp_dmg.exists():
            temp_dmg.unlink()
        return None
    
    mount_point = None
    for line in mount_result.stdout.split("\n"):
        if "/Volumes" in line and APP_NAME in line:
            parts = line.split("\t")
            if len(parts) > 2:
                mount_point = parts[-1].strip()
                break
    
    if not mount_point:
        import plistlib
        list_cmd = ["hdiutil", "info", "-plist"]
        list_result = subprocess.run(list_cmd, capture_output=True, text=True)
        try:
            info = plistlib.loads(list_result.stdout.encode())
            for entity in info.get("images", []):
                for system in entity.get("system-entities", []):
                    if system.get("mount-point"):
                        mount_point = system["mount-point"]
                        break
                if mount_point:
                    break
        except Exception:
            pass
    
    if mount_point and os.path.exists(mount_point):
        _style_dmg_with_applescript(mount_point)
        subprocess.run(["hdiutil", "detach", mount_point], capture_output=True)
    else:
        # Точка монтирования не найдена — ищем том по имени и отключаем
        for vol in Path("/Volumes").iterdir():
            if vol.name == APP_NAME and vol.is_dir():
                subprocess.run(["hdiutil", "detach", str(vol)], capture_output=True)
                break
    
    print("   Сжатие DMG...")
    cmd_convert = [
        "hdiutil", "convert",
        str(temp_dmg),
        "-format", "UDZO",  # Сжатый формат
        "-o", str(dmg_path)
    ]
    
    result_convert = subprocess.run(cmd_convert, check=False, capture_output=True)
    
    # Удаляем временный DMG
    if temp_dmg.exists():
        temp_dmg.unlink()
    
    # Очищаем временную папку
    if dmg_temp.exists():
        shutil.rmtree(dmg_temp)
    
    if result_convert.returncode != 0:
        print(f"⚠️  Ошибка при конвертации DMG: {result_convert.stderr.decode()}")
        return None
    
    if dmg_path.exists():
        # Получаем размер файла
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"✓ .dmg установщик создан: {dmg_path}")
        print(f"   Размер: {size_mb:.1f} MB")
        return dmg_path
    else:
        print("⚠️  .dmg файл не создан")
        return None

def main():
    """Главная функция"""
    print("=" * 60)
    print(f"🔨 Сборка установщика для macOS (Apple Silicon) — {APP_NAME} {VERSION} ({BUILD})")
    print("=" * 60)
    # Удаляем старые сборки и старый spec в начале (spec будет сгенерирован заново с актуальным chromedriver)
    if BUILD_DIR.exists():
        print("   Удаление старых артефактов build/...")
        shutil.rmtree(BUILD_DIR)
    if DIST_DIR.exists():
        print("   Удаление старых артефактов dist/...")
        shutil.rmtree(DIST_DIR)
    if SPEC_FILE.exists():
        print("   Удаление старого PinMaster.spec (будет создан заново с актуальными путями)...")
        SPEC_FILE.unlink()
    print("\n💡 Важно:")
    print("   - Убедитесь, что используете Python для arm64 (Apple Silicon)")
    print("   - Все зависимости должны быть установлены для arm64")
    print("   - Если возникают ошибки архитектуры, переустановите зависимости:")
    print("     pip uninstall -y lxml cryptography cffi")
    print("     pip install --no-cache-dir lxml cryptography cffi")
    print()
    
    # Проверяем зависимости
    check_dependencies()
    
    # Создаем .spec файл
    create_spec_file()
    
    # Собираем приложение
    try:
        app_path = build_app()
    except Exception as e:
        if "IncompatibleBinaryArchError" in str(e) or "incompatible architecture" in str(e).lower():
            print("\n" + "=" * 60)
            print("❌ ОШИБКА: Несовместимая архитектура")
            print("=" * 60)
            print("\nПроблема: Установлены пакеты для x86_64, но нужны для arm64")
            print("\nРешение:")
            print("1. Убедитесь, что используете Python для arm64:")
            print("   arch -arm64 python3 --version")
            print("   (должно показать arm64)")
            print("\n2. Переустановите зависимости для arm64:")
            print("   pip uninstall -y lxml cryptography cffi beautifulsoup4 selenium PyQt6")
            print("   arch -arm64 pip install --no-cache-dir lxml cryptography cffi beautifulsoup4 selenium PyQt6")
            print("\n3. Или используйте виртуальное окружение:")
            print("   python3 -m venv venv_arm64")
            print("   source venv_arm64/bin/activate")
            print("   pip install -r requirements.txt")
            print("\n4. Затем запустите скрипт снова")
            sys.exit(1)
        else:
            raise
    
    # Создаем DMG (опционально)
    dmg_path = create_dmg(app_path)
    
    print("\n" + "=" * 60)
    print("✅ Сборка завершена!")
    print("=" * 60)
    print(f"\n📦 Результаты:")
    print(f"   .app: {app_path}")
    if dmg_path:
        print(f"   .dmg: {dmg_path}")
    print(f"\n💡 Для тестирования запустите:")
    print(f"   open {app_path}")
    print("\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Сборка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

