"""
Парсер досок Pinterest через Playwright.
Работает с cookies без официального API.
Используется в GUI при загрузке досок для каждого аккаунта.
"""

import json
import os
import re
import sys
import tarfile
import logging
import shutil
from pathlib import Path
from urllib.parse import unquote
from typing import Dict, List, Optional, Tuple

from path_utils import get_app_data_dir, is_frozen

logger = logging.getLogger("PinMaster")


def _get_default_browsers_dir() -> Path:
    """Определяет директорию, где должны храниться браузеры Playwright."""
    if getattr(sys, "frozen", False):
        base_dir = get_app_data_dir()
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / "playwright-browsers"


def _find_packaged_archive() -> Optional[Path]:
    """Ищет архив с браузерами, упакованный вместе с приложением."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "playwright-browsers.tar.gz")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "playwright-browsers.tar.gz")
    candidates.append(Path(__file__).resolve().parent / "playwright-browsers.tar.gz")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ensure_playwright_browsers(target_dir: Path) -> Path:
    """Гарантирует наличие распакованных браузеров в target_dir."""
    if target_dir.exists() and any(target_dir.glob("chromium-*")):
        return target_dir

    archive = _find_packaged_archive()
    if archive and archive.exists():
        logger.debug("Распаковка Playwright из архива: %s", archive)
        target_parent = target_dir.parent
        target_parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=target_parent)
        if target_dir.exists():
            return target_dir

    # В дев-режиме можно использовать глобальный путь Playwright по умолчанию
    return target_dir


def _configure_playwright_browsers_path():
    """Устанавливает PLAYWRIGHT_BROWSERS_PATH (и распаковывает браузеры при необходимости)."""
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if current:
        logger.debug("PLAYWRIGHT_BROWSERS_PATH (из окружения): %s", current)
        return Path(current)

    browsers_dir = _get_default_browsers_dir()
    browsers_dir = _ensure_playwright_browsers(browsers_dir)
    if browsers_dir.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
        logger.debug("PLAYWRIGHT_BROWSERS_PATH установлен: %s", browsers_dir)
    else:
        if is_frozen():
            logger.warning("Playwright браузеры не найдены. Скачайте полную версию приложения (с Playwright) или проверьте подключение к интернету.")
        else:
            logger.warning("Playwright браузеры не найдены. Установите: playwright install chromium")
    return browsers_dir


_configure_playwright_browsers_path()

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _cookies_to_playwright(cookies: Dict[str, str]) -> List[dict]:
    """Преобразует словарь cookies в формат Playwright."""
    return [
        {"name": k, "value": str(v) if v is not None else "", "url": "https://ru.pinterest.com"}
        for k, v in cookies.items()
        if v
    ]


def get_username(cookies: Dict[str, str]) -> Optional[str]:
    """
    Получает username Pinterest по cookies.
    Посещает главную страницу и извлекает username из HTML/JSON.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright не установлен, get_username недоступен")
        return None
    pw_cookies = _cookies_to_playwright(cookies)
    if not pw_cookies:
        logger.warning("get_username: cookies пусты или некорректны")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            ctx.add_cookies(pw_cookies)
            page = ctx.new_page()
            # Увеличиваем timeout и используем domcontentloaded вместо load
            try:
                page.goto("https://ru.pinterest.com/", timeout=60000, wait_until="domcontentloaded")
            except Exception as nav_err:
                logger.warning(f"get_username: навигация не удалась: {nav_err}")
                browser.close()
                return None
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
        # Ищем "username":"xxx" в resource-response-data (UserSettingsResource)
        m = re.search(r'"username"\s*:\s*"([a-zA-Z0-9_.-]+)"', html)
        if m:
            return m.group(1)
        # Альтернатива: ссылка /username/ в canonical или og:url
        m = re.search(r'pinterest\.com/([a-zA-Z0-9_.-]+)/', html)
        if m:
            u = m.group(1)
            if u not in ("pin", "about", "business", "policy", "newsletter", "source"):
                return u
        logger.warning("get_username: username не найден в HTML (возможно cookies истекли или аккаунт заблокирован)")
    except Exception as e:
        logger.warning(f"get_username: {e}")
    return None


def get_boards(cookies: Dict[str, str], username: Optional[str] = None) -> Tuple[List[Dict], Optional[int], Optional[str]]:
    """
    Получает список досок пользователя Pinterest по cookies.

    Args:
        cookies: Словарь cookies (формат CookiesManager)
        username: Имя пользователя. Если None — определяется автоматически.

    Returns:
        (boards, total_pins, resolved_username) — доски, кол-во пинов, фактический username из URL досок.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright не установлен, get_boards недоступен")
        return [], None, None

    pw_cookies = _cookies_to_playwright(cookies)
    if not pw_cookies:
        return [], None, None

    if not username:
        username = get_username(cookies)
        if not username:
            logger.warning("Не удалось определить username для загрузки досок")
            return [], None, None

    boards_data = []
    total_pins = None
    resolved_username = username  # Фактический username (может быть скорректирован при retry)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            ctx.add_cookies(pw_cookies)
            page = ctx.new_page()

            def handle_response(response):
                nonlocal boards_data, total_pins
                url = response.url
                if "resource" in url or "graphql" in url.lower() or "GetBoard" in url or "Boards" in url:
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            data = body.get("resource_response", {}).get("data") or body.get("data")
                            if data:
                                if isinstance(data, list) and data and isinstance(data[0], dict):
                                    # Проверяем что это доски с name и url
                                    first = data[0]
                                    if first.get("type") == "board" and first.get("name") and first.get("url"):
                                        # Берём список с большим количеством досок (избегаем перезаписи полного списка коротким)
                                        if len(data) > len(boards_data):
                                            boards_data = data
                                elif isinstance(data, dict):
                                    if "pin_count" in data and "boards" not in str(data):
                                        total_pins = data.get("pin_count")
                                    boards = data.get("boards") if isinstance(data.get("boards"), list) else None
                                    if boards and not boards_data:
                                        boards_data = boards
                    except Exception:
                        pass

            page.on("response", handle_response)

            url = f"https://ru.pinterest.com/{username}/_boards/"
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            try:
                close_btn = page.query_selector(
                    '[aria-label="Close"], button[aria-label="Закрыть"], '
                    '[data-test-id="modal-close-button"], [data-test-id="close-modal-button"]'
                )
                if close_btn:
                    close_btn.click()
                    page.wait_for_timeout(500)
                else:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
            except Exception:
                pass

            try:
                board_grid = page.query_selector(
                    '[data-test-id="board-grid"], [data-test-id="boards-section"], [class*="boardGrid"]'
                )
                if board_grid:
                    for _ in range(5):
                        board_grid.evaluate("el => el.scrollBy(0, 500)")
                        page.wait_for_timeout(800)
            except Exception:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)

            page.wait_for_timeout(2000)
            # Если получили доски, проверяем — username в URL досок может отличаться от get_username
            # (get_username иногда возвращает ID вместо логина, тогда API отдаёт неполный список)
            if boards_data and isinstance(boards_data, list):
                for b in boards_data:
                    url = b.get("url") or b.get("board_url") or ""
                    parts = str(url).strip("/").split("/")
                    if len(parts) >= 2:
                        url_username = parts[0]
                        # ID обычно длинный/hex; логин — буквы, цифры, подчёркивание
                        if url_username != username and len(url_username) <= 30 and re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", url_username):
                            logger.debug(f"get_boards: username в URL доски ({url_username}) != {username}, переходим на правильный профиль")
                            resolved_username = url_username
                            boards_data = []
                            url = f"https://ru.pinterest.com/{url_username}/_boards/"
                            page.goto(url, timeout=90000, wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                            try:
                                grid = page.query_selector('[data-test-id="board-grid"], [data-test-id="boards-section"], [class*="boardGrid"]')
                                if grid:
                                    for _ in range(5):
                                        grid.evaluate("el => el.scrollBy(0, 500)")
                                        page.wait_for_timeout(800)
                            except Exception:
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                page.wait_for_timeout(1000)
                            page.wait_for_timeout(2000)
                            break
            html = page.content()

            if not boards_data:
                for m in re.finditer(
                    r'<script[^>]*data-test-id="resource-response-data"[^>]*type="application/json"[^>]*>(\{.+?\})</script>',
                    html, re.DOTALL
                ):
                    try:
                        data = json.loads(m.group(1))
                        res = data.get("resource", {})
                        resp = data.get("resource_response", {})
                        if "Board" in res.get("name", ""):
                            d = resp.get("data")
                            if isinstance(d, list):
                                boards_data = d
                            elif isinstance(d, dict) and "boards" in d:
                                boards_data = d["boards"]
                            break
                        if res.get("name") == "UserSettingsResource":
                            total_pins = resp.get("data", {}).get("pin_count")
                    except (json.JSONDecodeError, re.error):
                        pass

            if not boards_data:
                m = re.search(
                    r'<script[^>]*id="__PWS_DATA__"[^>]*type="application/json"[^>]*>(\{.+?\})</script>',
                    html, re.DOTALL
                )
                if not m:
                    m = re.search(r'"BoardsResource":\s*\{\s*"data":\s*(\[[^\]]+\])', html)
                if m:
                    try:
                        if m.lastindex and "[" in m.group(1):
                            boards_data = json.loads(m.group(1))
                        else:
                            data = json.loads(m.group(1))
                            boards_data = data.get("resources", {}).get("BoardsResource", {}).get("data", [])
                    except json.JSONDecodeError:
                        pass

            if not boards_data:
                page_username = resolved_username or username  # после retry страница показывает url_username
                board_links = page.query_selector_all(f'a[href^="/{page_username}/"]')
                seen_urls = set()
                for link_el in board_links:
                    try:
                        href = (link_el.get_attribute("href") or "").split("?")[0].rstrip("/")
                        parts = href.strip("/").split("/")
                        if len(parts) != 2 or parts[0] != page_username:
                            continue
                        board_slug = parts[1]
                        if board_slug in ("_profile", "_boards", "_saved", "_pins", "_collages", ""):
                            continue
                        if href in seen_urls:
                            continue
                        if link_el.evaluate(
                            'el => !!el.closest(\'[role=dialog], [data-test-id*="modal"]\')'
                        ):
                            continue
                        text = (link_el.inner_text() or "").replace("\xa0", " ")
                        if re.search(r"создать|create", text, re.I) and len(text) < 25:
                            continue
                        first_line = text.split("\n")[0].strip().strip(",")
                        name = first_line if first_line else unquote(board_slug.replace("-", " "))
                        name = re.sub(
                            r"\d+\s*(?:пин|pin).*", "", name, flags=re.I
                        ).strip().strip("-–—,") or name
                        seen_urls.add(href)
                        pin_match = re.search(r"(\d+)\s*(?:пин|pin)", text, re.I)
                        pin_count = int(pin_match.group(1)) if pin_match else 0
                        boards_data.append({
                            "name": name,
                            "pin_count": pin_count,
                            "url": f"/{page_username}/{board_slug}/"
                        })
                    except Exception:
                        continue

            browser.close()
    except Exception as e:
        logger.exception(f"get_boards: {e}")
        raise

    result = []
    for b in boards_data if isinstance(boards_data, list) else []:
        result.append({
            "id": b.get("id", ""),
            "name": b.get("name", ""),
            "pin_count": b.get("pin_count", 0),
            "url": b.get("url", b.get("board_url", ""))
        })
        if not resolved_username:
            url = b.get("url") or b.get("board_url") or ""
            parts = str(url).strip("/").split("/")
            if len(parts) >= 2 and re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", parts[0]):
                resolved_username = parts[0]
                break
    return result, total_pins, resolved_username or username
