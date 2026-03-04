"""
Модуль для публикации пинов на Pinterest.
Поддерживает Selenium (PinterestPublisher.create_pin) и Playwright (create_pin_playwright).
PinBuilderSession — переиспользование одной вкладки pin-builder без перезагрузки (open_builder_once, reset_builder_fields, upload_new_image_without_reload).
"""

import time
import os
import re
import json
from pathlib import Path
from typing import Optional, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSessionIdException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from pinmaster.browser.chromedriver import get_chromedriver_path

from pinmaster.pinterest.selectors import PinterestConfig, PinCreationSelectors as PCS
from pinmaster.pinterest.cookies import load_cookies_from_file
from pinmaster.pinterest.selenium_parser import PinterestSeleniumParser


def _cookies_to_playwright(cookies: dict) -> list:
    """Преобразует словарь cookies в формат Playwright."""
    return [
        {"name": k, "value": str(v) if v is not None else "", "url": "https://ru.pinterest.com"}
        for k, v in cookies.items()
        if v
    ]


# --- Human-like anti-detection helpers ---
import random

def human_delay(min_s=0.2, max_s=0.8):
    """Небольшая случайная задержка для антидетекта."""
    time.sleep(random.uniform(min_s, max_s))

def jitter_text(text: str) -> str:
    """Микро-рандомизация текста (не ломает смысл, но снижает дубликаты)."""
    if not text:
        return text
    if random.random() < 0.15:
        return text + " "
    return text


# --- PinBuilderSession: persistent page per account, no reload between pins ---

class PinBuilderSession:
    """
    Держит одну вкладку pin-builder и переиспользует её для нескольких пинов без перезагрузки.
    Методы: open_builder_once(), reset_builder_fields(), upload_new_image_without_reload(), publish_pin().
    """
    PAGE_URL = None  # set from PCS at runtime

    SEL = {
        "upload": "#storyboard-upload-input",
        "title": "#storyboard-selector-title",
        "link": "#WebsiteField",
        "more_options": '[data-test-id="storyboard-show-more-options-button"]',
        "board_dropdown": '[data-test-id="board-dropdown-select-button"]',
        "board_search": 'input[placeholder*="поиск" i], input[placeholder*="search" i], input[type="search"]',
    }

    def __init__(self, page, logger=None, timeout: int = 30000):
        import logging
        self.page = page
        self.log = logger or logging.getLogger("PinMaster")
        self.timeout = timeout
        if PinBuilderSession.PAGE_URL is None:
            PinBuilderSession.PAGE_URL = __import__("pinterest_selectors").PinCreationSelectors.PAGE_URL

    def open_builder_once(self) -> None:
        """Открывает pin-builder один раз; если уже на нём или после /pin/ — переходит при необходимости."""
        url = self.page.url or ""
        if "pin-creation-tool" not in url:
            self.page.goto(PinBuilderSession.PAGE_URL, timeout=self.timeout, wait_until="domcontentloaded")
            self.page.wait_for_load_state("load", timeout=8000)
            self.page.wait_for_timeout(500)
        self.page.evaluate("document.documentElement.style.zoom = '1';")

    def reset_builder_fields(self) -> None:
        """Очищает title/description/link через JS без перезагрузки страницы."""
        self.page.evaluate("""() => {
            const form = document.querySelector('[id*="storyboard"]') || document.body;
            const titleEl = form.querySelector('#storyboard-selector-title');
            if (titleEl) { titleEl.value = ''; titleEl.dispatchEvent(new Event('input', {bubbles: true})); }
            const linkEl = form.querySelector('#WebsiteField');
            if (linkEl) { linkEl.value = ''; linkEl.dispatchEvent(new Event('input', {bubbles: true})); }
            for (const el of form.querySelectorAll('textarea, input[type="text"]')) {
                const ph = (el.placeholder || '').toLowerCase();
                if (/описание|description|подробн/.test(ph)) { el.value = ''; el.dispatchEvent(new Event('input', {bubbles: true})); }
            }
            for (const el of form.querySelectorAll('div[contenteditable="true"]')) {
                if (el.offsetParent) { el.innerHTML = ''; el.textContent = ''; el.dispatchEvent(new InputEvent('input', {bubbles: true})); }
            }
            const fileInput = form.querySelector('#storyboard-upload-input');
            if (fileInput) { fileInput.value = ''; fileInput.dispatchEvent(new Event('input', {bubbles: true})); }
        }""")
        self.page.wait_for_timeout(400)

    def _wait_for_form_enabled(self, timeout_ms: int = 35000) -> None:
        """Ждёт, пока Pinterest включит поля формы (title/link) после обработки изображения. Поля изначально disabled."""
        try:
            self.page.wait_for_function(
                """() => {
                    const title = document.querySelector('#storyboard-selector-title');
                    return title && !title.disabled;
                }""",
                timeout=timeout_ms,
            )
            self.page.wait_for_timeout(600)
        except Exception:
            try:
                self.page.wait_for_timeout(3000)
                self.page.evaluate("""() => {
                    const t = document.querySelector('#storyboard-selector-title');
                    const l = document.querySelector('#WebsiteField');
                    if (t && t.disabled) t.removeAttribute('disabled');
                    if (l && l.disabled) l.removeAttribute('disabled');
                }""")
                self.page.wait_for_timeout(400)
            except Exception:
                pass

    def upload_new_image_without_reload(self, image_path: str) -> None:
        """Загружает новый файл в поле загрузки без перезагрузки страницы (Playwright set_input_files).
        Если поле загрузки не найдено (Pinterest сменил UI после предыдущего пина) — перезагружаем билдер и пробуем снова (до 2 раз)."""
        for attempt in range(3):
            try:
                self.page.locator(self.SEL["upload"]).wait_for(state="attached", timeout=20000 if attempt == 0 else 25000)
                break
            except Exception:
                if attempt >= 2:
                    raise
                self.log.warning("Поле загрузки не найдено, перезагружаем pin-builder (попытка %s/2)...", attempt + 1)
                self.page.goto(PinBuilderSession.PAGE_URL, timeout=self.timeout, wait_until="domcontentloaded")
                self.page.wait_for_load_state("load", timeout=15000)
                self.page.wait_for_timeout(1500)
        self.page.locator(self.SEL["upload"]).set_input_files(image_path)
        self.page.wait_for_selector(self.SEL["title"], state="visible", timeout=20000)
        self.page.wait_for_timeout(800)
        self._wait_for_form_enabled()

    def publish_pin(self, image_path: str, title: str, description: str, link: str,
                    board_name: str, error_out: list = None) -> bool:
        """
        Полный цикл: open_builder_once → reset_builder_fields → upload_new_image_without_reload
        → заполнение полей → выбор доски → публикация → ожидание успеха → ожидание сброса UI.
        Сохраняет существующую обработку ошибок и fallback-селекторы.
        """
        page = self.page
        log = self.log

        self.open_builder_once()
        self.reset_builder_fields()
        self.upload_new_image_without_reload(image_path)

        def _fill(loc, text: str, step_name: str, force: bool = True) -> bool:
            try:
                loc.wait_for(state="visible", timeout=8000)
                loc.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                loc.click(force=force)
                loc.fill(text)
                log.info("   ✓ %s", step_name)
                return True
            except Exception as e:
                log.warning("   %s: %s", step_name, e)
                return False

        title = jitter_text(title)
        _fill(page.locator(self.SEL["title"]), title, "Название")
        human_delay(0.1, 0.3)

        try:
            more_btn = page.locator(self.SEL["more_options"])
            more_btn.wait_for(state="visible", timeout=4000)
            more_btn.click(timeout=3000)
            page.wait_for_timeout(1200)  # даём панели «Подробнее» раскрыться, чтобы появилось поле описания
        except Exception:
            pass

        page.evaluate("window.scrollBy(0, 200)")
        page.wait_for_timeout(400)
        desc_ok = False
        try:
            description = jitter_text(description or "")
            filled = page.evaluate("""(desc) => {
                const form = document.querySelector('[id*="storyboard"]') || document.body;
                const descHint = (t) => /описание|description|подробн|detailed|add a|tell people|say more|what your|pin is about|write|describe/i.test((t || '').toLowerCase());
                for (const el of form.querySelectorAll('textarea, input[type="text"]')) {
                    const ph = (el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
                    if (descHint(ph) && el.offsetParent) {
                        el.focus(); el.value = desc;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
                const ed = Array.from(form.querySelectorAll('div[contenteditable="true"]')).filter(e => e.offsetParent);
                for (const el of ed) {
                    const par = el.closest('div');
                    const label = par ? (par.querySelector('label, [class*="label"]')?.textContent || par.textContent || '').toLowerCase() : '';
                    const ph = (el.getAttribute('data-placeholder') || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
                    if (descHint(label + ph) || ed.length <= 2) {
                        el.focus(); el.innerHTML = ''; el.textContent = desc;
                        el.dispatchEvent(new InputEvent('input', {bubbles: true, data: desc}));
                        return true;
                    }
                }
                if (ed.length > 0) {
                    const el = ed[ed.length - 1];
                    el.focus(); el.innerHTML = ''; el.textContent = desc;
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: desc}));
                    return true;
                }
                return false;
            }""", description)
            if filled:
                desc_ok = True
        except Exception:
            pass
        if not desc_ok:
            try:
                loc = page.locator(
                    '[placeholder*="подробное описание" i], [placeholder*="описание" i], '
                    '[placeholder*="detailed" i], [placeholder*="description" i], [placeholder*="tell people" i], '
                    'div[contenteditable="true"]'
                ).first
                loc.wait_for(state="visible", timeout=5000)
                loc.click(force=True)
                page.wait_for_timeout(300)
                for ch in description:
                    page.keyboard.type(ch)
                    time.sleep(random.uniform(0.02, 0.08))
                desc_ok = True
            except Exception:
                pass

        if link:
            link_filled = page.evaluate("""(url) => {
                const form = document.querySelector('[id*="storyboard"]') || document.body;
                let el = form.querySelector('#WebsiteField') || form.querySelector('input[placeholder*="ссылка"]') || form.querySelector('input[placeholder*="ссылк"]') || form.querySelector('input[placeholder*="link"]');
                if (el && el.offsetParent) {
                    el.focus(); el.value = url;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
                return false;
            }""", link)
            if not link_filled:
                _fill(page.locator(self.SEL["link"]), link, "Ссылка")
        page.wait_for_timeout(200)

        try:
            board_btn = page.locator(self.SEL["board_dropdown"])
            board_btn.wait_for(state="visible", timeout=5000)
            board_btn.click(timeout=3000, force=True)
            page.wait_for_timeout(800)
            try:
                search_input = page.locator(self.SEL["board_search"]).first
                search_input.wait_for(state="visible", timeout=2000)
                search_input.fill(board_name)
                page.wait_for_timeout(1000)
            except Exception:
                pass
            try:
                board_item = page.locator('[id*="storyboard"]').get_by_text(board_name, exact=False).first
                board_item.wait_for(state="visible", timeout=2500)
                board_item.click(timeout=3000, force=True)
            except Exception:
                try:
                    board_item = page.locator('div[role="listbox"], div[role="dialog"]').get_by_text(board_name, exact=False).first
                    board_item.wait_for(state="visible", timeout=1500)
                    board_item.click(timeout=3000, force=True)
                except Exception:
                    pass
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.locator(self.SEL["title"]).click(force=True)
            page.wait_for_timeout(300)
        except Exception as e:
            log.warning("   Ошибка выбора доски: %s", e)

        page.wait_for_timeout(400)
        page.evaluate("""window.scrollTo(0, document.body.scrollHeight); document.querySelector('[id*="storyboard"]')?.scrollIntoView({block: 'end'}); window.scrollBy(0, 500);""")
        page.wait_for_timeout(600)
        url_before_click = page.url
        try:
            publish_btn = page.locator('[data-test-id*="publish" i], [data-test-id*="Publish"]').first
            publish_btn.scroll_into_view_if_needed(timeout=4000)
            publish_btn.click(timeout=10000, force=True)
        except Exception:
            try:
                publish_btn = page.get_by_role("button", name=re.compile(r"Опубликовать|Publish", re.I)).first
                publish_btn.scroll_into_view_if_needed(timeout=4000)
                publish_btn.click(timeout=10000, force=True)
            except Exception:
                try:
                    btn = page.locator('button[type="submit"]').first
                    btn.scroll_into_view_if_needed(timeout=4000)
                    btn.click(timeout=10000, force=True)
                except Exception:
                    page.evaluate("""() => {
                        window.scrollTo(0, document.body.scrollHeight);
                        const scope = document.querySelector('[id*="storyboard"]') || document.body;
                        const all = Array.from(scope.querySelectorAll('button, [role="button"]'));
                        const btn = all.find(b => /Опубликовать|Publish/i.test(b.textContent || '') && !b.closest('[role="navigation"]'));
                        const sub = scope.querySelector('button[type="submit"]');
                        const target = (btn && !btn.disabled) ? btn : (sub && !sub.disabled) ? sub : null;
                        if (target) { target.scrollIntoView({block: 'end'}); target.click(); }
                    }""")
        page.wait_for_timeout(2000)
        success_phrases = [
            'pin created', 'опубликовано', 'published', 'successfully', 'done', 'готово',
            'ваш пин опубликован', 'pin published', 'saved', 'created', 'добавлен', 'создан',
            'your pin', 'pin was', 'пин создан', 'пин добавлен', 'added to', 'добавлен в',
        ]
        for attempt in range(30):
            page.wait_for_timeout(1000)
            url_now = page.url
            if "/pin/" in url_now and url_now != url_before_click:
                log.info("   ✓ Пин опубликован (URL: /pin/)")
                self._wait_ui_reset_then_return_to_builder()
                return True
            try:
                close_btn = page.locator('[aria-label="Close"], [aria-label="Закрыть"], [data-test-id="modal-close-button"], [role="dialog"] button').first
                if close_btn.is_visible():
                    close_btn.click(timeout=500)
                    page.wait_for_timeout(500)
            except Exception:
                pass
            try:
                success_els = page.locator('[role="alert"], [role="status"], [class*="toast"], [class*="Toast"], [data-test-id*="success"], [class*="modal"], [class*="dialog"]')
                for i in range(min(success_els.count(), 15)):
                    el = success_els.nth(i)
                    if el.is_visible():
                        txt = (el.text_content() or "").lower()
                        if any(p in txt for p in success_phrases):
                            log.info("   ✓ Пин опубликован (toast)")
                            page.wait_for_timeout(1500)
                            self._wait_ui_reset_then_return_to_builder()
                            return True
            except Exception:
                pass
            try:
                if page.get_by_text("Ваш пин опубликован").first.is_visible(timeout=0):
                    log.info("   ✓ Пин опубликован (тост «Ваш пин опубликован»)")
                    page.wait_for_timeout(1500)
                    self._wait_ui_reset_then_return_to_builder()
                    return True
            except Exception:
                pass
            try:
                if page.get_by_text("Опубликовано").first.is_visible(timeout=0):
                    log.info("   ✓ Пин опубликован (статус «Опубликовано» в сайдбаре)")
                    page.wait_for_timeout(1500)
                    self._wait_ui_reset_then_return_to_builder()
                    return True
            except Exception:
                pass
            found = page.evaluate("""() => {
                const txt = document.body.innerText.toLowerCase();
                return /ваш пин опубликован|pin published|опубликовано|pin created|saved|добавлен|создан|added to/.test(txt);
            }""")
            if found:
                log.info("   ✓ Пин опубликован (текст на странице)")
                self._wait_ui_reset_then_return_to_builder()
                return True
            if attempt >= 6 and "pin-creation-tool" in url_now:
                form_reset = page.evaluate("""() => {
                    const titleEl = document.querySelector('#storyboard-selector-title');
                    const linkEl = document.querySelector('#WebsiteField');
                    const t = titleEl ? (titleEl.value || '').trim() : '';
                    const l = linkEl ? (linkEl.value || '').trim() : '';
                    if (t || l) return false;
                    const ph = (titleEl && titleEl.placeholder) ? titleEl.placeholder.toLowerCase() : '';
                    const defaultPlaceholder = !ph || ph.includes('название') || ph.includes('title') || ph.includes('add');
                    return defaultPlaceholder;
                }""")
                if form_reset:
                    log.info("   ✓ Пин опубликован (форма сброшена — поля пустые)")
                    self._wait_ui_reset_then_return_to_builder()
                    return True
            try:
                err_els = page.locator('[role="alert"], [class*="error"], [data-test-id*="error"]')
                for i in range(min(err_els.count(), 5)):
                    el = err_els.nth(i)
                    if el.is_visible():
                        txt = (el.text_content() or "").strip()
                        if txt and len(txt) > 3 and any(k in txt.lower() for k in ['error', 'ошибка', 'failed', 'invalid', 'не удалось']):
                            log.warning("   Обнаружена ошибка Pinterest: %s", txt[:150])
                            if error_out is not None:
                                error_out.clear()
                                error_out.append(txt[:200])
                            return False
            except Exception:
                pass
        log.warning("   Публикация не подтверждена за 30 сек (URL: %s)", page.url[:80])
        if error_out is not None:
            error_out.clear()
            error_out.append("Публикация не подтверждена: не перешли на /pin/ и нет toast об успехе")
        return False

    def _wait_ui_reset_then_return_to_builder(self) -> None:
        """После успешной публикации ждёт сброс UI и возвращает страницу на pin-builder для следующего пина.
        Всегда перезагружаем страницу билдера, иначе после «Пин опубликован» Pinterest меняет UI и
        #storyboard-upload-input пропадает — следующие пины падают по таймауту. Ждём появления поля загрузки."""
        self.page.wait_for_timeout(2000)
        self.page.goto(PinBuilderSession.PAGE_URL, timeout=self.timeout, wait_until="domcontentloaded")
        self.page.wait_for_load_state("load", timeout=15000)
        self.page.wait_for_timeout(1200)
        # Критично: не возвращаемся, пока поле загрузки не появится (React может отрисовать форму позже)
        try:
            self.page.locator(self.SEL["upload"]).wait_for(state="attached", timeout=20000)
            self.page.wait_for_timeout(500)
        except Exception:
            self.log.warning("Поле загрузки не появилось за 20 сек после перезагрузки билдера, повторный goto...")
            self.page.goto(PinBuilderSession.PAGE_URL, timeout=self.timeout, wait_until="domcontentloaded")
            self.page.wait_for_load_state("load", timeout=15000)
            self.page.locator(self.SEL["upload"]).wait_for(state="attached", timeout=20000)


def create_pin_playwright(page, image_path: str, title: str, description: str, link: str,
                          board_name: str, timeout: int = 30000, logger=None, error_out: list = None,
                          reuse_page: bool = False) -> bool:
    """
    Публикует пин через Playwright. Используется в автопостинге.
    page — Playwright Page с загруженными cookies.
    error_out: опциональный list для записи текста ошибки (error_out[0] = str(e)).
    reuse_page: если True — переиспользует страницу pin-builder через PinBuilderSession (open_builder_once, reset_builder_fields, upload_new_image_without_reload).
    """
    import logging
    log = logger or logging.getLogger("PinMaster")

    if reuse_page:
        try:
            session = PinBuilderSession(page, logger=log, timeout=timeout)
            return session.publish_pin(image_path, title, description, link, board_name, error_out=error_out)
        except Exception as e:
            err_str = str(e)
            log.error("Ошибка Playwright (PinBuilderSession): %s", e)
            import traceback
            log.warning(traceback.format_exc())
            if error_out is not None:
                error_out.clear()
                error_out.append(err_str)
            return False

    PCS = __import__("pinterest_selectors").PinCreationSelectors
    SEL = {
        "upload": "#storyboard-upload-input",
        "title": "#storyboard-selector-title",
        "link": "#WebsiteField",
        "more_options": '[data-test-id="storyboard-show-more-options-button"]',
        "board_dropdown": '[data-test-id="board-dropdown-select-button"]',
        "board_search": 'input[placeholder*="поиск" i], input[placeholder*="search" i], input[type="search"]',
    }

    def _fill(loc, text: str, step_name: str, force: bool = True) -> bool:
        try:
            loc.wait_for(state="visible", timeout=8000)
            loc.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            loc.click(force=force)
            loc.fill(text)
            log.info("   ✓ %s", step_name)
            return True
        except Exception as e:
            log.warning("   %s: %s", step_name, e)
            return False

    try:
        page.goto(PCS.PAGE_URL, timeout=timeout, wait_until="domcontentloaded")
        try:
            import random
            for _ in range(random.randint(2, 5)):
                page.mouse.move(random.randint(0, 800), random.randint(0, 600))
                time.sleep(random.uniform(0.1, 0.3))
        except Exception:
            pass
        human_delay(0.5, 1.5)
        page.wait_for_load_state("load", timeout=12000)
        page.wait_for_timeout(1000)
        page.evaluate("document.documentElement.style.zoom = '1';")

        page.locator(SEL["upload"]).wait_for(state="attached", timeout=10000)
        page.locator(SEL["upload"]).set_input_files(image_path)
        page.wait_for_selector(SEL["title"], state="visible", timeout=20000)
        page.wait_for_timeout(1200)
        try:
            page.wait_for_function(
                """() => { const t = document.querySelector('#storyboard-selector-title'); return t && !t.disabled; }""",
                timeout=35000,
            )
            page.wait_for_timeout(600)
        except Exception:
            try:
                page.wait_for_timeout(3000)
                page.evaluate("""() => {
                    const t = document.querySelector('#storyboard-selector-title');
                    const l = document.querySelector('#WebsiteField');
                    if (t && t.disabled) t.removeAttribute('disabled');
                    if (l && l.disabled) l.removeAttribute('disabled');
                }""")
                page.wait_for_timeout(400)
            except Exception:
                pass

        title = jitter_text(title)
        _fill(page.locator(SEL["title"]), title, "Название")
        human_delay(0.2, 0.6)

        try:
            more_btn = page.locator(SEL["more_options"])
            more_btn.wait_for(state="visible", timeout=4000)
            more_btn.click(timeout=3000)
            page.wait_for_timeout(1200)  # даём панели «Подробнее» раскрыться
        except Exception:
            pass

        # Описание — JS или keyboard.type
        page.evaluate("window.scrollBy(0, 200)")
        page.wait_for_timeout(400)
        desc_ok = False
        try:
            description = jitter_text(description or "")
            filled = page.evaluate("""(desc) => {
                const form = document.querySelector('[id*="storyboard"]') || document.body;
                const descHint = (t) => /описание|description|подробн|detailed|add a|tell people|say more|what your|pin is about|write|describe/i.test((t || '').toLowerCase());
                for (const el of form.querySelectorAll('textarea, input[type="text"]')) {
                    const ph = (el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
                    if (descHint(ph) && el.offsetParent) {
                        el.focus(); el.value = desc;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
                const ed = Array.from(form.querySelectorAll('div[contenteditable="true"]')).filter(e => e.offsetParent);
                for (const el of ed) {
                    const par = el.closest('div');
                    const label = par ? (par.querySelector('label, [class*="label"]')?.textContent || par.textContent || '').toLowerCase() : '';
                    const ph = (el.getAttribute('data-placeholder') || el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
                    if (descHint(label + ph) || ed.length <= 2) {
                        el.focus(); el.innerHTML = ''; el.textContent = desc;
                        el.dispatchEvent(new InputEvent('input', {bubbles: true, data: desc}));
                        return true;
                    }
                }
                if (ed.length > 0) {
                    const el = ed[ed.length - 1];
                    el.focus(); el.innerHTML = ''; el.textContent = desc;
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: desc}));
                    return true;
                }
                return false;
            }""", description)
            if filled:
                desc_ok = True
        except Exception:
            pass
        if not desc_ok:
            try:
                loc = page.locator(
                    '[placeholder*="подробное описание" i], [placeholder*="описание" i], '
                    '[placeholder*="detailed" i], [placeholder*="description" i], [placeholder*="tell people" i], '
                    'div[contenteditable="true"]'
                ).first
                loc.wait_for(state="visible", timeout=5000)
                loc.click(force=True)
                page.wait_for_timeout(300)
                for ch in description:
                    page.keyboard.type(ch)
                    time.sleep(random.uniform(0.02, 0.08))
                desc_ok = True
            except Exception:
                pass

        if link:
            link_filled = page.evaluate("""(url) => {
                const form = document.querySelector('[id*="storyboard"]') || document.body;
                let el = form.querySelector('#WebsiteField') || form.querySelector('input[placeholder*="ссылка"]') || form.querySelector('input[placeholder*="ссылк"]') || form.querySelector('input[placeholder*="link"]');
                if (el && el.offsetParent) {
                    el.focus(); el.value = url;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
                return false;
            }""", link)
            if not link_filled:
                _fill(page.locator(SEL["link"]), link, "Ссылка")
        page.wait_for_timeout(200)

        # Выбор доски — с поиском в модалке
        try:
            board_btn = page.locator(SEL["board_dropdown"])
            board_btn.wait_for(state="visible", timeout=5000)
            board_btn.click(timeout=3000, force=True)
            page.wait_for_timeout(800)

            try:
                search_input = page.locator(SEL["board_search"]).first
                search_input.wait_for(state="visible", timeout=2000)
                search_input.fill(board_name)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            try:
                board_item = page.locator('[id*="storyboard"]').get_by_text(board_name, exact=False).first
                board_item.wait_for(state="visible", timeout=2500)
                board_item.click(timeout=3000, force=True)
            except Exception:
                try:
                    board_item = page.locator('div[role="listbox"], div[role="dialog"]').get_by_text(board_name, exact=False).first
                    board_item.wait_for(state="visible", timeout=1500)
                    board_item.click(timeout=3000, force=True)
                except Exception:
                    pass

            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.locator(SEL["title"]).click(force=True)
            page.wait_for_timeout(300)
        except Exception as e:
            log.warning("   Ошибка выбора доски: %s", e)

        page.wait_for_timeout(400)
        page.evaluate("""window.scrollTo(0, document.body.scrollHeight); document.querySelector('[id*="storyboard"]')?.scrollIntoView({block: 'end'}); window.scrollBy(0, 500);""")
        page.wait_for_timeout(600)
        url_before_click = page.url
        try:
            publish_btn = page.locator('[data-test-id*="publish" i], [data-test-id*="Publish"]').first
            publish_btn.scroll_into_view_if_needed(timeout=4000)
            publish_btn.click(timeout=10000, force=True)
        except Exception:
            try:
                publish_btn = page.get_by_role("button", name=re.compile(r"Опубликовать|Publish", re.I)).first
                publish_btn.scroll_into_view_if_needed(timeout=4000)
                publish_btn.click(timeout=10000, force=True)
            except Exception:
                try:
                    btn = page.locator('button[type="submit"]').first
                    btn.scroll_into_view_if_needed(timeout=4000)
                    btn.click(timeout=10000, force=True)
                except Exception:
                    page.evaluate("""() => {
                        window.scrollTo(0, document.body.scrollHeight);
                        const scope = document.querySelector('[id*="storyboard"]') || document.body;
                        const all = Array.from(scope.querySelectorAll('button, [role="button"]'));
                        const btn = all.find(b => /Опубликовать|Publish/i.test(b.textContent || '') && !b.closest('[role="navigation"]'));
                        const sub = scope.querySelector('button[type="submit"]');
                        const target = (btn && !btn.disabled) ? btn : (sub && !sub.disabled) ? sub : null;
                        if (target) { target.scrollIntoView({block: 'end'}); target.click(); }
                    }""")
        page.wait_for_timeout(2000)
        success_phrases = [
            'pin created', 'опубликовано', 'published', 'successfully', 'done', 'готово',
            'ваш пин опубликован', 'pin published', 'saved', 'created', 'добавлен', 'создан',
            'your pin', 'pin was', 'пин создан', 'пин добавлен', 'added to', 'добавлен в',
        ]
        for attempt in range(30):
            page.wait_for_timeout(1000)
            url_now = page.url
            if "/pin/" in url_now and url_now != url_before_click:
                log.info("   ✓ Пин опубликован (URL: /pin/)")
                return True
            try:
                close_btn = page.locator('[aria-label="Close"], [aria-label="Закрыть"], [data-test-id="modal-close-button"], [role="dialog"] button').first
                if close_btn.is_visible():
                    close_btn.click(timeout=500)
                    page.wait_for_timeout(500)
            except Exception:
                pass
            try:
                success_els = page.locator('[role="alert"], [role="status"], [class*="toast"], [class*="Toast"], [data-test-id*="success"], [class*="modal"], [class*="dialog"]')
                for i in range(min(success_els.count(), 15)):
                    el = success_els.nth(i)
                    if el.is_visible():
                        txt = (el.text_content() or "").lower()
                        if any(p in txt for p in success_phrases):
                            log.info("   ✓ Пин опубликован (toast)")
                            page.wait_for_timeout(1500)
                            return True
            except Exception:
                pass
            try:
                if page.get_by_text("Ваш пин опубликован").first.is_visible(timeout=0):
                    log.info("   ✓ Пин опубликован (тост «Ваш пин опубликован»)")
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                pass
            try:
                if page.get_by_text("Опубликовано").first.is_visible(timeout=0):
                    log.info("   ✓ Пин опубликован (статус «Опубликовано» в сайдбаре)")
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                pass
            found = page.evaluate("""() => {
                const txt = document.body.innerText.toLowerCase();
                return /ваш пин опубликован|pin published|опубликовано|pin created|saved|добавлен|создан|added to/.test(txt);
            }""")
            if found:
                log.info("   ✓ Пин опубликован (текст на странице)")
                return True
            if attempt >= 6 and "pin-creation-tool" in url_now:
                form_reset = page.evaluate("""() => {
                    const titleEl = document.querySelector('#storyboard-selector-title');
                    const linkEl = document.querySelector('#WebsiteField');
                    const t = titleEl ? (titleEl.value || '').trim() : '';
                    const l = linkEl ? (linkEl.value || '').trim() : '';
                    if (t || l) return false;
                    const ph = (titleEl && titleEl.placeholder) ? titleEl.placeholder.toLowerCase() : '';
                    const defaultPlaceholder = !ph || ph.includes('название') || ph.includes('title') || ph.includes('add');
                    return defaultPlaceholder;
                }""")
                if form_reset:
                    log.info("   ✓ Пин опубликован (форма сброшена — поля пустые)")
                    return True
            try:
                err_els = page.locator('[role="alert"], [class*="error"], [data-test-id*="error"]')
                for i in range(min(err_els.count(), 5)):
                    el = err_els.nth(i)
                    if el.is_visible():
                        txt = (el.text_content() or "").strip()
                        if txt and len(txt) > 3 and any(k in txt.lower() for k in ['error', 'ошибка', 'failed', 'invalid', 'не удалось']):
                            log.warning("   Обнаружена ошибка Pinterest: %s", txt[:150])
                            if error_out is not None:
                                error_out.clear()
                                error_out.append(txt[:200])
                            return False
            except Exception:
                pass
        log.warning("   Публикация не подтверждена за 30 сек (URL: %s)", page.url[:80])
        if error_out is not None:
            error_out.clear()
            error_out.append("Публикация не подтверждена: не перешли на /pin/ и нет toast об успехе")
        return False
    except Exception as e:
        err_str = str(e)
        log.error("Ошибка Playwright публикации: %s", e)
        import traceback
        log.warning(traceback.format_exc())
        if error_out is not None:
            error_out.clear()
            error_out.append(err_str)
        return False


class PinterestPublisher:
    """Класс для публикации пинов на Pinterest"""
    
    PIN_CREATION_URL = PCS.PAGE_URL
    
    def __init__(self, parser: Optional[PinterestSeleniumParser] = None):
        """
        Инициализирует публикатор.
        
        Args:
            parser: Существующий парсер с инициализированным браузером (опционально)
        """
        self.last_error = ""
        if parser and parser.driver:
            self.driver = parser.driver
            self.own_driver = False
        else:
            self.own_driver = True
            self._setup_driver()
    
    def _setup_driver(self):
        """Настраивает Chrome драйвер"""
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(f'user-agent={PinterestConfig.USER_AGENT}')
        chrome_options.add_argument('--window-size=1200,1080')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            service = Service(get_chromedriver_path())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✓ Chrome драйвер запущен для публикации")
            
            # Загружаем cookies если есть
            cookies = load_cookies_from_file("pinterest_cookies.json")
            if cookies:
                self.driver.get("https://www.pinterest.com")
                time.sleep(2)
                for name, value in cookies.items():
                    try:
                        self.driver.add_cookie({
                            'name': name,
                            'value': value,
                            'domain': '.pinterest.com',
                            'path': '/'
                        })
                    except Exception:
                        pass
                self.driver.refresh()
                time.sleep(2)
        except Exception as e:
            print(f"Ошибка при запуске Chrome драйвера: {e}")
            raise

    def _dump_debug_state(self, reason: str) -> None:
        """Сохраняет краткую диагностику текущей страницы."""
        try:
            url = self.driver.current_url
        except Exception:
            url = "<unknown>"
        try:
            title = self.driver.title
        except Exception:
            title = "<unknown>"

        print(f"  [debug] reason={reason}")
        print(f"  [debug] url={url}")
        print(f"  [debug] title={title}")

        try:
            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
            print(f"  [debug] file_inputs={len(file_inputs)}")
            for i, inp in enumerate(file_inputs[:5], 1):
                try:
                    inp_id = inp.get_attribute("id") or ""
                    inp_name = inp.get_attribute("name") or ""
                    inp_test = inp.get_attribute("data-test-id") or ""
                    inp_accept = inp.get_attribute("accept") or ""
                    print(f"  [debug] input#{i}: id='{inp_id}', name='{inp_name}', data-test-id='{inp_test}', accept='{inp_accept}'")
                except Exception:
                    continue
        except Exception:
            pass

        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join(os.getcwd(), "debug")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"pin_creation_{reason}_{ts}.html")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            print(f"  [debug] page_source saved: {out_path}")
        except Exception:
            pass
    
    def get_boards_from_creation_tool(self) -> List[Dict[str, str]]:
        """
        Получает список всех досок через страницу создания пина (pin-creation-tool).
        Открывает модальное окно выбора доски и парсит все доступные доски.
        
        Returns:
            Список словарей с информацией о досках
        """
        boards = []
        try:
            print("\nПолучение досок через pin-creation-tool...")
            # Переходим на страницу создания пина
            self.driver.get(self.PIN_CREATION_URL)
            time.sleep(3)
            
            # Ждем загрузки страницы
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                )
            except Exception:
                time.sleep(2)
            
            # Ищем поле выбора доски
            print("  Поиск поля выбора доски...")
            board_field = None
            
            # Способ 1: Поиск по тексту/placeholder
            try:
                all_elements = self.driver.find_elements(By.XPATH, PCS.BOARD_FIELD_XPATH)
                for elem in all_elements:
                    try:
                        if elem.is_displayed():
                            # Проверяем что это не в header/nav
                            is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                            if not is_in_header:
                                board_field = elem
                                print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}")
                                break
                    except Exception:
                        continue
            except Exception:
                pass
            
            # Способ 2: Поиск через input/button/div
            if not board_field:
                try:
                    all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                    all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                    all_divs = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                    
                    for elem in all_inputs + all_buttons + all_divs:
                        try:
                            if not elem.is_displayed():
                                continue
                            placeholder = elem.get_attribute('placeholder') or ''
                            aria_label = elem.get_attribute('aria-label') or ''
                            text = elem.text.strip() or ''
                            
                            if ('доск' in placeholder.lower() or 'board' in placeholder.lower() or
                                'доск' in aria_label.lower() or 'board' in aria_label.lower() or
                                'доск' in text.lower() or 'board' in text.lower()):
                                is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                                if not is_in_header:
                                    board_field = elem
                                    print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}")
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass
            
            if not board_field:
                print("  ⚠ Поле выбора доски не найдено")
                return []
            
            # Кликаем на поле выбора доски
            print("  Открытие модального окна с досками...")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
            time.sleep(1)
            
            try:
                board_field.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", board_field)
                except Exception:
                    print("  ⚠ Не удалось кликнуть на поле доски")
                    return []
            
            # Ждем открытия модального окна
            print("  Ожидание открытия модального окна...")
            modal_visible = False
            for attempt in range(10):
                try:
                    modals = self.driver.find_elements(By.CSS_SELECTOR,
                        'div[role="dialog"], div[class*="modal"], div[class*="overlay"], div[class*="BoardPicker"]')
                    search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                        'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                    if modals or search_inputs:
                        visible_modals = [m for m in modals if m.is_displayed()]
                        visible_search = [s for s in search_inputs if s.is_displayed()]
                        if visible_modals or visible_search:
                            modal_visible = True
                            print(f"  ✓ Модальное окно открыто (попытка {attempt + 1})")
                            break
                except Exception:
                    pass
                if attempt < 9:
                    time.sleep(0.5)
            
            if not modal_visible:
                print("  ⚠ Модальное окно не открылось")
                return []
            
            # Дополнительное ожидание для загрузки досок
            time.sleep(2)
            
            # Прокручиваем модальное окно для загрузки всех досок
            print("  Прокрутка модального окна для загрузки всех досок...")
            try:
                modal = self.driver.find_elements(By.CSS_SELECTOR, PCS.BOARD_MODAL_CSS)[0]
                for i in range(5):
                    self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
                    time.sleep(1)
            except Exception:
                # Прокручиваем всю страницу
                for i in range(5):
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
            
            time.sleep(2)
            
            # Парсим все доски из модального окна
            print("  Парсинг досок из модального окна...")
            seen_boards = set()
            
            # Ищем элементы с названиями досок
            board_elements = self.driver.find_elements(By.XPATH,
                "//div[@role='dialog']//*[text() and not(self::input) and not(self::textarea) and not(self::button)]")
            
            for elem in board_elements:
                try:
                    if not elem.is_displayed():
                        continue
                    
                    text = elem.text.strip()
                    if not text or len(text) > 100 or len(text) < 1:
                        continue
                    
                    text_lower = text.lower()
                    # Исключаем служебные тексты
                    excluded = ['поиск', 'search', 'создать', 'create', 'все доски', 'all boards', 
                               'найдена доска', 'board found', 'выберите доску', 'select board',
                               'закрыть', 'close', 'отмена', 'cancel']
                    
                    if any(ex in text_lower for ex in excluded):
                        continue
                    
                    # Проверяем что это не кнопка или ссылка на другую страницу
                    parent = elem.find_element(By.XPATH, './..')
                    parent_tag = parent.tag_name.lower()
                    if parent_tag in ['button', 'a']:
                        continue
                    
                    # Проверяем что текст не начинается с символов (эмодзи, иконки)
                    if text[0] in ['_', '-', '•', '·']:
                        continue
                    
                    if text not in seen_boards:
                        seen_boards.add(text)
                        boards.append({
                            'board_name': text,
                            'board_url': ''  # URL не нужен для выбора
                        })
                        print(f"    ✓ Найдена доска: {text}")
                except Exception:
                    continue
            
            # Также ищем через более специфичные селекторы
            try:
                # Ищем элементы с data-атрибутами или специальными классами
                specific_boards = self.driver.find_elements(By.CSS_SELECTOR,
                    'div[role="dialog"] [data-test-id*="board"], div[role="dialog"] [class*="Board"]')
                for elem in specific_boards:
                    try:
                        if not elem.is_displayed():
                            continue
                        text = elem.text.strip()
                        if text and text not in seen_boards and 1 < len(text) < 100:
                            text_lower = text.lower()
                            if not any(ex in text_lower for ex in excluded):
                                seen_boards.add(text)
                                boards.append({
                                    'board_name': text,
                                    'board_url': ''
                                })
                                print(f"    ✓ Найдена доска (спец. селектор): {text}")
                    except Exception:
                        continue
            except Exception:
                pass
            
            # Закрываем модальное окно (ESC или клик вне окна)
            try:
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                time.sleep(1)
            except Exception:
                pass
            
            print(f"  ✓ Всего найдено досок: {len(boards)}")
            return boards
            
        except Exception as e:
            print(f"  ⚠ Ошибка при получении досок через pin-creation-tool: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_user_boards(self) -> List[Dict[str, str]]:
        """
        Получает список досок пользователя.
        Сначала пытается через pin-creation-tool, затем через парсер.
        
        Returns:
            Список словарей с информацией о досках
        """
        # Пробуем получить доски через pin-creation-tool (самый актуальный способ)
        boards = self.get_boards_from_creation_tool()
        if boards:
            return boards
        
        # Если не получилось, используем парсер
        try:
            if hasattr(self, 'parser') and self.parser:
                account_info = self.parser.get_account_info()
                if account_info:
                    username = account_info.get('username')
                    if username:
                        boards = self.parser.parse_user_boards(username=username)
                        return boards
        except Exception as e:
            print(f"Ошибка при получении досок через парсер: {e}")
        
        return []
    
    def create_pin(self, image_path: str, title: str, description: str, 
                   link: str, board_name: str) -> bool:
        """
        Создает и публикует пин на Pinterest.
        Селекторы полей и кнопок: pinterest_selectors.PinCreationSelectors (PCS).
        
        Args:
            image_path: Путь к изображению для загрузки
            title: Название пина
            description: Описание пина
            link: Ссылка для пина
            board_name: Название доски для публикации
            
        Returns:
            True если публикация успешна, False иначе
        """
        try:
            if not self.driver:
                self.last_error = "Браузер не инициализирован"
                return False
            print("\n" + "=" * 80)
            print("ПУБЛИКАЦИЯ ПИНА")
            print("=" * 80)
            
            # Проверяем существование файла
            if not os.path.exists(image_path):
                self.last_error = f"Файл не найден: {image_path}"
                print(f"⚠ {self.last_error}")
                return False
            
            print(f"Изображение: {image_path}")
            print(f"Название: {title}")
            print(f"Описание: {description}")
            print(f"Ссылка: {link}")
            print(f"Доска: {board_name}")
            
            # Переходим на страницу создания пина (селекторы: pinterest_selectors.PinCreationSelectors)
            print(f"\nПереход на страницу создания пина: {self.PIN_CREATION_URL}")
            self.driver.get(self.PIN_CREATION_URL)
            time.sleep(3)
            
            # Ждем загрузки страницы
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
                )
            except Exception:
                time.sleep(2)
            
            # Шаг 1: Загружаем изображение
            print("\n1. Загрузка изображения...")
            try:
                # Получаем абсолютный путь к файлу
                abs_image_path = os.path.abspath(image_path)
                print(f"Путь к файлу: {abs_image_path}")
                
                # Ищем поле загрузки по ID (из анализа страницы)
                file_input = None
                
                # Способ 1: Поиск по ID (самый надежный)
                try:
                    file_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.ID, PCS.UPLOAD_INPUT_ID))
                    )
                    print("✓ Найдено поле загрузки по ID")
                except Exception:
                    pass
                
                # Способ 2: Поиск всех input[type="file"] и выбираем видимый/активный
                if not file_input:
                    try:
                        all_file_inputs = self.driver.find_elements(By.CSS_SELECTOR, PCS.UPLOAD_INPUT_CSS)
                        for inp in all_file_inputs:
                            try:
                                # Проверяем что элемент доступен (даже если не видим, может быть скрыт но активен)
                                inp_id = inp.get_attribute('id') or ''
                                if 'upload' in inp_id.lower() or 'storyboard' in inp_id.lower():
                                    file_input = inp
                                    print(f"✓ Найдено поле загрузки (способ 2): {inp_id or 'без ID'}")
                                    break
                                # Или берем первый доступный
                                if not file_input:
                                    file_input = inp
                                    print("✓ Найдено поле загрузки (способ 2): первый доступный input[type='file']")
                            except Exception:
                                continue
                    except Exception:
                        pass
                
                # Способ 3: Поиск через data-атрибуты или другие селекторы
                if not file_input:
                    try:
                        file_input = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, PCS.UPLOAD_INPUT_ALT))
                        )
                        print("✓ Найдено поле загрузки (способ 3: data-атрибут)")
                    except Exception:
                        pass
                
                if file_input:
                    # Загружаем файл
                    file_input.send_keys(abs_image_path)
                    print(f"✓ Файл выбран: {abs_image_path}")
                    
                    # Ждем загрузки изображения (страница изменится)
                    print("Ожидание загрузки изображения...")
                    time.sleep(5)
                    
                    # Проверяем, что изображение загрузилось и форма появилась
                    try:
                        WebDriverWait(self.driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, PCS.FORM_READY_CSS))
                        )
                        print("✓ Изображение загружено, форма готова")
                        time.sleep(2)  # Дополнительная задержка для полной загрузки
                    except Exception:
                        print("⚠ Таймаут ожидания загрузки формы, продолжаем...")
                        time.sleep(5)
                else:
                    self.last_error = "Поле загрузки файла не найдено — Pinterest мог изменить страницу"
                    print("⚠ " + self.last_error)
                    self._dump_debug_state("upload_input_not_found")
                    return False
            except Exception as e:
                if isinstance(e, InvalidSessionIdException):
                    self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                    return False
                self.last_error = f"Ошибка загрузки изображения: {e}"
                print(f"⚠ {self.last_error}")
                import traceback
                traceback.print_exc()
                return False
            
            # Шаг 2: Сначала выбираем доску
            # ВАЖНО: После выбора доски заполняем все поля заново, так как они могут сброситься
            print(f"\n2. Выбор доски: {board_name}...")
            board_selected = False
            try:
                # Ищем поле выбора доски
                print("  Поиск поля выбора доски...")
                all_board_elements = self.driver.find_elements(By.XPATH,
                    "//*[contains(text(), 'Доска') or contains(text(), 'Board') or contains(@placeholder, 'доск') or contains(@placeholder, 'board')]")
                
                board_field = None
                # Ищем поле через альтернативные методы
                try:
                    all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                    all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                    all_divs = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                    
                    for elem in all_inputs + all_buttons + all_divs:
                        try:
                            if not elem.is_displayed():
                                continue
                            placeholder = elem.get_attribute('placeholder') or ''
                            aria_label = elem.get_attribute('aria-label') or ''
                            text = elem.text.strip() or ''
                            
                            if ('доск' in placeholder.lower() or 'board' in placeholder.lower() or
                                'доск' in aria_label.lower() or 'board' in aria_label.lower() or
                                'доск' in text.lower() or 'board' in text.lower()):
                                is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                                if not is_in_header:
                                    board_field = elem
                                    print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}")
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass
                
                if board_field:
                    # Кликаем на поле выбора доски
                    print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                    time.sleep(1)
                    
                    clicked = False
                    try:
                        board_field.click()
                        clicked = True
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", board_field)
                            clicked = True
                        except Exception:
                            pass
                    
                    if clicked:
                        print("✓ Поле выбора доски открыто")
                        # Ждем открытия модального окна
                        print("  Ожидание открытия модального окна...")
                        time.sleep(2)
                        
                        # Ищем модальное окно
                        modal_visible = False
                        for attempt in range(5):
                            try:
                                modals = self.driver.find_elements(By.CSS_SELECTOR,
                                    'div[role="dialog"], div[class*="modal"], div[class*="overlay"]')
                                search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                    'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                                if modals or search_inputs:
                                    visible_modals = [m for m in modals if m.is_displayed()]
                                    visible_search = [s for s in search_inputs if s.is_displayed()]
                                    if visible_modals or visible_search:
                                        modal_visible = True
                                        print("  ✓ Модальное окно открыто")
                                        break
                            except Exception:
                                pass
                            if attempt < 4:
                                time.sleep(0.5)
                        
                        if modal_visible:
                            # Ищем доску в модальном окне
                            print(f"  Поиск доски '{board_name}' в модальном окне...")
                            
                            # Прокручиваем модал и ждём загрузки досок
                            try:
                                modal = self.driver.find_element(By.CSS_SELECTOR, PCS.BOARD_MODAL_CSS)
                                for _ in range(3):
                                    self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
                                    time.sleep(0.3)
                                self.driver.execute_script("arguments[0].scrollTop = 0;", modal)
                                time.sleep(0.5)
                            except Exception:
                                pass
                            # Ищем по тексту (contains(., ) включает вложенный текст)
                            board_name_esc = board_name.replace("'", "\\'")
                            board_options = []
                            try:
                                board_options = self.driver.find_elements(By.XPATH,
                                    f"//div[@role='dialog']//*[contains(., '{board_name_esc}') and not(self::input) and not(self::textarea)]")
                                board_options = [opt for opt in board_options 
                                               if (opt.text or '').strip() and len((opt.text or '').strip()) < 100]
                                # Альтернатива: ищем по slug (board_oliver3 -> Board oliver3)
                                if not board_options:
                                    all_text_elements = self.driver.find_elements(By.XPATH,
                                        "//div[@role='dialog']//*[text() and not(self::input) and not(self::textarea) and not(self::button)]")
                                    for elem in all_text_elements:
                                        try:
                                            text = (elem.text or '').strip()
                                            if text and len(text) < 100:
                                                # Сравниваем: board_name, с заменой _ на пробел
                                                bn_lower = board_name.lower()
                                                txt_lower = text.lower()
                                                bn_alt = bn_lower.replace('_', ' ')
                                                if bn_lower in txt_lower or bn_alt in txt_lower or txt_lower in bn_lower:
                                                    if elem.is_displayed():
                                                        board_options.append(elem)
                                        except Exception:
                                            continue
                            except Exception:
                                pass
                            
                            if board_options:
                                # Выбираем доску через JavaScript — избегаем stale element reference
                                clicked_js = self.driver.execute_script("""
                                    var boardName = arguments[0];
                                    var bnLower = boardName.toLowerCase();
                                    var bnAlt = bnLower.replace(/_/g, ' ');
                                    var dialog = document.querySelector('div[role="dialog"]');
                                    if (!dialog) return false;
                                    var candidates = [];
                                    var els = dialog.querySelectorAll('div, span, button, a');
                                    for (var i = 0; i < els.length; i++) {
                                        var el = els[i];
                                        if (!el.offsetParent) continue;
                                        var t = (el.textContent || '').trim();
                                        if (t.length < 2 || t.length > 60) continue;
                                        var tl = t.toLowerCase();
                                        if ((tl.indexOf(bnLower) >= 0 || tl.indexOf(bnAlt) >= 0) && !/^(поиск|search|создать|create|закрыть|close|отмена|cancel|все доски|all boards)$/i.test(tl)) {
                                            var childCount = el.querySelectorAll('div, span, button, a').length;
                                            candidates.push({el: el, text: t, len: t.length, children: childCount});
                                        }
                                    }
                                    candidates.sort(function(a,b){ return a.len - b.len || a.children - b.children; });
                                    for (var j = 0; j < candidates.length; j++) {
                                        try {
                                            candidates[j].el.scrollIntoView({block: 'center'});
                                            candidates[j].el.click();
                                            return candidates[j].text;
                                        } catch(e) {}
                                    }
                                    return false;
                                """, board_name)
                                if clicked_js:
                                    board_selected = True
                                    print(f"✓ Доска выбрана: {clicked_js}")
                                    time.sleep(2)
                            else:
                                # Если точного совпадения нет — ищем через JS (без stale reference)
                                print("  Точное совпадение не найдено, ищем все доски через JS...")
                                clicked_alt = self.driver.execute_script("""
                                    var dialog = document.querySelector('div[role="dialog"]');
                                    if (!dialog) return false;
                                    var ex = /поиск|search|создать|create|все доски|all boards|закрыть|close|отмена|cancel|новый|new/i;
                                    var els = dialog.querySelectorAll('div, span, button');
                                    for (var i = 0; i < els.length; i++) {
                                        var el = els[i];
                                        if (!el.offsetParent) continue;
                                        var t = (el.textContent || '').trim();
                                        if (t.length < 2 || t.length > 60) continue;
                                        if (ex.test(t)) continue;
                                        if (/^[_\\-•·#]/.test(t)) continue;
                                        el.scrollIntoView({block: 'center'});
                                        el.click();
                                        return t;
                                    }
                                    return false;
                                """)
                                if clicked_alt:
                                    board_selected = True
                                    print(f"✓ Доска выбрана (первая доступная): '{clicked_alt}'")
                                    time.sleep(2)
            except Exception as e:
                print(f"⚠ Ошибка при выборе доски: {e}")
            
            if not board_selected:
                print("⚠ ВНИМАНИЕ: Доска не выбрана! Публикация может не пройти.")
            
            # Шаг 3: Заполняем название
            print("\n3. Заполнение названия...")
            try:
                title_field = None
                
                # Способ 1: Поиск по ID (PCS.TITLE_INPUT_ID)
                try:
                    title_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, PCS.TITLE_INPUT_ID))
                    )
                    print("  ✓ Поле названия найдено по ID")
                except Exception:
                    pass
                
                # Способ 2: Поиск по placeholder (PCS.TITLE_PLACEHOLDER_CSS)
                if not title_field:
                    for selector in PCS.TITLE_PLACEHOLDER_CSS:
                        try:
                            title_field = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            if title_field:
                                break
                        except Exception:
                            continue
                
                if title_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_field)
                    time.sleep(1)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                    try:
                        title_field.click()
                        time.sleep(0.3)
                        # Очищаем через выделение и удаление
                        title_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                        time.sleep(0.2)
                        title_field.send_keys(Keys.DELETE)  # Удаляем
                        time.sleep(0.3)
                        # Заполняем через send_keys
                        title_field.send_keys(title)
                        time.sleep(1)  # Даем время на обработку
                        # Снимаем фокус для сохранения
                        self.driver.execute_script("arguments[0].blur();", title_field)
                        time.sleep(0.5)
                        # Кликаем вне поля для триггера сохранения
                        self.driver.execute_script("document.body.click();")
                        time.sleep(0.5)
                        print(f"✓ Название заполнено: {title}")
                    except Exception as e:
                        print(f"⚠ Ошибка заполнения названия: {e}")
                else:
                    print("⚠ Поле названия не найдено")
            except Exception as e:
                if isinstance(e, InvalidSessionIdException):
                    self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                    return False
                print(f"⚠ Ошибка при заполнении названия: {e}")
            
            # Шаг 4: Заполняем описание (может загружаться с задержкой)
            print("\n4. Заполнение описания...")
            try:
                # Ждем загрузки поля описания - оно может появиться не сразу
                print("  Ожидание загрузки поля описания...")
                
                # Сначала ждем немного после загрузки изображения
                time.sleep(3)
                
                desc_selectors = PCS.DESCRIPTION_SELECTORS
                desc_field = None
                max_wait = 15  # Максимальное время ожидания
                wait_interval = 0.5
                waited = 0
                
                while not desc_field and waited < max_wait:
                    for selector in desc_selectors:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            
                            for elem in elements:
                                if elem.tag_name == 'div' and elem.get_attribute('contenteditable') == 'true':
                                    placeholder = elem.get_attribute('placeholder') or ''

                                    if 'описание' in placeholder.lower() or 'description' in placeholder.lower() or 'подробное' in placeholder.lower():
                                        desc_field = elem
                                        print(f"  ✓ Поле описания найдено (contenteditable) через {waited:.1f}с")
                                        break
                                    if selector == 'div[contenteditable="true"]' and len(elements) > 1:
                                        desc_field = elements[1] if len(elements) > 1 else elements[0]
                                        print(f"  ✓ Поле описания найдено (contenteditable, второй) через {waited:.1f}с")
                                        break

                                elif elem.tag_name == 'textarea':
                                    placeholder = elem.get_attribute('placeholder') or ''
                                    if 'описание' in placeholder.lower() or 'description' in placeholder.lower() or 'подробное' in placeholder.lower():
                                        desc_field = elem
                                        print(f"  ✓ Поле описания найдено (textarea) через {waited:.1f}с")
                                        break
                            
                            if desc_field:
                                break
                        except Exception:
                            continue
                    
                    if not desc_field:
                        time.sleep(wait_interval)
                        waited += wait_interval
                
                # Если все еще не нашли, пробуем найти все textarea
                if not desc_field:
                    try:
                        all_textareas = self.driver.find_elements(By.TAG_NAME, 'textarea')
                        if len(all_textareas) > 1:
                            desc_field = all_textareas[1]  # Второй textarea обычно описание
                            print("  ✓ Поле описания найдено (второй textarea из списка)")
                        elif len(all_textareas) == 1:
                            # Проверяем, не название ли это
                            placeholder = all_textareas[0].get_attribute('placeholder') or ''
                            if 'описание' in placeholder.lower() or 'description' in placeholder.lower():
                                desc_field = all_textareas[0]
                                print("  ✓ Поле описания найдено (единственный textarea)")
                    except Exception:
                        pass
                
                if desc_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                    time.sleep(1)
                    
                    # Если это contenteditable div, используем специальный метод
                    if desc_field.tag_name == 'div' and desc_field.get_attribute('contenteditable') == 'true':
                        try:
                            # Фокусируемся на поле
                            self.driver.execute_script("arguments[0].focus();", desc_field)
                            desc_field.click()
                            time.sleep(0.5)
                            
                            # Очищаем содержимое через выделение и удаление (как пользователь)
                            desc_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                            time.sleep(0.2)
                            desc_field.send_keys(Keys.DELETE)  # Удаляем
                            time.sleep(0.3)
                            
                            # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод пользователя)
                            # Это критически важно - Pinterest может проверять, что ввод был реальным
                            desc_field.send_keys(description)
                            time.sleep(1.5)  # Даем время на обработку
                            
                            # Проверяем, что значение установилось
                            verify_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                            if verify_desc.strip() == description.strip():
                                print(f"✓ Описание заполнено (contenteditable): {description}")
                            else:
                                print(f"⚠ Описание не сохранилось, текущее: '{verify_desc[:50]}', ожидалось: '{description[:50]}'")
                                # Пробуем еще раз - выделяем весь текст и заменяем
                                try:
                                    desc_field.click()
                                    time.sleep(0.5)
                                    # Выделяем весь текст через Ctrl+A
                                    desc_field.send_keys(Keys.COMMAND + 'a')  # Mac
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)
                                    time.sleep(0.3)
                                    # Вводим текст заново
                                    desc_field.send_keys(description)
                                    time.sleep(1)
                                    verify_desc2 = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                                    if verify_desc2.strip() == description.strip():
                                        print(f"✓ Описание заполнено (повторная попытка): {description}")
                                    else:
                                        print(f"⚠ Описание все еще не сохранилось: '{verify_desc2[:50]}'")
                                except Exception as e3:
                                    print(f"⚠ Ошибка при повторной попытке: {e3}")
                        except Exception as e:
                            # Альтернативный способ для contenteditable
                            try:
                                desc_field.click()
                                time.sleep(0.5)
                                desc_field.send_keys(description)
                                time.sleep(1)
                                verify_desc = desc_field.text or desc_field.get_attribute('innerText') or ''
                                if verify_desc.strip() == description.strip():
                                    print(f"✓ Описание заполнено (send_keys): {description}")
                                else:
                                    print(f"⚠ Описание не сохранилось через send_keys: '{verify_desc[:50]}'")
                            except Exception:
                                print(f"⚠ Ошибка заполнения contenteditable: {e}")
                    else:
                        # Для textarea используем стандартный способ
                        try:
                            self.driver.execute_script("arguments[0].value = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", desc_field)
                            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", desc_field)
                            print(f"✓ Описание заполнено через JS: {description}")
                        except Exception:
                            # Если JS не сработал, пробуем обычный способ
                            try:
                                desc_field.click()
                                time.sleep(0.5)
                                # Пробуем clear только если элемент готов
                                if desc_field.is_enabled() and desc_field.is_displayed():
                                    try:
                                        desc_field.clear()
                                    except Exception:
                                        # Если clear не работает, используем только send_keys
                                        pass
                                desc_field.send_keys(description)
                                print(f"✓ Описание заполнено: {description}")
                            except Exception as e:
                                print(f"⚠ Ошибка при заполнении описания через send_keys: {e}")
                else:
                    print("⚠ Поле описания не найдено по селекторам, пробуем альтернативный метод...")
                    # Пробуем найти все textarea и contenteditable и использовать второй как описание
                    try:
                        all_textareas = self.driver.find_elements(By.TAG_NAME, 'textarea')
                        all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                        print(f"  Найдено textarea: {len(all_textareas)}, contenteditable: {len(all_contenteditable)}")
                        
                        # Пробуем использовать contenteditable (приоритет) или textarea как описание
                        if len(all_contenteditable) > 0:
                            # Используем первый contenteditable (обычно это описание)
                            desc_field = all_contenteditable[0]
                            print("  Используем contenteditable как описание")
                        elif len(all_textareas) > 1:
                            desc_field = all_textareas[1]
                            print("  Используем второй textarea как описание")
                        elif len(all_textareas) == 1:
                            # Проверяем placeholder - если не название, то это описание
                            placeholder = all_textareas[0].get_attribute('placeholder') or ''
                            if 'название' not in placeholder.lower() and 'title' not in placeholder.lower():
                                desc_field = all_textareas[0]
                                print("  Используем единственный textarea как описание")
                        
                        # Если нашли поле, заполняем его
                        if desc_field:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                            time.sleep(1)
                            
                            if desc_field.tag_name == 'div' and desc_field.get_attribute('contenteditable') == 'true':
                                try:
                                    # Фокусируемся на поле
                                    self.driver.execute_script("arguments[0].focus();", desc_field)
                                    desc_field.click()
                                    time.sleep(0.5)
                                    
                                    # Очищаем через выделение и удаление (как пользователь)
                                    desc_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)  # Удаляем
                                    time.sleep(0.3)
                                    
                                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                                    desc_field.send_keys(description)
                                    time.sleep(1.5)  # Даем время на обработку
                                    # Снимаем фокус для сохранения
                                    self.driver.execute_script("arguments[0].blur();", desc_field)
                                    time.sleep(0.5)
                                    # Кликаем вне поля для триггера сохранения
                                    self.driver.execute_script("document.body.click();")
                                    time.sleep(0.5)
                                    print(f"✓ Описание заполнено (contenteditable, альтернативный метод): {description}")
                                except Exception as e:
                                    print(f"⚠ Ошибка заполнения contenteditable: {e}")
                            else:
                                try:
                                    # Прокручиваем к полю и делаем видимым
                                    self.driver.execute_script(
                                        "arguments[0].scrollIntoView({block:'center'}); arguments[0].removeAttribute('hidden'); arguments[0].style.visibility='visible'; arguments[0].style.display='';",
                                        desc_field)
                                    time.sleep(0.5)
                                    # Для textarea пробуем send_keys
                                    desc_field.click()
                                    time.sleep(0.3)
                                    desc_field.send_keys(Keys.COMMAND + 'a')
                                    time.sleep(0.2)
                                    desc_field.send_keys(Keys.DELETE)
                                    time.sleep(0.3)
                                    desc_field.send_keys(description)
                                    time.sleep(1.5)
                                    self.driver.execute_script("arguments[0].blur();", desc_field)
                                    time.sleep(0.5)
                                    print(f"✓ Описание заполнено: {description}")
                                except Exception as e:
                                    # Fallback: заполняем через JavaScript
                                    try:
                                        self.driver.execute_script("""
                                            var el = arguments[0];
                                            el.value = arguments[1];
                                            el.dispatchEvent(new Event('input', {bubbles:true}));
                                            el.dispatchEvent(new Event('change', {bubbles:true}));
                                        """, desc_field, description)
                                        time.sleep(0.5)
                                        print(f"✓ Описание заполнено через JS: {description}")
                                    except Exception as je:
                                        print(f"⚠ Ошибка заполнения textarea: {e}, JS fallback: {je}")
                        else:
                            print("  ⚠ Не удалось найти поле описания альтернативным методом")
                    except Exception as e_alt:
                        print(f"  ⚠ Ошибка при альтернативном поиске описания: {e_alt}")
            except Exception as e:
                print(f"⚠ Ошибка при заполнении описания: {e}")
            
            # Шаг 5: Заполняем ссылку
            print("\n5. Заполнение ссылки...")
            try:
                link_field = None
                
                # Способ 1: Поиск по ID (PCS.LINK_FIELD_ID)
                try:
                    link_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, PCS.LINK_FIELD_ID))
                    )
                    print("  ✓ Поле ссылки найдено по ID")
                except Exception:
                    pass
                
                # Способ 2: Поиск по типу и placeholder (PCS.LINK_FIELD_CSS)
                if not link_field:
                    for selector in PCS.LINK_FIELD_CSS:
                        try:
                            link_field = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            # Проверяем, что это поле ссылки (не название)
                            placeholder = link_field.get_attribute('placeholder') or ''
                            if 'ссылк' in placeholder.lower() or 'link' in placeholder.lower() or selector == 'input[type="url"]':
                                break
                        except Exception:
                            continue
                
                if link_field:
                    # Прокручиваем к полю
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                    time.sleep(1)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод пользователя)
                    try:
                        link_field.click()
                        time.sleep(0.3)
                        
                        # Очищаем поле через выделение и удаление (как пользователь)
                        link_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                        time.sleep(0.2)
                        link_field.send_keys(Keys.DELETE)  # Удаляем
                        time.sleep(0.3)
                        
                        # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                        link_field.send_keys(link)
                        time.sleep(1.5)  # Даем время на обработку
                        
                        # Проверяем, что значение установилось
                        verify_link = link_field.get_attribute('value') or ''
                        if verify_link.strip() == link.strip():
                            print(f"✓ Ссылка заполнена: {link}")
                        else:
                            print(f"⚠ Ссылка не сохранилась, текущее: '{verify_link}'")
                            # Пробуем еще раз
                            try:
                                link_field.click()
                                time.sleep(0.3)
                                link_field.send_keys(Keys.COMMAND + 'a')
                                time.sleep(0.2)
                                link_field.send_keys(Keys.DELETE)
                                time.sleep(0.3)
                                link_field.send_keys(link)
                                time.sleep(1.5)
                                verify_link2 = link_field.get_attribute('value') or ''
                                if verify_link2.strip() == link.strip():
                                    print(f"✓ Ссылка заполнена (повторная попытка): {link}")
                                else:
                                    print(f"⚠ Ссылка все еще не сохранилась: '{verify_link2}'")
                            except Exception as e2:
                                print(f"⚠ Ошибка при повторной попытке: {e2}")
                    except Exception as e:
                        print(f"⚠ Ошибка заполнения ссылки: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print("⚠ Поле ссылки не найдено")
            except Exception as e:
                print(f"⚠ Ошибка при заполнении ссылки: {e}")
            
            # Доска уже выбрана выше (Шаг 2), пропускаем этот шаг
            # После выбора доски проверяем и восстанавливаем значения полей, если они сбросились
            print("\nПроверка и восстановление значений полей после выбора доски...")
            time.sleep(2)  # Даем время на закрытие модального окна
            
            try:
                # Проверяем поле названия
                try:
                    title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                    current_title = title_field.get_attribute('value') or ''
                    print(f"  Текущее значение названия: '{current_title}'")
                    if not current_title or current_title.strip() != title.strip():
                        print("  Восстанавливаем название...")
                        self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", title_field)
                        time.sleep(0.5)
                        # Проверяем, что значение установилось
                        verify_title = title_field.get_attribute('value') or ''
                        print(f"  ✓ Название восстановлено: '{verify_title}'")
                except Exception as e:
                    print(f"  ⚠ Ошибка при проверке названия: {e}")
                
                # Проверяем поле описания
                try:
                    all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                    print(f"  Найдено contenteditable элементов: {len(all_contenteditable)}")
                    if all_contenteditable:
                        desc_field = all_contenteditable[0]
                        current_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        print(f"  Текущее значение описания: '{current_desc[:50]}'")
                        if not current_desc or current_desc.strip() != description.strip():
                            print("  Восстанавливаем описание...")
                            # Прокручиваем к полю
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                            time.sleep(0.5)
                            # Кликаем на поле
                            desc_field.click()
                            time.sleep(0.5)
                            # Очищаем содержимое
                            self.driver.execute_script("arguments[0].innerText = '';", desc_field)
                            self.driver.execute_script("arguments[0].textContent = '';", desc_field)
                            time.sleep(0.3)
                            # Вставляем текст
                            self.driver.execute_script("arguments[0].innerText = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].textContent = arguments[1];", desc_field, description)
                            # Триггерим события
                            self.driver.execute_script("""
                                var event = new Event('input', { bubbles: true });
                                arguments[0].dispatchEvent(event);
                                var changeEvent = new Event('change', { bubbles: true });
                                arguments[0].dispatchEvent(changeEvent);
                            """, desc_field)
                            time.sleep(0.5)
                            # Проверяем, что значение установилось
                            verify_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                            print(f"  ✓ Описание восстановлено: '{verify_desc[:50]}'")
                        else:
                            print(f"  ✓ Описание уже заполнено: '{current_desc[:50]}'")
                except Exception as e:
                    if isinstance(e, InvalidSessionIdException):
                        self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                        return False
                    print(f"  ⚠ Ошибка при проверке описания: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Проверяем поле ссылки
                try:
                    # Ждем, пока элемент станет доступным
                    link_field = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, PCS.LINK_FIELD_ID))
                    )
                    
                    # Проверяем, что элемент видим и готов
                    if not link_field.is_displayed():
                        print("  ⚠ Поле ссылки не видимо, прокручиваем...")
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                        time.sleep(1)
                    
                    current_link = link_field.get_attribute('value') or ''
                    print(f"  Текущее значение ссылки: '{current_link}'")
                    if not current_link or current_link.strip() != link.strip():
                        print("  Восстанавливаем ссылку...")
                        # Прокручиваем к полю
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                        time.sleep(0.5)
                        
                        # Пробуем очистить через JS (безопаснее)
                        try:
                            self.driver.execute_script("arguments[0].value = '';", link_field)
                            time.sleep(0.2)
                        except Exception:
                            pass
                        
                        # Пробуем кликнуть и очистить через Selenium (только если элемент готов)
                        try:
                            # Ждем, пока элемент станет кликабельным
                            WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable(link_field)
                            )
                            link_field.click()
                            time.sleep(0.3)
                            # Очищаем через Selenium только если элемент готов
                            if link_field.is_enabled() and link_field.is_displayed():
                                try:
                                    link_field.clear()
                                except Exception:
                                    # Если clear не работает, используем только JS
                                    pass
                        except Exception:
                            # Если клик не работает, используем только JS
                            print("  Используем только JavaScript для заполнения...")
                        
                        time.sleep(0.3)
                        
                        # Заполняем через JS (надежнее)
                        self.driver.execute_script("arguments[0].value = arguments[1];", link_field, link)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", link_field)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", link_field)
                        time.sleep(0.5)
                        
                        # Проверяем, что значение установилось
                        verify_link = link_field.get_attribute('value') or ''
                        if verify_link.strip() != link.strip():
                            # Если не сработало, пробуем через send_keys (только если поле пустое)
                            if not verify_link.strip():
                                try:
                                    # Убеждаемся, что элемент готов
                                    if link_field.is_enabled() and link_field.is_displayed():
                                        link_field.send_keys(link)
                                        time.sleep(0.5)
                                        verify_link = link_field.get_attribute('value') or ''
                                except Exception:
                                    pass
                        print(f"  ✓ Ссылка восстановлена: '{verify_link}'")
                    else:
                        print(f"  ✓ Ссылка уже заполнена: '{current_link}'")
                except Exception as e:
                    if isinstance(e, InvalidSessionIdException):
                        self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                        return False
                    print(f"  ⚠ Ошибка при проверке ссылки: {e}")
                    import traceback
                    traceback.print_exc()
            except Exception as e:
                if isinstance(e, InvalidSessionIdException):
                    self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                    return False
                print(f"  ⚠ Ошибка при восстановлении полей: {e}")
                import traceback
                traceback.print_exc()
            
            # Старый код выбора доски удален - доска выбирается в Шаге 2
            
            # Шаг 6: Публикуем пин
                if all_board_elements:
                    print(f"  Найдено {len(all_board_elements)} элементов, связанных с досками")
                    for i, elem in enumerate(all_board_elements[:5], 1):
                        try:
                            tag = elem.tag_name
                            placeholder = elem.get_attribute('placeholder') or ''
                            text = elem.text.strip()[:50] or ''
                            print(f"    {i}. {tag}: placeholder='{placeholder[:30]}', text='{text}'")
                        except Exception:
                            pass
                # Пробуем разные селекторы для поля выбора доски
                # ВАЖНО: Ищем поле выбора доски в форме создания пина, НЕ глобальный поиск
                board_selectors = [
                    # По placeholder
                    'input[placeholder*="Выберите доску" i]',
                    'input[placeholder*="Select board" i]',
                    'input[placeholder*="доск" i]',
                    'input[placeholder*="board" i]',
                    # По label и связанному input
                    'label:has-text("Доска") + input',
                    'label:has-text("Board") + input',
                    # По div с текстом "Доска" и связанному input
                    'div:has-text("Доска") input',
                    'div:has-text("Board") input',
                    # По классам
                    'div[class*="board"] input[placeholder*="доск" i]',
                    'div[class*="board"] input[placeholder*="board" i]',
                    'div[class*="Board"] input',
                    # Кнопки и div с role="button"
                    'button[aria-label*="доск" i]',
                    'button[aria-label*="board" i]',
                    'div[role="button"][aria-label*="доск" i]',
                    'div[role="button"][aria-label*="board" i]',
                    # Поиск через XPath по тексту "Доска"
                    None  # Будет обработан отдельно
                ]
                
                board_field = None
                for selector in board_selectors:
                    try:
                        if selector is None:
                            # XPath поиск по тексту "Доска" и связанному элементу
                            try:
                                # Ищем label или div с текстом "Доска"
                                label = self.driver.find_element(By.XPATH,
                                    "//label[contains(text(), 'Доска')] | //div[contains(text(), 'Доска')] | //span[contains(text(), 'Доска')]")
                                # Ищем следующий input или button
                                board_field = label.find_element(By.XPATH,
                                    "./following-sibling::input | ./following-sibling::button | ./following-sibling::div[@role='button'] | ./ancestor::div[1]//input | ./ancestor::div[1]//button")
                                if board_field and board_field.is_displayed():
                                    break
                            except Exception:
                                pass
                        else:
                            board_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                            # Проверяем, что это не глобальный поиск
                            if board_field and board_field.is_displayed():
                                # Проверяем, что это поле в форме создания пина (не в header/sidebar)
                                try:
                                    # Исключаем элементы в header или sidebar
                                    is_in_header = board_field.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav | ./ancestor::*[contains(@class, "header")] | ./ancestor::*[contains(@class, "sidebar")]')
                                    if not is_in_header:
                                        # Проверяем placeholder для уверенности
                                        placeholder = board_field.get_attribute('placeholder') or ''
                                        if 'доск' in placeholder.lower() or 'board' in placeholder.lower() or 'выберите' in placeholder.lower() or 'select' in placeholder.lower():
                                            break
                                except Exception:
                                    # Если не можем проверить, все равно используем
                                    break
                    except Exception:
                        continue
                
                if board_field:
                    # Кликаем на поле выбора доски
                    print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                    time.sleep(1)
                    
                    # Пробуем кликнуть разными способами
                    clicked = False
                    try:
                        board_field.click()
                        clicked = True
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", board_field)
                            clicked = True
                        except Exception:
                            pass
                    
                    if clicked:
                        print("✓ Поле выбора доски открыто")
                    else:
                        print("⚠ Не удалось кликнуть на поле выбора доски")
                    
                    # Ждем открытия модального окна с выбором доски
                    print("  Ожидание открытия модального окна...")
                    time.sleep(2)
                    
                    # Пробуем найти модальное окно
                    modal_visible = False
                    for attempt in range(5):  # Проверяем до 5 раз
                        try:
                            # Ищем модальное окно (overlay, dialog, modal)
                            modals = self.driver.find_elements(By.CSS_SELECTOR,
                                'div[role="dialog"], div[class*="modal"], div[class*="overlay"], div[class*="dialog"]')
                            
                            # Также ищем по наличию поисковой строки "Поиск"
                            search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                            
                            if modals or search_inputs:
                                visible_modals = [m for m in modals if m.is_displayed()]
                                visible_search = [s for s in search_inputs if s.is_displayed()]
                                if visible_modals or visible_search:
                                    modal_visible = True
                                    print("  ✓ Модальное окно открыто")
                                    break
                        except Exception:
                            pass
                        if attempt < 4:
                            time.sleep(0.5)
                    
                    if not modal_visible:
                        print("  ⚠ Модальное окно не найдено, ждем еще...")
                        time.sleep(2)
                    
                    # Ищем доску в модальном окне
                    print("  Поиск доски в модальном окне...")
                    board_options = []
                    
                    # Ищем доску в модальном окне - пробуем разные способы
                    # ВАЖНО: Ищем в списке досок БЕЗ использования поиска
                    
                    # Способ 1: Ищем список досок в модальном окне (обычно это div с классом или ролью)
                    try:
                        # Ищем контейнер со списком досок (обычно после текста "Все доски" или подобного)
                        list_containers = self.driver.find_elements(By.XPATH,
                            "//div[@role='dialog']//div[contains(text(), 'Все доски') or contains(text(), 'All boards')]/following-sibling::div | //div[@role='dialog']//div[contains(text(), 'Все доски') or contains(text(), 'All boards')]/parent::div//div")
                        
                        board_options = []
                        for container in list_containers:
                            if container.is_displayed():
                                # Ищем все элементы внутри контейнера с текстом доски
                                items = container.find_elements(By.XPATH, f".//*[contains(text(), '{board_name}')]")
                                for item in items:
                                    if item.is_displayed() and len(item.text.strip()) < 100:
                                        # Проверяем, что это не поисковая строка
                                        text = item.text.strip().lower()
                                        if 'поиск' not in text and 'search' not in text:
                                            board_options.append(item)
                        
                        if board_options:
                            print(f"  Найдено {len(board_options)} потенциальных досок в списке")
                    except Exception:
                        pass
                    
                    # Способ 2: Ищем все кликабельные элементы в модальном окне с текстом доски
                    if not board_options:
                        try:
                            # Ищем все элементы в модальном окне с текстом доски
                            all_elements = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[contains(text(), '{board_name}') and not(self::input) and not(self::textarea)]")
                            
                            board_options = []
                            for elem in all_elements:
                                try:
                                    if elem.is_displayed():
                                        text = elem.text.strip()
                                        # Проверяем, что текст содержит название доски и не слишком длинный
                                        if text and len(text) < 100 and board_name.lower() in text.lower():
                                            # Проверяем, что это не поисковая строка или другие элементы
                                            text_lower = text.lower()
                                            if ('поиск' not in text_lower and 'search' not in text_lower and 
                                                'создать' not in text_lower and 'create' not in text_lower):
                                                board_options.append(elem)
                                except Exception:
                                    continue
                            
                            if board_options:
                                print(f"  Найдено {len(board_options)} потенциальных досок в модальном окне")
                        except Exception:
                            pass
                    
                    # Способ 2: Ищем по точному тексту
                    if not board_options:
                        try:
                            board_options = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[normalize-space(text())='{board_name}' and not(self::input)]")
                            board_options = [opt for opt in board_options if opt.is_displayed()]
                            if board_options:
                                print(f"  Найдено {len(board_options)} элементов с точным текстом '{board_name}'")
                        except Exception:
                            pass
                    
                    # Способ 3: Ищем элементы с вхождением названия доски
                    if not board_options:
                        try:
                            board_options = self.driver.find_elements(By.XPATH,
                                f"//div[@role='dialog']//*[contains(normalize-space(text()), '{board_name}') and not(self::input)]")
                            # Фильтруем видимые и короткие (названия досок обычно короткие)
                            board_options = [opt for opt in board_options 
                                           if opt.is_displayed() and len(opt.text.strip()) < 100]
                            if board_options:
                                print(f"  Найдено {len(board_options)} элементов с текстом '{board_name}'")
                        except Exception:
                            pass
                    
                    # Способ 2: Ищем в контейнерах модального окна
                    if not board_options:
                        try:
                            # Ищем контейнеры модального окна
                            modal_containers = self.driver.find_elements(By.CSS_SELECTOR,
                                'div[role="dialog"], div[class*="modal"], div[class*="overlay"], div[class*="dialog"], div[class*="listbox"]')
                            
                            for container in modal_containers:
                                if container.is_displayed():
                                    # Ищем все элементы внутри контейнера с текстом доски
                                    items = container.find_elements(By.XPATH,
                                        f".//*[contains(text(), '{board_name}') and not(self::input)]")
                                    if items:
                                        board_options = [item for item in items if item.is_displayed()]
                                        if board_options:
                                            print(f"  Найдено {len(board_options)} опций в модальном окне")
                                            break
                        except Exception:
                            pass
                    
                    # Способ 3: Ищем кликабельные элементы (div, button) с текстом доски
                    if not board_options:
                        try:
                            clickable_with_text = self.driver.find_elements(By.XPATH,
                                f"//div[contains(text(), '{board_name}')] | //button[contains(text(), '{board_name}')]")
                            board_options = [item for item in clickable_with_text if item.is_displayed()]
                            if board_options:
                                print(f"  Найдено {len(board_options)} кликабельных элементов")
                        except Exception:
                            pass
                    
                    board_found = False
                    print(f"  Проверка {len(board_options)} найденных элементов...")
                    for i, option in enumerate(board_options, 1):
                        try:
                            option_text = option.text.strip()
                            # Выводим для отладки первые несколько
                            if i <= 3:
                                print(f"    Элемент {i}: '{option_text[:50]}'")
                            
                            # Проверяем точное совпадение или вхождение названия доски
                            if option_text and (
                                option_text.lower() == board_name.lower() or
                                option_text.lower().strip() == board_name.lower() or
                                board_name.lower() in option_text.lower() or
                                option_text.lower() in board_name.lower()
                            ):
                                print(f"  ✓ Найдена подходящая доска: '{option_text}'")
                                
                                # Прокручиваем к опции
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                time.sleep(0.5)
                                
                                # Пробуем кликнуть - несколько способов
                                clicked = False
                                
                                # Способ 1: Ищем кликабельный родительский элемент
                                try:
                                    # Ищем родительский div или button, который может быть кликабельным
                                    parent = option.find_element(By.XPATH, 
                                        './ancestor::div[@role="button" or @onclick or contains(@class, "click")][1] | ./ancestor::button[1] | ./parent::div[1]')
                                    if parent:
                                        parent.click()
                                        clicked = True
                                        print("  ✓ Клик на родительский элемент")
                                except Exception:
                                    pass
                                
                                # Способ 2: Прямой клик на элемент
                                if not clicked:
                                    try:
                                        option.click()
                                        clicked = True
                                        print("  ✓ Прямой клик на элемент")
                                    except Exception:
                                        pass
                                
                                # Способ 3: Клик через JS
                                if not clicked:
                                    try:
                                        self.driver.execute_script("arguments[0].click();", option)
                                        clicked = True
                                        print("  ✓ Клик через JS")
                                    except Exception:
                                        pass
                                
                                # Способ 4: Клик на родительский элемент через JS
                                if not clicked:
                                    try:
                                        parent = self.driver.execute_script("return arguments[0].parentElement || arguments[0].closest('div[role=\"button\"]') || arguments[0].closest('button');", option)
                                        if parent:
                                            self.driver.execute_script("arguments[0].click();", parent)
                                            clicked = True
                                            print("  ✓ Клик на родитель через JS")
                                    except Exception:
                                        pass
                                
                                if clicked:
                                    print(f"✓ Доска выбрана из модального окна: {board_name}")
                                    board_found = True
                                    board_selected = True
                                    time.sleep(2)  # Ждем закрытия модального окна
                                    break
                                else:
                                    print(f"  ⚠ Не удалось кликнуть на элемент {i}")
                        except Exception as e_opt:
                            if i <= 3:
                                print(f"  ⚠ Ошибка при обработке элемента {i}: {e_opt}")
                            continue
                    
                    # ТОЛЬКО если не нашли в списке, используем поиск ВНУТРИ модального окна
                    if not board_found:
                        print(f"⚠ Доска '{board_name}' не найдена в списке, используем поиск в модальном окне...")
                        try:
                            # ВАЖНО: Ищем поле поиска ТОЛЬКО внутри модального окна (dialog), НЕ глобальный поиск
                            time.sleep(1)
                            
                            # Ищем модальное окно
                            modal = None
                            try:
                                modal = self.driver.find_element(By.CSS_SELECTOR, PCS.BOARD_MODAL_CSS)
                            except Exception:
                                pass
                            
                            if modal:
                                # Ищем поле поиска ВНУТРИ модального окна
                                search_inputs = modal.find_elements(By.CSS_SELECTOR, 
                                    'input[placeholder*="Поиск" i], input[placeholder*="Search" i], input[type="search"], input[type="text"]')
                                
                                # Фильтруем - берем только поле поиска в модальном окне
                                input_field = None
                                for inp in search_inputs:
                                    if inp.is_displayed():
                                        placeholder = inp.get_attribute('placeholder') or ''
                                        # Проверяем, что это поле поиска в модальном окне (не глобальный поиск)
                                        if 'поиск' in placeholder.lower() or 'search' in placeholder.lower():
                                            input_field = inp
                                            break
                                
                                if input_field:
                                    print("  ✓ Найдено поле поиска в модальном окне")
                                    # Очищаем поле (с проверкой готовности)
                                    try:
                                        if input_field.is_enabled() and input_field.is_displayed():
                                            try:
                                                input_field.clear()
                                            except Exception:
                                                # Если clear не работает, используем JS
                                                self.driver.execute_script("arguments[0].value = '';", input_field)
                                    except Exception:
                                        # Если не удалось, используем только JS
                                        self.driver.execute_script("arguments[0].value = '';", input_field)
                                    time.sleep(0.5)
                                    
                                    # Вводим название доски
                                    input_field.send_keys(board_name)
                                    time.sleep(2)  # Ждем результатов поиска досок
                                    
                                    # Ищем в результатах поиска - пробуем разные селекторы
                                    search_results = []
                                
                                # Способ 1: Стандартные селекторы
                                search_selectors = [
                                    'div[role="option"]',
                                    'li[role="option"]',
                                    'div[class*="option"]',
                                    'li[class*="option"]',
                                    'div[class*="item"]',
                                    'li[class*="item"]',
                                    'div[class*="board"]',
                                    'li[class*="board"]'
                                ]
                                
                                for selector in search_selectors:
                                    try:
                                        results = self.driver.find_elements(By.CSS_SELECTOR, selector)
                                        visible_results = [r for r in results if r.is_displayed()]
                                        if visible_results:
                                            search_results = visible_results
                                            print(f"  Найдено {len(search_results)} результатов поиска через селектор")
                                            break
                                    except Exception:
                                        continue
                                
                                # Способ 2: Поиск по тексту (точное совпадение или вхождение)
                                if not search_results:
                                    try:
                                        # Сначала точное совпадение
                                        search_results = self.driver.find_elements(By.XPATH,
                                            f"//*[normalize-space(text())='{board_name}' and not(self::input)]")
                                        if not search_results:
                                            # Потом вхождение
                                            search_results = self.driver.find_elements(By.XPATH,
                                                f"//*[contains(normalize-space(text()), '{board_name}') and not(self::input)]")
                                        search_results = [r for r in search_results if r.is_displayed() and len(r.text.strip()) < 100]
                                        if search_results:
                                            print(f"  Найдено {len(search_results)} результатов по тексту")
                                    except Exception:
                                        pass
                                
                                # Кликаем на первый подходящий результат
                                print(f"  Обработка {len(search_results)} результатов поиска...")
                                for i, result in enumerate(search_results, 1):
                                    try:
                                        result_text = result.text.strip()
                                        # Выводим информацию для отладки
                                        if i <= 3:  # Показываем первые 3 для отладки
                                            print(f"    Результат {i}: '{result_text[:50]}'")
                                        
                                        # Проверяем, что это действительно доска
                                        # Ищем точное совпадение или вхождение названия доски
                                        text_lower = result_text.lower()
                                        board_lower = board_name.lower()
                                        
                                        if result_text and (
                                            board_lower == text_lower or
                                            board_lower in text_lower or
                                            text_lower.startswith(board_lower) or
                                            f" {board_lower} " in f" {text_lower} " or
                                            f" {board_lower}\n" in f" {text_lower}\n"
                                        ):
                                            print(f"  ✓ Найдена подходящая доска: '{result_text[:50]}'")
                                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", result)
                                            time.sleep(0.5)
                                            
                                            # Пробуем кликнуть - несколько способов
                                            clicked = False
                                            
                                            # Способ 1: Прямой клик
                                            try:
                                                result.click()
                                                clicked = True
                                            except Exception:
                                                pass
                                            
                                            # Способ 2: Через JS
                                            if not clicked:
                                                try:
                                                    self.driver.execute_script("arguments[0].click();", result)
                                                    clicked = True
                                                except Exception:
                                                    pass
                                            
                                            # Способ 3: Клик на родительский элемент
                                            if not clicked:
                                                try:
                                                    parent = self.driver.execute_script("return arguments[0].parentElement;", result)
                                                    if parent:
                                                        self.driver.execute_script("arguments[0].click();", parent)
                                                        clicked = True
                                                except Exception:
                                                    pass
                                            
                                            # Способ 4: Ищем кликабельный родитель
                                            if not clicked:
                                                try:
                                                    clickable_parent = result.find_element(By.XPATH, 
                                                        "./ancestor::div[contains(@class, 'board') or contains(@role, 'option') or @onclick] | ./ancestor::button[1]")
                                                    if clickable_parent:
                                                        clickable_parent.click()
                                                        clicked = True
                                                except Exception:
                                                    pass
                                            
                                            if clicked:
                                                board_selected = True
                                                print(f"✓ Доска выбрана из результатов поиска: {board_name}")
                                                time.sleep(1)  # Ждем закрытия модального окна
                                                break
                                            else:
                                                print(f"  ⚠ Не удалось кликнуть на результат {i}")
                                    except Exception as e_result:
                                        if i <= 3:  # Показываем ошибки для первых 3
                                            print(f"  ⚠ Ошибка при обработке результата {i}: {e_result}")
                                        continue
                                
                                    if not board_selected:
                                        print("⚠ Результаты поиска не найдены, пробуем Enter...")
                                        # Если не нашли в результатах, пробуем Enter (но это не идеально)
                                        input_field.send_keys(Keys.ENTER)
                                        board_selected = True
                                        print(f"✓ Доска введена через Enter: {board_name}")
                                else:
                                    print("  ⚠ Поле поиска в модальном окне не найдено")
                            else:
                                print("  ⚠ Модальное окно не найдено для поиска")
                        except Exception as e2:
                            print(f"⚠ Не удалось использовать поиск доски: {e2}")
                            import traceback
                            traceback.print_exc()
                else:
                    print("⚠ Поле выбора доски не найдено, пробуем альтернативные методы...")
                    # Пробуем найти поле через более широкий поиск
                    try:
                        # Ищем все input и button элементы на странице
                        all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                        all_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                        all_divs = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                        
                        print(f"  Проверка {len(all_inputs)} input, {len(all_buttons)} button, {len(all_divs)} div[role='button']...")
                        
                        for elem in all_inputs + all_buttons + all_divs:
                            try:
                                if not elem.is_displayed():
                                    continue
                                placeholder = elem.get_attribute('placeholder') or ''
                                aria_label = elem.get_attribute('aria-label') or ''
                                text = elem.text.strip() or ''
                                
                                # Проверяем, что это поле выбора доски
                                if ('доск' in placeholder.lower() or 'board' in placeholder.lower() or
                                    'доск' in aria_label.lower() or 'board' in aria_label.lower() or
                                    'доск' in text.lower() or 'board' in text.lower()):
                                    # Проверяем, что это не глобальный поиск
                                    is_in_header = elem.find_elements(By.XPATH, './ancestor::header | ./ancestor::nav')
                                    if not is_in_header:
                                        board_field = elem
                                        print(f"  ✓ Найдено поле выбора доски: {elem.tag_name}, placeholder='{placeholder[:30]}'")
                                        break
                            except Exception:
                                continue
                        
                        if board_field:
                            # Используем найденное поле - продолжаем выполнение
                            print("  ✓ Поле найдено через альтернативный метод")
                            # Теперь используем найденное поле - переходим к открытию модального окна
                            # Кликаем на поле выбора доски
                            print(f"  Клик на поле выбора доски (tag: {board_field.tag_name})...")
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", board_field)
                            time.sleep(1)
                            
                            # Пробуем кликнуть разными способами
                            clicked = False
                            try:
                                board_field.click()
                                clicked = True
                            except Exception:
                                try:
                                    self.driver.execute_script("arguments[0].click();", board_field)
                                    clicked = True
                                except Exception:
                                    pass
                            
                            if clicked:
                                print("✓ Поле выбора доски открыто")
                                # Продолжаем с открытием модального окна и выбором доски
                                # Используем ту же логику, что и в основном блоке выше
                                # Ждем открытия модального окна
                                print("  Ожидание открытия модального окна...")
                                time.sleep(2)
                                
                                # Ищем модальное окно и доску (код будет выполнен ниже в основном блоке)
                                # Но так как мы уже кликнули, нужно найти модальное окно здесь
                                modal_visible = False
                                for attempt in range(5):
                                    try:
                                        modals = self.driver.find_elements(By.CSS_SELECTOR,
                                            'div[role="dialog"], div[class*="modal"], div[class*="overlay"]')
                                        search_inputs = self.driver.find_elements(By.CSS_SELECTOR,
                                            'input[placeholder*="Поиск" i], input[placeholder*="Search" i]')
                                        if modals or search_inputs:
                                            visible_modals = [m for m in modals if m.is_displayed()]
                                            visible_search = [s for s in search_inputs if s.is_displayed()]
                                            if visible_modals or visible_search:
                                                modal_visible = True
                                                print("  ✓ Модальное окно открыто")
                                                break
                                    except Exception:
                                        pass
                                    if attempt < 4:
                                        time.sleep(0.5)
                                
                                if modal_visible:
                                    # Ищем доску в модальном окне
                                    print("  Поиск доски в модальном окне...")
                                    
                                    # Отладка: выводим все элементы в модальном окне
                                    try:
                                        all_modal_elements = self.driver.find_elements(By.XPATH,
                                            "//div[@role='dialog']//*[not(self::input) and not(self::textarea) and text()]")
                                        print(f"  Найдено {len(all_modal_elements)} элементов с текстом в модальном окне")
                                        for i, elem in enumerate(all_modal_elements[:10], 1):  # Первые 10
                                            try:
                                                text = elem.text.strip()[:50]
                                                if text:
                                                    print(f"    {i}. '{text}'")
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    
                                    board_options = []
                                    
                                    # Способ 1: Точное совпадение
                                    try:
                                        board_options = self.driver.find_elements(By.XPATH,
                                            f"//div[@role='dialog']//*[normalize-space(text())='{board_name}' and not(self::input)]")
                                        board_options = [opt for opt in board_options if opt.is_displayed()]
                                        if board_options:
                                            print(f"  Найдено {len(board_options)} элементов с точным текстом")
                                    except Exception:
                                        pass
                                    
                                    # Способ 2: Вхождение
                                    if not board_options:
                                        try:
                                            board_options = self.driver.find_elements(By.XPATH,
                                                f"//div[@role='dialog']//*[contains(text(), '{board_name}') and not(self::input) and not(self::textarea)]")
                                            board_options = [opt for opt in board_options 
                                                           if opt.is_displayed() and len(opt.text.strip()) < 100]
                                            if board_options:
                                                print(f"  Найдено {len(board_options)} элементов с вхождением текста")
                                        except Exception:
                                            pass
                                    
                                    # Кликаем на найденную доску
                                    if board_options:
                                        print(f"  Проверка {len(board_options)} найденных элементов...")
                                        for i, option in enumerate(board_options, 1):
                                            try:
                                                option_text = option.text.strip()
                                                if i <= 5:  # Показываем больше для отладки
                                                    print(f"    Элемент {i}: '{option_text[:50]}'")
                                                
                                                # Проверяем совпадение (точное или частичное)
                                                text_lower = option_text.lower()
                                                board_lower = board_name.lower()
                                                
                                                # Убираем подчеркивания для сравнения
                                                text_clean = text_lower.replace('_', '').replace('-', '').strip()
                                                board_clean = board_lower.replace('_', '').replace('-', '').strip()
                                                
                                                if (board_lower == text_lower or 
                                                    board_lower in text_lower or 
                                                    text_lower in board_lower or
                                                    board_clean == text_clean or
                                                    board_clean in text_clean):
                                                    print(f"  ✓ Найдена подходящая доска: '{option_text}'")
                                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                                    time.sleep(0.5)
                                                    
                                                    # Пробуем кликнуть
                                                    clicked = False
                                                    try:
                                                        option.click()
                                                        clicked = True
                                                    except Exception:
                                                        try:
                                                            self.driver.execute_script("arguments[0].click();", option)
                                                            clicked = True
                                                        except Exception:
                                                            # Пробуем кликнуть на родителя
                                                            try:
                                                                parent = self.driver.execute_script("return arguments[0].parentElement;", option)
                                                                if parent:
                                                                    self.driver.execute_script("arguments[0].click();", parent)
                                                                    clicked = True
                                                            except Exception:
                                                                pass
                                                    
                                                    if clicked:
                                                        board_selected = True
                                                        print(f"✓ Доска выбрана: {board_name}")
                                                        time.sleep(2)
                                                        break
                                            except Exception as e_opt:
                                                if i <= 3:
                                                    print(f"  ⚠ Ошибка при обработке элемента {i}: {e_opt}")
                                                continue
                                    else:
                                        print("  ⚠ Доска не найдена в модальном окне")
                                        # Пробуем найти все доски в модальном окне и выбрать первую доступную
                                        try:
                                            all_boards = self.driver.find_elements(By.XPATH,
                                                "//div[@role='dialog']//*[text() and not(self::input) and not(self::textarea)]")
                                            print(f"  Всего элементов в модальном окне: {len(all_boards)}")
                                            
                                            # Ищем кликабельные элементы, которые могут быть досками
                                            for i, elem in enumerate(all_boards, 1):
                                                try:
                                                    text = elem.text.strip()
                                                    if text and len(text) < 50 and len(text) > 0:
                                                        print(f"    Элемент {i}: '{text}'")
                                                        
                                                        # Пропускаем служебные элементы
                                                        text_lower = text.lower()
                                                        if ('поиск' not in text_lower and 'search' not in text_lower and 
                                                            'создать' not in text_lower and 'create' not in text_lower and
                                                            'все доски' not in text_lower and 'all boards' not in text_lower and
                                                            'найдена доска' not in text_lower):
                                                            # Пробуем кликнуть на этот элемент
                                                            try:
                                                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                                                time.sleep(0.5)
                                                                self.driver.execute_script("arguments[0].click();", elem)
                                                                board_selected = True
                                                                print(f"✓ Доска выбрана (первая доступная): '{text}'")
                                                                time.sleep(2)
                                                                break
                                                            except Exception:
                                                                continue
                                                except Exception:
                                                    continue
                                        except Exception:
                                            pass
                            else:
                                print("⚠ Не удалось кликнуть на поле выбора доски")
                        else:
                            print("  ⚠ Поле выбора доски не найдено ни одним способом")
                            board_field = None
                    except Exception as e_alt:
                        print(f"  ⚠ Ошибка при альтернативном поиске: {e_alt}")
                
                if not board_selected:
                    print("⚠ ВНИМАНИЕ: Доска не выбрана! Публикация может не пройти.")
                    
            except Exception as e:
                print(f"⚠ Ошибка при выборе доски: {e}")
                import traceback
                traceback.print_exc()
            
            # Финальная проверка всех полей перед публикацией
            print("\nФинальная проверка всех полей перед публикацией...")
            try:
                # Проверяем название
                try:
                    title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                    final_title = title_field.get_attribute('value') or ''
                    if not final_title or final_title.strip() != title.strip():
                        print(f"  ⚠ Название пустое или неверное: '{final_title}', заполняем заново...")
                        self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                        time.sleep(0.5)
                    else:
                        print(f"  ✓ Название заполнено: '{final_title}'")
                except Exception:
                    print("  ⚠ Не удалось проверить название")
                
                # Проверяем описание
                try:
                    all_contenteditable = self.driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                    if all_contenteditable:
                        desc_field = all_contenteditable[0]
                        final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        if not final_desc or final_desc.strip() != description.strip():
                            print(f"  ⚠ Описание пустое или неверное: '{final_desc[:50]}', заполняем заново...")
                            desc_field.click()
                            time.sleep(0.5)
                            self.driver.execute_script("arguments[0].innerText = arguments[1];", desc_field, description)
                            self.driver.execute_script("arguments[0].textContent = arguments[1];", desc_field, description)
                            self.driver.execute_script("""
                                var event = new Event('input', { bubbles: true });
                                arguments[0].dispatchEvent(event);
                            """, desc_field)
                            time.sleep(0.5)
                        else:
                            print(f"  ✓ Описание заполнено: '{final_desc[:50]}'")
                    else:
                        print("  ⚠ Поле описания не найдено")
                except Exception as e:
                    print(f"  ⚠ Не удалось проверить описание: {e}")
                
                # Проверяем ссылку
                try:
                    # Ждем, пока элемент станет доступным
                    link_field = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, PCS.LINK_FIELD_ID))
                    )
                    
                    final_link = link_field.get_attribute('value') or ''
                    if not final_link or final_link.strip() != link.strip():
                        print(f"  ⚠ Ссылка пустая или неверная: '{final_link}', заполняем заново...")
                        
                        # Прокручиваем к полю
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_field)
                        time.sleep(0.5)
                        
                        # Очищаем через JS (безопаснее)
                        self.driver.execute_script("arguments[0].value = '';", link_field)
                        time.sleep(0.2)
                        
                        # Пробуем кликнуть и очистить через Selenium (только если элемент готов)
                        try:
                            if link_field.is_enabled() and link_field.is_displayed():
                                WebDriverWait(self.driver, 5).until(
                                    EC.element_to_be_clickable(link_field)
                                )
                                link_field.click()
                                time.sleep(0.3)
                                # Пробуем clear только если элемент готов
                                try:
                                    if link_field.is_enabled():
                                        link_field.clear()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        
                        time.sleep(0.3)
                        
                        # Заполняем через JS
                        self.driver.execute_script("arguments[0].value = arguments[1];", link_field, link)
                        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", link_field)
                        time.sleep(0.5)
                    else:
                        print(f"  ✓ Ссылка заполнена: '{final_link}'")
                except Exception as e:
                    print(f"  ⚠ Не удалось проверить ссылку: {e}")
                
                print("  Ожидание 2 секунды для сохранения всех полей...")
                time.sleep(2)
            except Exception as e:
                print(f"  ⚠ Ошибка при финальной проверке: {e}")
            
            # Финальная проверка и заполнение полей непосредственно перед публикацией
            print("\nФинальная проверка полей непосредственно перед публикацией...")
            time.sleep(2)
            
            # Проверяем и заполняем название
            try:
                title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                final_title = title_field.get_attribute('value') or ''
                if not final_title or final_title.strip() != title.strip():
                    print(f"  ⚠ Название пустое или неверное: '{final_title}', заполняем...")
                    try:
                        title_field.click()
                        time.sleep(0.3)
                        # Пробуем clear только если элемент готов
                        if title_field.is_enabled() and title_field.is_displayed():
                            try:
                                title_field.clear()
                            except Exception:
                                # Если clear не работает, используем только send_keys
                                pass
                        time.sleep(0.3)
                        title_field.send_keys(title)
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"  ⚠ Ошибка при заполнении названия: {e}")
                        # Fallback на JS
                        self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                    # Также через JS
                    self.driver.execute_script("arguments[0].value = arguments[1];", title_field, title)
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", title_field)
                    time.sleep(0.5)
                    final_title = title_field.get_attribute('value') or ''
                    print(f"  ✓ Название заполнено: '{final_title}'")
                else:
                    print(f"  ✓ Название уже заполнено: '{final_title}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки названия: {e}")
            
            # Проверяем и заполняем описание
            try:
                all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                if all_ce:
                    desc_field = all_ce[0]
                    final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                    if not final_desc or final_desc.strip() != description.strip():
                        print(f"  ⚠ Описание пустое или неверное: '{final_desc[:50]}', заполняем...")
                        desc_field.click()
                        time.sleep(0.5)
                        # Очищаем
                        self.driver.execute_script("arguments[0].innerText = '';", desc_field)
                        self.driver.execute_script("arguments[0].textContent = '';", desc_field)
                        time.sleep(0.3)
                        # Заполняем через более агрессивный метод
                        # Сначала фокусируемся на поле
                        self.driver.execute_script("arguments[0].focus();", desc_field)
                        time.sleep(0.3)
                        
                        # Очищаем содержимое полностью
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            elem.innerHTML = '';
                            elem.innerText = '';
                            elem.textContent = '';
                            // Удаляем все дочерние элементы
                            while (elem.firstChild) {
                                elem.removeChild(elem.firstChild);
                            }
                        """, desc_field)
                        time.sleep(0.3)
                        
                        # Заполняем через send_keys (симулируем реальный ввод)
                        desc_field.send_keys(description)
                        time.sleep(0.5)
                        
                        # Также устанавливаем через innerText и textContent
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            var text = arguments[1];
                            elem.innerText = text;
                            elem.textContent = text;
                            // Устанавливаем также через innerHTML для надежности
                            elem.innerHTML = text;
                        """, desc_field, description)
                        time.sleep(0.5)
                        
                        # Триггерим все возможные события в правильном порядке
                        self.driver.execute_script("""
                            var elem = arguments[0];
                            // Сначала keydown
                            var keydownEvent = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'a' });
                            elem.dispatchEvent(keydownEvent);
                            // Потом input
                            var inputEvent = new InputEvent('input', { bubbles: true, cancelable: true, data: arguments[1] });
                            elem.dispatchEvent(inputEvent);
                            // Потом keyup
                            var keyupEvent = new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: 'a' });
                            elem.dispatchEvent(keyupEvent);
                            // Потом change
                            var changeEvent = new Event('change', { bubbles: true, cancelable: true });
                            elem.dispatchEvent(changeEvent);
                            // Потом blur (потеря фокуса)
                            var blurEvent = new FocusEvent('blur', { bubbles: true, cancelable: true });
                            elem.dispatchEvent(blurEvent);
                            // И снова focus
                            elem.focus();
                        """, desc_field, description)
                        time.sleep(1)
                        final_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        print(f"  ✓ Описание заполнено: '{final_desc[:50]}'")
                    else:
                        print(f"  ✓ Описание уже заполнено: '{final_desc[:50]}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки описания: {e}")
            
            # Проверяем и заполняем ссылку
            try:
                link_field = self.driver.find_element(By.ID, PCS.LINK_FIELD_ID)
                final_link = link_field.get_attribute('value') or ''
                if not final_link or final_link.strip() != link.strip():
                    print(f"  ⚠ Ссылка пустая или неверная: '{final_link}', заполняем...")
                    link_field.click()
                    time.sleep(0.3)
                    
                    # Очищаем поле через выделение и удаление (как пользователь)
                    link_field.send_keys(Keys.COMMAND + 'a')  # Выделяем все (Mac)
                    time.sleep(0.2)
                    link_field.send_keys(Keys.DELETE)  # Удаляем
                    time.sleep(0.3)
                    
                    # Заполняем ТОЛЬКО через send_keys (симулируем реальный ввод)
                    link_field.send_keys(link)
                    time.sleep(1.5)  # Даем время на обработку
                    final_link = link_field.get_attribute('value') or ''
                    print(f"  ✓ Ссылка заполнена: '{final_link}'")
                else:
                    print(f"  ✓ Ссылка уже заполнена: '{final_link}'")
            except Exception as e:
                print(f"  ⚠ Ошибка проверки ссылки: {e}")
            
            print("  Ожидание 3 секунды для финального сохранения...")
            time.sleep(3)
            
            # ЕЩЕ РАЗ проверяем и заполняем поля непосредственно перед публикацией
            print("\nПоследняя проверка и заполнение полей перед публикацией...")
            try:
                # Название
                try:
                    title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                    current_title = title_field.get_attribute('value') or ''
                    if not current_title or current_title.strip() != title.strip():
                        print("  ⚠ Название пустое перед публикацией, заполняем...")
                        title_field.click()
                        time.sleep(0.3)
                        title_field.send_keys(Keys.COMMAND + 'a')
                        time.sleep(0.2)
                        title_field.send_keys(Keys.DELETE)
                        time.sleep(0.3)
                        title_field.send_keys(title)
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].blur();", title_field)
                        time.sleep(0.5)
                except Exception:
                    pass
                
                # Описание
                try:
                    all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                    if all_ce:
                        desc_field = all_ce[0]
                        current_desc = desc_field.text or desc_field.get_attribute('innerText') or desc_field.get_attribute('textContent') or ''
                        if not current_desc or current_desc.strip() != description.strip():
                            print("  ⚠ Описание пустое перед публикацией, заполняем...")
                            desc_field.click()
                            time.sleep(0.3)
                            desc_field.send_keys(Keys.COMMAND + 'a')
                            time.sleep(0.2)
                            desc_field.send_keys(Keys.DELETE)
                            time.sleep(0.3)
                            desc_field.send_keys(description)
                            time.sleep(1.5)
                            self.driver.execute_script("arguments[0].blur();", desc_field)
                            time.sleep(0.5)
                except Exception:
                    pass
                
                # Ссылка
                try:
                    link_field = self.driver.find_element(By.ID, PCS.LINK_FIELD_ID)
                    current_link = link_field.get_attribute('value') or ''
                    if not current_link or current_link.strip() != link.strip():
                        print("  ⚠ Ссылка пустая перед публикацией, заполняем...")
                        link_field.click()
                        time.sleep(0.3)
                        link_field.send_keys(Keys.COMMAND + 'a')
                        time.sleep(0.2)
                        link_field.send_keys(Keys.DELETE)
                        time.sleep(0.3)
                        link_field.send_keys(link)
                        time.sleep(1.5)
                        self.driver.execute_script("arguments[0].blur();", link_field)
                        time.sleep(0.5)
                except Exception:
                    pass
                
                # Финальная задержка для сохранения всех изменений
                print("  Ожидание 2 секунды для финального сохранения всех полей...")
                time.sleep(2)
            except Exception as e:
                print(f"  ⚠ Ошибка при финальной проверке: {e}")
            
            # Шаг 6: Публикуем пин
            print("\n6. Публикация пина...")
            try:
                # ВАЖНО: Снимаем фокус со всех полей ввода перед публикацией
                print("  Снятие фокуса с полей ввода...")
                try:
                    # Снимаем фокус с поля ссылки (последнее заполненное поле)
                    link_field = self.driver.find_element(By.ID, PCS.LINK_FIELD_ID)
                    self.driver.execute_script("arguments[0].blur();", link_field)
                    time.sleep(0.3)
                except Exception:
                    pass
                try:
                    # Снимаем фокус с поля описания
                    all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                    if all_ce:
                        self.driver.execute_script("arguments[0].blur();", all_ce[0])
                        time.sleep(0.3)
                except Exception:
                    pass
                try:
                    # Снимаем фокус с поля названия
                    title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                    self.driver.execute_script("arguments[0].blur();", title_field)
                    time.sleep(0.3)
                except Exception:
                    pass
                # Кликаем вне всех полей для полного снятия фокуса
                self.driver.execute_script("document.body.click();")
                time.sleep(0.5)
                
                # Pinterest размещает кнопку публикации ВНИЗУ формы — прокручиваем вверх и вниз
                print("  Прокрутка для поиска кнопки публикации...")
                for scroll_pos in ['0', 'document.body.scrollHeight']:  # Сначала вверх, потом вниз
                    self.driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(0.5)
                # Прокручиваем scrollable контейнеры — вверх И вниз
                try:
                    self.driver.execute_script("""
                        document.querySelectorAll('div, section, main').forEach(function(el) {
                            var s = getComputedStyle(el);
                            if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflow === 'auto')
                                && el.scrollHeight > el.clientHeight) {
                                el.scrollTop = 0;
                            }
                        });
                    """)
                    time.sleep(0.3)
                    self.driver.execute_script("""
                        document.querySelectorAll('div, section, main').forEach(function(el) {
                            var s = getComputedStyle(el);
                            if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflow === 'auto')
                                && el.scrollHeight > el.clientHeight) {
                                el.scrollTop = el.scrollHeight;
                            }
                        });
                    """)
                    time.sleep(0.3)
                except Exception:
                    pass
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Ищем кнопку публикации (селекторы: PCS.PUBLISH_BUTTON_*)
                publish_button = None
                publish_texts = PCS.PUBLISH_BUTTON_TEXTS
                publish_xpath = " or ".join([f"contains(., '{t}')" for t in publish_texts])
                # Способ 1: Кнопка внутри контейнера формы (PCS.FORM_TITLE_ID) — не в sidebar
                try:
                    self.driver.find_element(By.ID, PCS.FORM_TITLE_ID)
                    form_buttons = self.driver.find_elements(
                        By.XPATH,
                        f"//*[.//input[@id='{PCS.FORM_TITLE_ID}']]//button[{publish_xpath}] | "
                        f"//*[.//input[@id='{PCS.FORM_TITLE_ID}']]//*[@role='button'][{publish_xpath}]",
                    )
                    for btn in form_buttons:
                        if btn.is_displayed():
                            publish_button = btn
                            print("  ✓ Кнопка найдена в форме создания пина")
                            break
                except Exception:
                    pass
                # Способ 2: Поиск по тексту, исключая sidebar (data-test-id=create-tab, collapse-drafts-sidebar и т.д.)
                if not publish_button:
                    try:
                        for btn in self.driver.find_elements(By.XPATH, f"//button[{publish_xpath}]"):
                            if not btn.is_displayed():
                                continue
                            tid = (btn.get_attribute("data-test-id") or "").lower()
                            if any(ex in tid for ex in PCS.PUBLISH_SIDEBAR_EXCLUDE):
                                continue
                            publish_button = btn
                            print(f"  ✓ Кнопка найдена по тексту: '{btn.text.strip()}'")
                            break
                    except Exception:
                        pass
                
                # Способ 2: Поиск по селекторам (включая div/span с role=button)
                if not publish_button:
                    for selector in PCS.PUBLISH_BUTTON_CSS:
                        try:
                            elems = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for elem in elems:
                                try:
                                    btn_text = (elem.text or '').strip().lower()
                                    if not btn_text or 'опубликовать' in btn_text or 'publish' in btn_text or 'create' in btn_text or 'сохранить' in btn_text:
                                        if elem.is_displayed():
                                            publish_button = elem
                                            print(f"  ✓ Кнопка найдена по селектору: {selector}")
                                            break
                                except Exception:
                                    pass
                            if publish_button:
                                break
                        except Exception:
                            continue
                
                # Способ 3: Поиск всех кнопок и элементов с role=button
                if not publish_button:
                    btn_texts_lower = [t.lower() for t in publish_texts]
                    for selector in ['button', '[role="button"]']:
                        try:
                            elems = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for btn in elems:
                                try:
                                    txt = (btn.text or '').strip().lower()
                                    if txt and any(b in txt or txt == b for b in btn_texts_lower):
                                        publish_button = btn
                                        print(f"  ✓ Кнопка найдена: '{btn.text.strip()}'")
                                        break
                                except Exception:
                                    continue
                            if publish_button:
                                break
                        except Exception:
                            pass
                
                # Способ 4: Поиск среди div/span с cursor:pointer (Pinterest использует кастомные кнопки)
                if not publish_button:
                    for xpath in [
                        "//*[contains(@class, 'Button') and (contains(., 'Publish') or contains(., 'Опубликовать') or contains(., 'Create') or contains(., 'Создать'))]",
                        "//div[contains(., 'Publish') or contains(., 'Опубликовать')][.//span]",
                    ]:
                        try:
                            elems = self.driver.find_elements(By.XPATH, xpath)
                            for e in elems:
                                try:
                                    if e.is_displayed() and (e.get_attribute('disabled') != 'true' and e.get_attribute('aria-disabled') != 'true'):
                                        txt = (e.text or '').strip()
                                        if len(txt) < 50 and ('publish' in txt.lower() or 'опубликовать' in txt.lower() or 'create' in txt.lower() or 'создать' in txt.lower()):
                                            publish_button = e
                                            print(f"  ✓ Кнопка найдена (custom): '{txt[:30]}'")
                                            break
                                except Exception:
                                    pass
                            if publish_button:
                                break
                        except Exception:
                            pass
                
                # Способ 5: Прокрутка и повторный поиск (кнопка может быть вне viewport)
                if not publish_button:
                    print("  Кнопка не найдена, прокручиваем и повторяем поиск...")
                    for scroll_y in [0, "document.body.scrollHeight"]:
                        self.driver.execute_script(f"window.scrollTo(0, {scroll_y});")
                        time.sleep(1)
                        for xpath in [
                            "//button[contains(., 'Опубликовать') or contains(., 'Publish') or contains(., 'Create')]",
                            "//*[@role='button'][contains(., 'Опубликовать') or contains(., 'Publish') or contains(., 'Create')]",
                            "//*[contains(@aria-label, 'публиковать') or contains(@aria-label, 'publish') or contains(@aria-label, 'create')]",
                        ]:
                            try:
                                elems = self.driver.find_elements(By.XPATH, xpath)
                                for e in elems:
                                    try:
                                        if (e.get_attribute('disabled') != 'true' 
                                                and e.get_attribute('aria-disabled') != 'true'):
                                            publish_button = e
                                            print("  ✓ Кнопка найдена через повторный поиск")
                                            break
                                    except Exception:
                                        pass
                                if publish_button:
                                    break
                            except Exception:
                                pass
                        if publish_button:
                            break
                
                # Способ 6: JavaScript — поиск любой кнопки с текстом Publish/Create/Опубликовать вне sidebar
                if not publish_button:
                    try:
                        found = self.driver.execute_script("""
                            var keywordsPrio = ['publish', 'опубликовать'];
                            var keywords = ['publish', 'опубликовать', 'create pin', 'создать пин', 'create', 'создать', 'done', 'готово', 'save', 'сохранить'];
                            var candidates = [];
                            document.querySelectorAll('button, [role="button"], div[class*="Button"], span[class*="Button"]').forEach(function(el) {
                                if (!el.offsetParent) return;
                                var txt = (el.textContent || '').trim().toLowerCase();
                                if (txt.length < 3 || txt.length > 40) return;
                                var match = keywords.some(function(k) { return txt.indexOf(k) >= 0; });
                                if (!match) return;
                                var inSidebar = !!el.closest('[data-test-id*="sidebar"], [data-test-id*="create-tab"], .sidebar');
                                if (inSidebar) return;
                                var inForm = !!el.closest('form') || !!el.closest('[id*="storyboard"]');
                                var prio = keywordsPrio.some(function(k) { return txt.indexOf(k) >= 0; }) ? 2 : 1;
                                candidates.push({el: el, text: txt, inForm: inForm, prio: prio});
                            });
                            candidates.sort(function(a,b) { return (b.prio - a.prio) || ((b.inForm ? 1 : 0) - (a.inForm ? 1 : 0)); });
                            if (candidates.length > 0) {
                                candidates[0].el.scrollIntoView({block: 'center'});
                                candidates[0].el.click();
                                return candidates[0].text;
                            }
                            return null;
                        """)
                        if found:
                            publish_button = "js_clicked"
                            print(f"  ✓ Кнопка найдена и нажата через JS: '{found}'")
                    except Exception:
                        pass
                
                if publish_button:
                    js_already_clicked = (publish_button == "js_clicked")
                    if not js_already_clicked:
                        # Прокручиваем к кнопке (она может быть внизу формы)
                        print("  Прокрутка к кнопке публикации...")
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", publish_button)
                    time.sleep(1.5)
                    # Также пробуем прокрутить через window.scrollTo с координатами кнопки
                    if not js_already_clicked:
                        try:
                            location = publish_button.location_once_scrolled_into_view
                            self.driver.execute_script(f"window.scrollTo(0, {location['y'] - 200});")
                            time.sleep(1)
                        except Exception:
                            pass
                    
                    # Проверяем, что кнопка видима и кликабельна (пропускаем если уже нажали через JS)
                    if not js_already_clicked and not publish_button.is_displayed():
                        print("⚠ Кнопка публикации не видна, пробуем разные способы прокрутки...")
                        # Прокручиваем вверх
                        self.driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(1)
                        self.driver.execute_script("document.body.scrollTop = 0; document.documentElement.scrollTop = 0;")
                        time.sleep(1)
                        # Прокручиваем к кнопке снова
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'start', behavior: 'auto'});", publish_button)
                        time.sleep(1.5)
                    
                    # Проверяем, что кнопка не disabled (пропускаем если уже нажали через JS)
                    if not js_already_clicked:
                        is_disabled = publish_button.get_attribute('disabled') or publish_button.get_attribute('aria-disabled') == 'true'
                        if is_disabled:
                            print("⚠ Кнопка публикации отключена, проверяем поля...")
                        # Проверяем поля еще раз
                        try:
                            title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                            title_val = title_field.get_attribute('value') or ''
                            print(f"  Название: '{title_val}'")
                        except Exception:
                            pass
                        try:
                            link_field = self.driver.find_element(By.ID, PCS.LINK_FIELD_ID)
                            link_val = link_field.get_attribute('value') or ''
                            print(f"  Ссылка: '{link_val}'")
                        except Exception:
                            pass
                        try:
                            all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                            if all_ce:
                                desc_val = all_ce[0].text or all_ce[0].get_attribute('innerText') or ''
                                print(f"  Описание: '{desc_val[:50]}'")
                        except Exception:
                            pass
                            print("  Пробуем нажать кнопку несмотря на disabled...")
                    
                    # Если кнопка уже нажата через JS — пропускаем блок клика
                    clicked = js_already_clicked
                    click_methods = ["JS (способ 6)"] if js_already_clicked else []
                    
                    # Сохраняем текущий URL перед кликом (или после — если уже нажали)
                    url_before = self.driver.current_url
                    print(f"URL перед кликом: {url_before}")
                    
                    # Проверяем, что кнопка видима и кликабельна перед попыткой клика (пропускаем при js_already_clicked)
                    if not js_already_clicked:
                        print("  Проверка состояния кнопки перед кликом...")
                        try:
                            is_visible = publish_button.is_displayed()
                            is_enabled = publish_button.is_enabled()
                            btn_text = publish_button.text.strip()
                            print(f"    Видима: {is_visible}, Включена: {is_enabled}, Текст: '{btn_text}'")
                        except Exception as check_e:
                            print(f"    Ошибка проверки: {check_e}")
                    
                    # Пробуем кликнуть через разные методы (если ещё не нажали через JS)
                    if not clicked:
                        # Метод 1: ActionChains с move_to_element (самый надежный)
                        try:
                            print("  Попытка клика методом 1: ActionChains move_to_element + click...")
                            from selenium.webdriver.common.action_chains import ActionChains
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'nearest', behavior: 'auto'});", publish_button)
                            time.sleep(0.3)
                            actions = ActionChains(self.driver)
                            actions.move_to_element(publish_button).pause(0.2).click().perform()
                            clicked = True
                            click_methods.append("ActionChains")
                            print("  ✓ Кнопка публикации нажата (ActionChains)")
                        except Exception as e:
                            print(f"  ⚠ ActionChains не сработал: {e}")
                    
                    # Метод 2: JavaScript click
                    if not clicked:
                        try:
                            print("  Попытка клика методом 2: JavaScript click()...")
                            self.driver.execute_script("arguments[0].click();", publish_button)
                            clicked = True
                            click_methods.append("JS клик")
                            print("  ✓ Кнопка публикации нажата (JS клик)")
                        except Exception as e2:
                            print(f"  ⚠ JS клик не сработал: {e2}")
                    
                    # Метод 3: ActionChains
                    if not clicked:
                        try:
                            print("  Попытка клика методом 3: ActionChains...")
                            from selenium.webdriver.common.action_chains import ActionChains
                            actions = ActionChains(self.driver)
                            actions.move_to_element(publish_button).pause(0.5).click().perform()
                            clicked = True
                            click_methods.append("ActionChains")
                            print("  ✓ Кнопка публикации нажата (ActionChains)")
                        except Exception as e3:
                            print(f"  ⚠ ActionChains не сработал: {e3}")
                    
                    # Метод 4: JavaScript с dispatchEvent
                    if not clicked:
                        try:
                            print("  Попытка клика методом 4: JavaScript dispatchEvent...")
                            self.driver.execute_script("""
                                var btn = arguments[0];
                                var event = new MouseEvent('click', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true
                                });
                                btn.dispatchEvent(event);
                            """, publish_button)
                            clicked = True
                            click_methods.append("JS dispatchEvent")
                            print("  ✓ Кнопка публикации нажата (JS dispatchEvent)")
                        except Exception as e4:
                            print(f"  ⚠ JS dispatchEvent не сработал: {e4}")
                    
                    # Метод 5: JavaScript с mousedown/mouseup
                    if not clicked:
                        try:
                            print("  Попытка клика методом 5: JavaScript mousedown/mouseup...")
                            self.driver.execute_script("""
                                var btn = arguments[0];
                                var mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
                                var mouseup = new MouseEvent('mouseup', { bubbles: true, cancelable: true });
                                var click = new MouseEvent('click', { bubbles: true, cancelable: true });
                                btn.dispatchEvent(mousedown);
                                btn.dispatchEvent(mouseup);
                                btn.dispatchEvent(click);
                            """, publish_button)
                            clicked = True
                            click_methods.append("JS mousedown/mouseup")
                            print("  ✓ Кнопка публикации нажата (JS mousedown/mouseup)")
                        except Exception as e5:
                            print(f"  ⚠ JS mousedown/mouseup не сработал: {e5}")
                    
                    if not clicked:
                        print("  ⚠ ВСЕ методы клика не сработали!")
                        print("  Пробуем найти кнопку заново и кликнуть...")
                        # Пробуем найти кнопку заново
                        try:
                            publish_button_retry = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                            if publish_button_retry:
                                self.driver.execute_script("arguments[0].click();", publish_button_retry)
                                clicked = True
                                print("  ✓ Кнопка найдена заново и нажата")
                        except Exception:
                            pass
                    
                    if not clicked:
                        self.last_error = "Не удалось нажать кнопку публикации"
                        print("  ⚠ " + self.last_error)
                        return False
                    
                    print(f"✓ Кнопка публикации нажата (методы: {', '.join(click_methods)})")
                    
                    # Ждем подтверждения публикации (Pinterest обрабатывает асинхронно)
                    print("Ожидание подтверждения публикации...")
                    time.sleep(2)
                    
                    # Сразу после клика проверяем, не появилась ли ошибка
                    print("  Проверка на наличие ошибок после клика...")
                    error_found = False
                    try:
                        # Проверяем наличие модальных окон с ошибками
                        modal_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="dialog"] [class*="error"], [role="dialog"] [role="alert"], [role="dialog"] [class*="Error"]')
                        if modal_errors:
                            for err in modal_errors:
                                error_text = err.text.strip()
                                if error_text:
                                    print(f"  ⚠ Обнаружена ошибка в модальном окне: {error_text}")
                                    error_found = True
                        
                        # Проверяем наличие toast-уведомлений с ошибками (но исключаем информационные сообщения)
                        toast_errors = self.driver.find_elements(By.CSS_SELECTOR, '[class*="toast"] [class*="error"], [class*="notification"] [class*="error"], [role="alert"]')
                        if toast_errors:
                            for err in toast_errors:
                                error_text = err.text.strip()
                                if error_text and len(error_text) > 0:
                                    # Исключаем информационные сообщения и сообщения об успехе (не ошибки)
                                    info_keywords = ['проверяем', 'проверяет', 'checking', 'проверка', 'одну минуту', 'one moment', 
                                                    'опубликовано', 'published', 'успешно', 'success', 'сохранено', 'saved']
                                    is_info = any(keyword in error_text.lower() for keyword in info_keywords)
                                    if not is_info:
                                        # Проверяем, что это действительно ошибка (содержит слова об ошибке)
                                        error_keywords = ['ошибка', 'error', 'не удалось', 'failed', 'неверно', 'invalid', 'неправильно', 
                                                         'недоступно', 'unavailable', 'отклонено', 'rejected']
                                        is_error = any(keyword in error_text.lower() for keyword in error_keywords)
                                        if is_error:
                                            print(f"  ⚠ Обнаружена ошибка в уведомлении: {error_text}")
                                            error_found = True
                                        else:
                                            print(f"  ℹ Информационное сообщение: {error_text}")
                                    else:
                                        # Это информационное сообщение или сообщение об успехе
                                        if 'опубликовано' in error_text.lower() or 'published' in error_text.lower():
                                            print(f"  ✓ Сообщение об успешной публикации: {error_text}")
                                        else:
                                            print(f"  ℹ Информационное сообщение: {error_text}")
                        
                        # Проверяем наличие ошибок валидации в полях
                        field_errors = self.driver.find_elements(By.CSS_SELECTOR, '[class*="error-message"], [class*="validation-error"], [data-test-id*="error"]')
                        if field_errors:
                            for err in field_errors:
                                error_text = err.text.strip()
                                if error_text and len(error_text) > 0:
                                    print(f"  ⚠ Обнаружена ошибка валидации: {error_text}")
                                    error_found = True
                    except Exception as check_err:
                        print(f"  ⚠ Ошибка при проверке ошибок: {check_err}")
                    
                    if error_found:
                        self.last_error = "Обнаружены ошибки на странице Pinterest, публикация заблокирована"
                        print("  ⚠ " + self.last_error)
                        return False
                    
                    time.sleep(1.5)
                    
                    # Проверяем, что мы перешли на страницу пина (URL изменился)
                    current_url = self.driver.current_url
                    print(f"URL после клика (через 2 сек): {current_url}")
                    
                    if '/pin/' in current_url and current_url != url_before:
                        print("✓ Пин успешно опубликован!")
                        print(f"Текущий URL: {current_url}")
                        return True
                    else:
                        # Возможно, появилось модальное окно с подтверждением или идет обработка
                        print("⚠ URL не изменился сразу, ждем обработки...")
                        for i in range(45):  # Ждем до 45 секунд (Pinterest может медленно обрабатывать)
                            time.sleep(1)
                            current_url = self.driver.current_url
                            if i % 5 == 0:
                                print(f"  Проверка {i+1}/45: {current_url}")
                            if '/pin/' in current_url and current_url != url_before:
                                print("✓ Пин успешно опубликован!")
                                print(f"Текущий URL: {current_url}")
                                return True
                            # Проверяем toast/модалку об успехе только в видимых элементах (не по всему page_source)
                            # Слова "published", "done" и т.п. есть по всей странице — это даёт ложные срабатывания
                            try:
                                visible_success = self.driver.find_elements(
                                    By.CSS_SELECTOR,
                                    '[role="alert"], [role="status"], [class*="toast"], [class*="Toast"], '
                                    '[data-test-id*="success"], [data-test-id*="toast"]'
                                )
                                for el in visible_success:
                                    if not el.is_displayed():
                                        continue
                                    txt = (el.text or "").lower()
                                    if any(p in txt for p in ['pin created', 'pin опубликован', 'опубликовано', 'published', 'successfully']):
                                        print("✓ Обнаружено toast об успешной публикации")
                                        time.sleep(2)
                                        view_btns = self.driver.find_elements(By.XPATH,
                                            "//button[contains(., 'View') or contains(., 'Посмотреть') or contains(., 'Done') or contains(., 'Готово')]")
                                        for vb in view_btns:
                                            if vb.is_displayed():
                                                vb.click()
                                                time.sleep(2)
                                                break
                                        if '/pin/' in self.driver.current_url:
                                            return True
                                        break
                            except Exception:
                                pass
                            # Проверяем наличие ошибок на странице
                            if i % 5 == 0:
                                try:
                                    # Ищем различные типы ошибок
                                    error_selectors = [
                                        '[role="alert"]',
                                        '.error',
                                        '[class*="error"]',
                                        '[class*="Error"]',
                                        '[data-test-id*="error"]',
                                        '[aria-live="polite"]',
                                        '[aria-live="assertive"]'
                                    ]
                                    for selector in error_selectors:
                                        error_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                                        if error_elements:
                                            for err in error_elements:
                                                error_text = err.text.strip()
                                                if error_text and len(error_text) > 0:
                                                    print(f"⚠ Обнаружена ошибка ({selector}): {error_text}")
                                    
                                    # Проверяем, не появилось ли модальное окно с ошибкой
                                    try:
                                        modal_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="dialog"] [class*="error"], [role="dialog"] [role="alert"]')
                                        if modal_errors:
                                            for err in modal_errors:
                                                error_text = err.text.strip()
                                                if error_text:
                                                    print(f"⚠ Обнаружена ошибка в модальном окне: {error_text}")
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                
                                # Проверяем, не заблокирована ли кнопка публикации
                                try:
                                    publish_button_after = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], button[aria-label*="publish" i], button[aria-label*="опубликовать" i]')
                                    is_disabled_after = publish_button_after.get_attribute('disabled') or publish_button_after.get_attribute('aria-disabled') == 'true'
                                    if is_disabled_after:
                                        print(f"⚠ Кнопка публикации все еще отключена на проверке {i+1}")
                                except Exception:
                                    pass
                        
                        # Если после 30 секунд URL не изменился
                        print("⚠ Пин не опубликован или публикация еще обрабатывается")
                        print(f"Финальный URL: {current_url}")
                        print("Ожидался URL с '/pin/' в пути или изменение URL")
                        
                        # Финальная проверка - может быть пин опубликован, но страница не обновилась
                        print("\nФинальная диагностика:")
                        try:
                            # Проверяем все ошибки на странице
                            all_errors = self.driver.find_elements(By.CSS_SELECTOR, '[role="alert"], .error, [class*="error"], [class*="Error"], [data-test-id*="error"]')
                            if all_errors:
                                print("  Найдены элементы с ошибками:")
                                for err in all_errors[:5]:  # Первые 5
                                    try:
                                        err_text = err.text.strip()
                                        if err_text:
                                            print(f"    - {err_text[:100]}")
                                    except Exception:
                                        pass
                            
                            # Проверяем состояние кнопки публикации
                            try:
                                publish_btn_final = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], button[aria-label*="publish" i], button[aria-label*="опубликовать" i]')
                                btn_text = publish_btn_final.text.strip()
                                is_disabled_final = publish_btn_final.get_attribute('disabled') or publish_btn_final.get_attribute('aria-disabled') == 'true'
                                print(f"  Кнопка публикации: текст='{btn_text}', disabled={is_disabled_final}")
                            except Exception:
                                print("  Кнопка публикации не найдена")
                            
                            # Проверяем поля еще раз
                            print("  Состояние полей:")
                            try:
                                title_field = self.driver.find_element(By.ID, PCS.TITLE_INPUT_ID)
                                title_val = title_field.get_attribute('value') or ''
                                print(f"    Название: '{title_val}'")
                            except Exception:
                                print("    Название: не найдено")
                            try:
                                link_field = self.driver.find_element(By.ID, PCS.LINK_FIELD_ID)
                                link_val = link_field.get_attribute('value') or ''
                                print(f"    Ссылка: '{link_val}'")
                            except Exception:
                                print("    Ссылка: не найдено")
                            try:
                                all_ce = self.driver.find_elements(By.CSS_SELECTOR, '[contenteditable="true"]')
                                if all_ce:
                                    desc_val = all_ce[0].text or all_ce[0].get_attribute('innerText') or ''
                                    print(f"    Описание: '{desc_val[:50]}'")
                                else:
                                    print("    Описание: не найдено")
                            except Exception:
                                print("    Описание: ошибка проверки")
                        except Exception as diag_e:
                            print(f"  Ошибка диагностики: {diag_e}")
                        
                        print("\nПроверьте браузер вручную - возможно пин опубликован, но страница не обновилась")
                        print("Или есть ошибка валидации, которая блокирует публикацию")
                        self.last_error = "Таймаут ожидания завершения публикации (возможно UI Pinterest изменился)"
                        return False
                else:
                    # Отладка: выводим все кнопки на странице
                    try:
                        all_btns = self.driver.find_elements(By.CSS_SELECTOR, 'button, [role="button"]')
                        texts = [f"'{b.text.strip()}'" for b in all_btns[:15] if (b.text or '').strip()]
                        if texts:
                            print(f"  [Отладка] Кнопки на странице: {', '.join(texts)}")
                    except Exception:
                        pass
                    # Последняя попытка: нажать Enter для отправки формы
                    print("  Попытка отправки через Enter...")
                    try:
                        body = self.driver.find_element(By.TAG_NAME, 'body')
                        body.send_keys(Keys.RETURN)
                        time.sleep(3)
                        # Проверяем, изменился ли URL (значит публикация прошла)
                        if '/pin/' in self.driver.current_url and 'pin-creation' not in self.driver.current_url:
                            print("  ✓ Похоже, пин опубликован (URL изменился)")
                            return True
                    except Exception as kbd_e:
                        print(f"  Enter не сработал: {kbd_e}")
                    self.last_error = "Кнопка публикации не найдена — Pinterest мог обновить интерфейс. Включите headless=False в Настройках и проверьте страницу вручную."
                    print("⚠ " + self.last_error)
                    print("Попробуйте опубликовать пин вручную в открывшемся браузере")
                    print("Все поля должны быть заполнены:")
                    print(f"  - Название: {title}")
                    print(f"  - Описание: {description}")
                    print(f"  - Ссылка: {link}")
                    print(f"  - Доска: {board_name}")
                    return False
            except InvalidSessionIdException:
                self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                print("⚠ " + self.last_error)
                return False
            except Exception as e:
                if isinstance(e, InvalidSessionIdException):
                    self.last_error = "Сессия браузера прервана (Chrome закрыт или упал). Остановите автопостинг, откройте Настройки и дождитесь готовности парсера, затем запустите снова."
                    return False
                self.last_error = str(e)
                print(f"⚠ Ошибка при публикации: {e}")
                import traceback
                traceback.print_exc()
                return False
            
        except InvalidSessionIdException:
            self.last_error = "Сессия браузера прервана. Остановите автопостинг и перезапустите приложение или переинициализируйте парсер в Настройках."
            print("⚠ " + self.last_error)
            return False
        except Exception as e:
            if isinstance(e, InvalidSessionIdException):
                self.last_error = "Сессия браузера прервана. Остановите автопостинг и перезапустите приложение или переинициализируйте парсер в Настройках."
                return False
            self.last_error = str(e)
            print(f"⚠ Ошибка при создании пина: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def close(self):
        """Закрывает браузер если он был создан этим классом"""
        if self.own_driver and self.driver:
            self.driver.quit()
            print("✓ Браузер закрыт")


if __name__ == "__main__":
    """
    Тестовый модуль для публикации пина.
    """
    import sys
    
    print("=" * 80)
    print("ТЕСТОВЫЙ МОДУЛЬ ПУБЛИКАЦИИ ПИНА")
    print("=" * 80)
    
    # Быстро берём первое изображение из результатов парсинга (PinMaster/images)
    image_path = None
    try:
        from path_utils import get_user_data_dir
        pm_images = get_user_data_dir() / "images"
        if pm_images.exists():
            for sub in sorted(pm_images.iterdir(), reverse=True):
                if sub.is_dir():
                    imgs = list(sub.glob("*.jpg")) + list(sub.glob("*.jpeg")) + list(sub.glob("*.png"))
                    if imgs:
                        image_path = str(imgs[0])
                        print(f"\n✓ Изображение из парсинга: {image_path}")
                        break
        if not image_path:
            image_dirs = [d for d in os.listdir(".") if d.startswith("pinterest_images_") and os.path.isdir(d)]
            if image_dirs:
                latest_dir = sorted(image_dirs)[-1]
                image_files = [f for f in os.listdir(latest_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))]
                if image_files:
                    image_path = os.path.join(latest_dir, image_files[0])
                    print(f"\n✓ Изображение из папки результатов: {image_path}")
    except Exception as e:
        print(f"\n⚠ Ошибка поиска изображений: {e}")
    
    # Если изображение не найдено, запрашиваем у пользователя
    if not image_path:
        print("\nВведите путь к изображению для публикации:")
        user_path = input("Путь к изображению: ").strip()
        if user_path and os.path.exists(user_path):
            image_path = user_path
        else:
            print("\n⚠ Изображение не найдено. Завершение работы.")
            sys.exit(1)
    
    # Инициализируем парсер для получения досок
    print("\nИнициализация парсера...")
    parser = PinterestSeleniumParser(
        headless=False,
        download_images=False,
        auto_login=True
    )
    
    try:
        # Получаем список досок
        print("\nПолучение списка досок...")
        account_info = parser.get_account_info()
        if account_info:
            username = account_info.get('username')
            if username:
                boards = parser.parse_user_boards(username=username)
                
                if boards:
                    print(f"\n✓ Найдено досок: {len(boards)}")
                    print("\nСписок досок:")
                    for i, board in enumerate(boards, 1):
                        print(f"  {i}. {board.get('board_name', 'Без названия')}")
                    
                    # Берем первую доску для теста
                    test_board = boards[0].get('board_name')
                    print(f"\nИспользуем доску для теста: {test_board}")
                else:
                    print("\n⚠ Доски не найдены, используем 'test'")
                    test_board = "test"
            else:
                print("\n⚠ Не удалось определить имя пользователя")
                test_board = "test"
        else:
            print("\n⚠ Не удалось получить информацию об аккаунте")
            test_board = "test"
        
        # Создаем публикатор
        print("\nИнициализация публикатора...")
        publisher = PinterestPublisher(parser=parser)
        
        # Публикуем тестовый пин
        print("\n" + "=" * 80)
        success = publisher.create_pin(
            image_path=image_path,
            title="test",
            description="test 2",
            link="https://huggingface.co/",
            board_name=test_board
        )
        
        if success:
            print("\n" + "=" * 80)
            print("✓ ТЕСТ ПУБЛИКАЦИИ ЗАВЕРШЕН УСПЕШНО")
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("⚠ ТЕСТ ПУБЛИКАЦИИ ЗАВЕРШЕН С ОШИБКАМИ")
            print("=" * 80)
        
        # Не закрываем браузер, оставляем для проверки
        print("\nБраузер остается открытым для проверки результата")
        try:
            input("Нажмите Enter для закрытия браузера...")
        except (EOFError, KeyboardInterrupt):
            print("\nЗакрытие браузера...")
        
    finally:
        parser.close()
