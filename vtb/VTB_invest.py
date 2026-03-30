#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline for downloading PDF files from VTB tariff pages.
Extracts files from ALL tabs with accordion expansion.
Files saved to: vtb_downloads/<tab_name>/*.pdf
"""

import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright, Page


# ============================================================================
# 🔧 НАСТРОЙКИ — меняйте только здесь
# ============================================================================

def main():
    """=== ОСНОВНЫЕ НАСТРОЙКИ СКРИПТА ==="""
    
    # === ССЫЛКИ ===
    BASE_URL = "https://www.vtb.ru/personal/investicii/tarify/"
    SITE_DOMAIN = "https://www.vtb.ru"
    
    # === ПУТИ ===
    DOWNLOAD_ROOT = Path("vtb_downloads")  # Относительно скрипта
    
    # === BROWSER ===
    HEADLESS = True              # False = видеть браузер (для отладки)
    VIEWPORT = (1920, 1080)
    PAGE_TIMEOUT = 60000         # Таймаут загрузки страницы (мс)
    
    # === ЗАДЕРЖКИ (секунды) ===
    DELAY_AFTER_PAGE_LOAD = 2.0      # После загрузки страницы
    DELAY_AFTER_TAB_CLICK = 1.5      # После клика по табу
    DELAY_BETWEEN_ACCORDIONS = 0.4   # Между раскрытием аккордеонов
    DELAY_BETWEEN_DOWNLOADS = 0.5    # Между скачиваниями файлов
    DELAY_BETWEEN_TABS = 1.0         # Между обработкой табов
    
    # === REQUESTS ===
    REQUESTS_TIMEOUT = 30            # Таймаут запроса на скачивание
    REQUESTS_RETRIES = 3             # Повторы при ошибке
    
    # === ТАБЫ (порядок обработки) ===
    TABS_TO_PROCESS = [
        "Базовые тарифы",
        "Профессиональные тарифы",
        "Маржинальная торговля",
        "Полезная информация"
    ]
    
    # === ФИЛЬТРЫ ФАЙЛОВ ===
    FILE_EXTENSION = "pdf"                    # Расширение файлов
    SKIP_KEYWORDS = ["архив", "archive"]      # Пропускать файлы с этими словами
    MIN_FILE_SIZE = 1024                      # Мин. размер файла (защита от битых)
    
    # === АККОРДЕОНЫ ===
    ACCORDION_SELECTOR = "div[role='button'][tabindex='0'].accordion-titlestyles__Box-accordion__sc-ncxzgq-1"
    EXPAND_ACCORDIONS = True                  # Раскрывать аккордеоны для поиска ссылок
    SCROLL_BEFORE_CLICK = True                # Скроллить элемент в видимую область перед кликом
    
    # === ДОПОЛНИТЕЛЬНО ===
    SKIP_EXISTING = True             # Не качать если файл уже есть
    SAVE_DEBUG_SCREENSHOTS = False   # Сохранять скриншоты для отладки
    
    # ================= КОНЕЦ НАСТРОЕК =================
    
    # Запуск пайплайна
    run_pipeline(
        main_url=BASE_URL,
        site_domain=SITE_DOMAIN,
        output_root=DOWNLOAD_ROOT,
        headless=HEADLESS,
        viewport=VIEWPORT,
        page_timeout=PAGE_TIMEOUT,
        delays={
            "after_load": DELAY_AFTER_PAGE_LOAD,
            "after_tab": DELAY_AFTER_TAB_CLICK,
            "accordions": DELAY_BETWEEN_ACCORDIONS,
            "downloads": DELAY_BETWEEN_DOWNLOADS,
            "between_tabs": DELAY_BETWEEN_TABS
        },
        requests_config={
            "timeout": REQUESTS_TIMEOUT,
            "retries": REQUESTS_RETRIES
        },
        tabs=TABS_TO_PROCESS,
        file_ext=FILE_EXTENSION,
        skip_keywords=SKIP_KEYWORDS,
        min_file_size=MIN_FILE_SIZE,
        skip_existing=SKIP_EXISTING,
        accordion_config={
            "selector": ACCORDION_SELECTOR,
            "expand": EXPAND_ACCORDIONS,
            "scroll_before_click": SCROLL_BEFORE_CLICK
        },
        save_screenshots=SAVE_DEBUG_SCREENSHOTS
    )


# ============================================================================
# 📦 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def sanitize_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов"""
    filename = re.sub(r'\s*\(?\s*\d+[\.,]?\d*\s*[КKкkМм][БBбb]\s*\)?', '', filename, flags=re.IGNORECASE)
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = re.sub(r'\s+', ' ', filename)
    return filename.strip().strip('_.')


def make_safe_folder_name(name: str) -> str:
    """Делает безопасное имя папки из названия таба"""
    return sanitize_filename(name) or f"tab_{uuid.uuid4().hex[:6]}"


def download_file(
    url: str, 
    save_dir: Path, 
    display_name: str,
    file_ext: str = "pdf",
    skip_keywords: Optional[List[str]] = None,
    min_size: int = 1024,
    skip_existing: bool = True,
    timeout: int = 30,
    retries: int = 3
) -> Tuple[bool, Optional[Path]]:
    """Скачивает файл через requests с обработкой ошибок"""
    if skip_keywords is None:
        skip_keywords = []
    
    if not url or not isinstance(url, str):
        return False, None
    
    url = url.strip()
    url_lower = url.lower()
    
    # Пропуск по ключевым словам в URL
    if any(kw.lower() in url_lower for kw in skip_keywords):
        return True, None
    
    # Формируем имя файла
    base_name = sanitize_filename(display_name)
    if not base_name:
        base_name = f"document_{uuid.uuid4().hex[:8]}"
    
    filename = f"{base_name}.{file_ext}" if not base_name.lower().endswith(f".{file_ext}") else base_name
    
    # Пропуск по ключевым словам в имени
    if any(kw.lower() in filename.lower() for kw in skip_keywords):
        return True, None
    
    save_dir.mkdir(parents=True, exist_ok=True)
    final_path = save_dir / filename
    
    # Обработка дубликатов
    if skip_existing and final_path.exists() and final_path.stat().st_size >= min_size:
        return True, final_path
    
    if final_path.exists():
        stem = sanitize_filename(base_name)
        unique_id = uuid.uuid4().hex[:6]
        final_path = save_dir / f"{stem}_{unique_id}.{file_ext}"
    
    # Заголовки как у браузера
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
        "Referer": "https://www.vtb.ru/"
    }
    
    # Попытки скачивания
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            resp.raise_for_status()
            
            with open(final_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            if final_path.stat().st_size >= min_size:
                return True, final_path
            else:
                final_path.unlink(missing_ok=True)
                return False, None
                
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else None
            if status in (403, 404, 410):
                break
            time.sleep(1 * (attempt + 1))
        except requests.exceptions.RequestException:
            time.sleep(1 * (attempt + 1))
        except Exception:
            time.sleep(1 * (attempt + 1))
    
    return False, None


def expand_accordions(
    page: Page, 
    selector: str, 
    delay: float = 0.4,
    scroll_before: bool = True
) -> int:
    """
    Раскрывает аккордеоны по точному селектору.
    Returns: количество раскрытых элементов
    """
    accordions = page.locator(selector)
    count = accordions.count()
    
    if count == 0:
        return 0
    
    opened = 0
    
    for i in range(count):
        try:
            acc = accordions.nth(i)
            
            if not acc.is_visible():
                continue
            
            # Получаем название из h2
            title_el = acc.locator("h2").first
            title_text = title_el.inner_text().strip() if title_el.count() > 0 else f"#{i+1}"
            
            # Проверяем атрибут aria-expanded
            aria_exp = acc.get_attribute("aria-expanded")
            if aria_exp == "true":
                continue
            
            # Проверяем класс на open/active
            class_attr = acc.get_attribute("class") or ""
            if "open" in class_attr.lower() or "active" in class_attr.lower():
                continue
            
            # Скролл в видимую область если нужно
            if scroll_before:
                acc.scroll_into_view_if_needed()
                page.wait_for_timeout(100)
            
            # Кликаем
            acc.click()
            opened += 1
            
            if delay > 0:
                page.wait_for_timeout(delay * 1000)
                
        except Exception:
            continue
    
    return opened


def extract_pdf_links_from_page(page: Page, site_domain: str) -> List[Tuple[str, str]]:
    """
    Извлекает PDF-ссылки, используя заголовок аккордеона (h2) как имя файла.
    """
    results = {}
    
    pdf_data = page.evaluate("""() => {
        const links = [];
        
        const processLink = (a) => {
            const href = a.href?.trim();
            if (!href || !href.toLowerCase().includes('.pdf')) return null;
            
            // Ищем заголовок аккордеона: h2 в предыдущем соседе или в самом элементе
            let text = '';
            
            // Вариант 1: родитель .accordion-content, берём h2 из предыдущего sibling
            const contentParent = a.closest('.accordion-contentstyles__BoxOuter-accordion__sc-2gs3cd-0');
            if (contentParent) {
                const header = contentParent.previousElementSibling?.querySelector('h2');
                if (header?.innerText) text = header.innerText.trim();
            }
            
            // Вариант 2: ищем h2 внутри самого кликабельного элемента
            if (!text) {
                const accordionBtn = a.closest('div[role="button"][tabindex="0"]');
                if (accordionBtn) {
                    const h2 = accordionBtn.querySelector('h2');
                    if (h2?.innerText) text = h2.innerText.trim();
                }
            }
            
            // Вариант 3: текст самой ссылки или родителя
            if (!text && a.innerText?.trim()) {
                text = a.innerText.trim();
            }
            if (!text && a.parentElement?.innerText?.trim()) {
                text = a.parentElement.innerText.trim().split('\\n')[0];
            }
            
            return { href, text: text || 'tariff' };
        };
        
        document.querySelectorAll('a[href]').forEach(a => {
            const item = processLink(a);
            if (item) links.push(item);
        });
        
        return links;
    }""")
    
    for item in pdf_data:
        clean_url = item['href'].split('#')[0]
        
        if clean_url.startswith('/'):
            clean_url = urljoin(site_domain, clean_url)
        elif clean_url.startswith('//'):
            clean_url = f"https:{clean_url}"
        
        if site_domain in clean_url and clean_url not in results:
            name = item['text'] if item['text'] else Path(urlparse(clean_url).path).name
            results[clean_url] = name
    
    return [(url, name) for url, name in results.items() if name]


def switch_to_tab(page: Page, tab_name: str, timeout: int = 10000) -> bool:
    """Переключается на указанный таб, возвращает успех"""
    try:
        tab_locator = page.locator(
            "ul.tabs-headerstyles__TabTitleContainer-foundation-kit__sc-1w1sfys-0 li",
            has_text=tab_name
        ).first
        
        tab_locator.wait_for(state="visible", timeout=timeout)
        tab_locator.click()
        page.wait_for_load_state("networkidle")
        return True
    except Exception:
        return False


# ============================================================================
# 🚀 ОСНОВНОЙ ПАЙПЛАЙН
# ============================================================================

def run_pipeline(
    main_url: str,
    site_domain: str,
    output_root: Path,
    headless: bool = True,
    viewport: Tuple[int, int] = (1920, 1080),
    page_timeout: int = 60000,
    delays: Optional[Dict[str, float]] = None,
    requests_config: Optional[Dict[str, int]] = None,
    tabs: Optional[List[str]] = None,
    file_ext: str = "pdf",
    skip_keywords: Optional[List[str]] = None,
    min_file_size: int = 1024,
    skip_existing: bool = True,
    accordion_config: Optional[Dict] = None,
    save_screenshots: bool = False
):
    """Основной пайплайн обработки всех табов с аккордеонами"""
    
    # Дефолтные значения
    if delays is None:
        delays = {"after_load": 2.0, "after_tab": 1.5, "accordions": 0.4, "downloads": 0.5, "between_tabs": 1.0}
    if requests_config is None:
        requests_config = {"timeout": 30, "retries": 3}
    if tabs is None:
        tabs = ["Базовые тарифы", "Профессиональные тарифы", "Маржинальная торговля", "Полезная информация"]
    if accordion_config is None:
        accordion_config = {
            "selector": "div[role='button'][tabindex='0'].accordion-titlestyles__Box-accordion__sc-ncxzgq-1",
            "expand": True,
            "scroll_before_click": True
        }
    
    output_root.mkdir(parents=True, exist_ok=True)
    stats = {"total_found": 0, "total_downloaded": 0, "by_tab": {}}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": viewport[0], "height": viewport[1]},
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"}
        )
        page = context.new_page()
        page.set_default_timeout(page_timeout)
        
        # Загрузка страницы
        print(f"🌐 Загрузка: {main_url}")
        page.goto(main_url.strip(), wait_until="networkidle")
        page.wait_for_timeout(delays["after_load"] * 1000)
        
        if save_screenshots:
            page.screenshot(path="debug_01_page_loaded.png")
        
        # Обработка каждого таба
        for tab_idx, tab_name in enumerate(tabs, 1):
            print(f"\n[{tab_idx}/{len(tabs)}] 📑 Таб: '{tab_name}'")
            
            try:
                # Переключаем таб
                if not switch_to_tab(page, tab_name):
                    print(f"   ⚠️  Не удалось переключить таб")
                    stats["by_tab"][tab_name] = {"found": 0, "downloaded": 0}
                    continue
                
                page.wait_for_timeout(delays["after_tab"] * 1000)
                
                if save_screenshots:
                    page.screenshot(path=f"debug_02_tab_{tab_idx}.png")
                
                # Раскрываем аккордеоны
                opened_count = 0
                if accordion_config.get("expand", True):
                    opened_count = expand_accordions(
                        page,
                        selector=accordion_config["selector"],
                        delay=delays["accordions"],
                        scroll_before=accordion_config.get("scroll_before_click", True)
                    )
                    print(f"   🔓 Раскрыто аккордеонов: {opened_count}")
                
                # Извлекаем PDF-ссылки
                pdf_links = extract_pdf_links_from_page(page, site_domain)
                
                if not pdf_links:
                    print(f"   ⚠️  PDF не найдены")
                    stats["by_tab"][tab_name] = {"found": 0, "downloaded": 0}
                    continue
                
                print(f"   📄 Найдено PDF: {len(pdf_links)}")
                stats["total_found"] += len(pdf_links)
                
                # Папка для таба
                safe_tab = make_safe_folder_name(tab_name)
                tab_dir = output_root / safe_tab
                
                # Скачивание
                downloaded = 0
                for idx, (file_url, display_name) in enumerate(pdf_links, 1):
                    print(f"   [{idx}/{len(pdf_links)}] ⬇️  {display_name[:50]}")
                    
                    success, saved_path = download_file(
                        url=file_url,
                        save_dir=tab_dir,
                        display_name=display_name,
                        file_ext=file_ext,
                        skip_keywords=skip_keywords,
                        min_size=min_file_size,
                        skip_existing=skip_existing,
                        timeout=requests_config["timeout"],
                        retries=requests_config["retries"]
                    )
                    
                    if success:
                        if saved_path:
                            size = saved_path.stat().st_size
                            print(f"      ✅ {saved_path.name} ({size:,} B)")
                            downloaded += 1
                        else:
                            print(f"      ⏭️  Пропущен")
                    else:
                        print(f"      ❌ Ошибка скачивания")
                    
                    if delays["downloads"] > 0 and idx < len(pdf_links):
                        time.sleep(delays["downloads"])
                
                stats["by_tab"][tab_name] = {"found": len(pdf_links), "downloaded": downloaded}
                stats["total_downloaded"] += downloaded
                
            except Exception as e:
                print(f"   ❌ Ошибка: {e}")
                stats["by_tab"][tab_name] = {"found": 0, "downloaded": 0, "error": str(e)[:50]}
            
            if delays["between_tabs"] > 0 and tab_idx < len(tabs):
                time.sleep(delays["between_tabs"])
        
        browser.close()
    
    # Итоговый отчёт
    print(f"\n{'='*60}")
    print(f"📊 ИТОГО:")
    print(f"   Найдено: {stats['total_found']} | Скачано: {stats['total_downloaded']}")
    print(f"\n   По табам:")
    for tab_name, data in stats["by_tab"].items():
        err = f" (⚠️ {data.get('error', '')})" if "error" in data else ""
        print(f"   • {tab_name}: {data['downloaded']}/{data['found']}{err}")
    print(f"\n📁 Папка: {output_root.absolute()}")
    print(f"{'='*60}")
    
    return stats


if __name__ == "__main__":
    # Проверка зависимостей
    try:
        import requests
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Установите: pip install requests playwright")
        print("   Затем: playwright install chromium")
        exit(1)
    
    main()