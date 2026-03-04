#!/usr/bin/env python3
"""Точка входа PinMaster: патч webdriver и запуск GUI."""

import sys
from pathlib import Path

# Корень проекта в sys.path для frozen и dev
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Патч webdriver до любых импортов selenium/webdriver_manager
try:
    import pinmaster.browser.webdriver_patch  # noqa: F401
except ImportError:
    pass

from pinmaster.gui.main_window import main

if __name__ == "__main__":
    main()
