# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['qt_main_window.py'],
    pathex=[],
    binaries=[
        ('/Users/amirfatyhov/.wdm/drivers/chromedriver/mac64/144.0.7559.133/chromedriver-mac-arm64/chromedriver', '.')
    ],
    datas=[
        ('styles.qss', '.'),
        ('icon.icns', '.'),
        ('playwright-browsers.tar.gz', '.')
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
    hooksconfig={},
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
    name='PinMaster',
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
    name='PinMaster.app',
    icon='icon.icns',
    bundle_identifier='com.pinmaster.app',
    version='1.0.0',
    info_plist={
        'CFBundleName': 'PinMaster',
        'CFBundleDisplayName': 'PinMaster',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '20250204',
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'NSRequiresAquaSystemAppearance': 'False',
        'LSMinimumSystemVersion': '11.0',
        'NSHumanReadableCopyright': 'Copyright © 2024',
    },
)
