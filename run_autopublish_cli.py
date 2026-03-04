#!/usr/bin/env python3
"""
Автопостинг без GUI: тот же движок, что и AutoPublishThread (Playwright + persistent profiles).
Проверка патча с постоянными профилями и пулом контекстов.

Использование:
  python run_autopublish_cli.py --link https://example.com --board "My Board" --posts 1 --headless
  python run_autopublish_cli.py --link https://... --board "Board" --posts 0   # только инициализация/закрытие пула
  python run_autopublish_cli.py --link https://... --board "Board" --posts 1 --dry-run  # без реальной публикации
  python run_autopublish_cli.py --csv path/to/results.csv --link https://... --board "Board" --posts 2
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("AutoPublishCLI")

from pinmaster.utils.paths import (
    get_accounts_dir,
    get_config_path,
    get_cookies_path,
    get_playwright_profile_dir,
    get_user_data_dir,
)


def resolve_cookies_path(account_id: str, accounts: List[Dict], acc_map: Dict[str, Dict]) -> Path:
    """Как в GUI: путь к cookies по account_id и config accounts."""
    acc = acc_map.get(str(account_id))
    if acc and acc.get("cookies_file"):
        cf = str(acc["cookies_file"])
        if "/" in cf or "\\" in cf:
            return Path(cf)
        return get_accounts_dir() / cf
    return get_cookies_path(account_id)


def get_account_proxy(account_id: str, accounts: List[Dict]) -> Optional[str]:
    """Прокси для аккаунта из config accounts[].proxy."""
    aid = str(account_id or "").strip()
    acc = next((a for a in accounts if str(a.get("id") or "") == aid), None)
    if not acc:
        return None
    proxy = (acc.get("proxy") or "").strip()
    return proxy if proxy else None


def run_autopublish_playwright(
    account_boards: List[Tuple[str, str]],
    pins_list: List[Dict],
    link: str,
    max_posts: int,
    accounts: List[Dict],
    get_cookies_path_fn: Callable[[str], Path],
    headless: bool = True,
    dry_run: bool = False,
    interval_sec: int = 5,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[int, int]:
    """
    Логика автопостинга как в AutoPublishThread: persistent context по account_id, пул, закрытие в конце.
    Возвращает (success_count, error_count).
    """
    log = log_fn or logger.info
    _context_pool: Dict[str, Any] = {}
    _page_pool: Dict[str, Any] = {}  # account_id -> page (ultra-fast: одна вкладка на аккаунт)

    def _get_or_create_context(playwright, account_id: str):
        aid = str(account_id or "").strip() or "default"
        if aid in _context_pool:
            return _context_pool[aid]
        try:
            import pinmaster.pinterest.board_scraper as board_scraper
            board_scraper._configure_playwright_browsers_path()
        except Exception:
            pass
        import random
        user_data_dir = get_playwright_profile_dir(account_id)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        proxy = get_account_proxy(account_id, accounts)
        viewport = {"width": random.randint(1360, 1440), "height": random.randint(860, 940)}
        kwargs = {
            "user_data_dir": str(user_data_dir),
            "headless": headless,
            "viewport": viewport,
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept_downloads": True,
        }
        if proxy:
            kwargs["proxy"] = {"server": proxy}
        ctx = playwright.chromium.launch_persistent_context(**kwargs)
        ctx.add_init_script("document.documentElement.style.zoom = '100%';")
        _context_pool[aid] = ctx
        return ctx

    try:
        from playwright.sync_api import sync_playwright
        from pinmaster.pinterest.cookies import load_cookies_from_file
        from pinmaster.pinterest.publisher import create_pin_playwright, _cookies_to_playwright
    except ImportError as e:
        log(f"✗ Playwright не установлен: {e}")
        return 0, max_posts

    plan = [account_boards[i % len(account_boards)] for i in range(max_posts)]
    success_count = 0
    error_count = 0
    image_cache: Dict[str, str] = {}
    temp_files_to_remove: List[str] = []

    def download_image(image_url: str) -> Optional[str]:
        if not image_url.startswith("http://") and not image_url.startswith("https://"):
            pm_images = get_user_data_dir() / "images"
            possible = [image_url, os.path.join(os.getcwd(), image_url), os.path.abspath(image_url)]
            if pm_images.exists():
                possible.append(str(pm_images / image_url))
            for p in possible:
                if os.path.exists(p):
                    return os.path.abspath(p)
            return None
        try:
            import tempfile
            import uuid
            import requests
            r = requests.get(image_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            ext = os.path.splitext(image_url)[1] or ".jpg"
            fp = os.path.join(tempfile.gettempdir(), f"pin_{uuid.uuid4().hex[:8]}{ext}")
            with open(fp, "wb") as f:
                f.write(r.content)
            temp_files_to_remove.append(fp)
            return fp
        except Exception:
            return None

    try:
        with sync_playwright() as p:
            try:
                log(f"Автопубликация (Playwright, persistent): {max_posts} постов, {len(account_boards)} аккаунтов, interval={interval_sec}s, dry_run={dry_run}")
                for i, (account_id, board_name) in enumerate(plan, 1):
                    pin_index = (i - 1) % len(pins_list)
                    pin = pins_list[pin_index]
                    image_url_or_path = (pin.get("image_url") or pin.get("image_path") or "").strip()
                    title = (pin.get("title") or pin.get("Title") or "").strip()
                    description = (pin.get("description") or pin.get("Description") or "").strip()
                    if not title and description:
                        title = (description[:80] + "…") if len(description) > 80 else description
                    if not title:
                        title = "Без названия"

                    if i > 1:
                        log(f"⏱ Ожидание {interval_sec} сек...")
                        time.sleep(interval_sec)
                    log(f"--- Пост {i}/{max_posts} | Аккаунт {account_id}, доска: '{board_name}' | пин {pin_index + 1}/{len(pins_list)} ---")

                    cookies_path = get_cookies_path_fn(str(account_id))
                    if not cookies_path or not cookies_path.exists():
                        log(f"✗ Нет cookies для аккаунта {account_id}")
                        error_count += 1
                        continue
                    cookies = load_cookies_from_file(str(cookies_path))
                    if not cookies:
                        log("✗ Не удалось загрузить cookies")
                        error_count += 1
                        continue
                    pw_cookies = _cookies_to_playwright(cookies)

                    if not image_url_or_path:
                        log("✗ У пина нет изображения")
                        error_count += 1
                        continue
                    image_path = image_cache.get(image_url_or_path)
                    if not image_path or not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
                        image_path = download_image(image_url_or_path)
                        if image_path and os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                            image_cache[image_url_or_path] = image_path
                    if not image_path or not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
                        log("✗ Не удалось загрузить изображение пина")
                        error_count += 1
                        continue

                    if i > 1:
                        time.sleep(2)

                    aid_str = str(account_id)
                    try:
                        context = _get_or_create_context(p, aid_str)
                        context.add_cookies(pw_cookies)
                        reuse_page = aid_str in _page_pool
                        if reuse_page:
                            page = _page_pool[aid_str]
                        else:
                            page = context.new_page()
                            page.set_default_timeout(30000)
                            _page_pool[aid_str] = page
                        if dry_run:
                            log("  [DRY-RUN] Пропуск create_pin_playwright")
                            success_count += 1
                        else:
                            error_out = []
                            ok = create_pin_playwright(
                                page,
                                image_path=image_path,
                                title=title,
                                description=description,
                                link=link,
                                board_name=board_name,
                                logger=logger,
                                error_out=error_out,
                                reuse_page=reuse_page,
                            )
                            if ok:
                                success_count += 1
                                log(f"✓ Опубликовано в доску «{board_name}» (аккаунт {account_id})")
                            else:
                                error_count += 1
                                log("✗ Ошибка публикации (Playwright)")
                                if error_out:
                                    log(f"  Детали: {error_out[0][:300]}")
                        # Страницу не закрываем — переиспользуем (ultra-fast)
                    except Exception as e:
                        error_count += 1
                        log(f"✗ {e}")
                        if aid_str in _page_pool:
                            try:
                                _page_pool[aid_str].close()
                            except Exception:
                                pass
                            del _page_pool[aid_str]

                for fp in temp_files_to_remove:
                    try:
                        if os.path.exists(fp):
                            os.remove(fp)
                    except Exception:
                        pass
                log(f"Завершено. Успешно: {success_count}, ошибок: {error_count}.")
            finally:
                _page_pool.clear()
                for ctx in _context_pool.values():
                    try:
                        ctx.close()
                    except Exception:
                        pass
                _context_pool.clear()
                log("Пул контекстов закрыт.")
    except Exception as e:
        logger.exception("AutoPublishCLI")
        raise
    return success_count, error_count


def main() -> int:
    ap = argparse.ArgumentParser(description="Автопостинг без GUI (Playwright, persistent profiles)")
    ap.add_argument("--config", default="", help="Путь к config.json (по умолчанию — из path_utils)")
    ap.add_argument("--csv", default="", help="CSV с пинами (колонки: image_url/image_path, title, description)")
    ap.add_argument("--link", required=True, help="Ссылка для всех пинов")
    ap.add_argument("--board", required=True, help="Название доски для публикации")
    ap.add_argument("--posts", type=int, default=1, help="Количество постов (0 = только инициализация пула)")
    ap.add_argument("--interval", type=int, default=5, help="Интервал между постами (сек)")
    ap.add_argument("--headless", action="store_true", default=True, help="Браузер в фоне")
    ap.add_argument("--no-headless", action="store_false", dest="headless")
    ap.add_argument("--dry-run", action="store_true", help="Не вызывать create_pin_playwright")
    ap.add_argument("--image", default="", help="Один пин: путь к изображению (если нет --csv)")
    ap.add_argument("--title", default="Test Pin", help="Заголовок при --image")
    ap.add_argument("--description", default="", help="Описание при --image")
    args = ap.parse_args()

    config_path = Path(args.config) if args.config else get_config_path()
    if not config_path.exists():
        logger.error("Конфиг не найден: %s", config_path)
        return 1
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    accounts = config.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    accounts = accounts[:10]
    if not accounts:
        logger.error("В config.json нет аккаунтов (accounts).")
        return 1

    acc_map = {str(a.get("id") or ""): a for a in accounts if a.get("id")}
    def get_cookies_path_fn(aid: str) -> Path:
        return resolve_cookies_path(aid, accounts, acc_map)

    account_boards = [(str(a.get("id") or "").strip(), args.board) for a in accounts if a.get("id")]
    if not account_boards:
        logger.error("Нет ни одного аккаунта с id.")
        return 1

    pins_list: List[Dict] = []
    if args.csv and os.path.exists(args.csv):
        with open(args.csv, "r", encoding="utf-8") as f:
            pins_list = list(csv.DictReader(f))
        logger.info("Загружено пинов из CSV: %d", len(pins_list))
    if not pins_list and args.image and os.path.exists(args.image):
        pins_list = [{
            "image_url": args.image,
            "image_path": args.image,
            "title": args.title,
            "description": args.description or "",
        }]
    if not pins_list and args.posts > 0:
        logger.error("Нет пинов: укажите --csv с данными или --image (путь к файлу).")
        return 1
    if not pins_list:
        pins_list = [{"image_url": "", "image_path": "", "title": "", "description": ""}]

    success, errors = run_autopublish_playwright(
        account_boards=account_boards,
        pins_list=pins_list,
        link=args.link,
        max_posts=args.posts,
        accounts=accounts,
        get_cookies_path_fn=get_cookies_path_fn,
        headless=args.headless,
        dry_run=args.dry_run,
        interval_sec=args.interval,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
