#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔗 Единый пайплайн для скачивания PDF (ВЕРСИЯ 6.0 — одна папка на главную URL):
Структура: tbank_downloads/{последний_сегмент_ГЛАВНОЙ_url}/{все_файлы.pdf}

1. Извлекает ссылки с кнопок "Подробнее"
2. Ищет страницу с тарифами (исключая футер/меню)
3. Если ссылка на тарифы ведёт на PDF — скачивает сразу через requests
4. Если ссылка на тарифы ведёт на страницу — переходит и скачивает все PDF оттуда
5. Все PDF с одной главной страницы → в ОДНУ папку
6. Имена файлов: чистые, без нумерации (01_, 02_)
7. Дубликаты внутри папки пропускаются
8. Исключает: "Политика обработки персональных данных", "Условия комплексного банковского обслуживания"
"""

import os
import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


# ==================== ГЛОБАЛЬНЫЕ КОНСТАНТЫ ====================
SCRIPT_DIR = Path(__file__).parent.resolve()

# 🔥 ЗАПРЕЩЁННЫЕ ИМЕНА ФАЙЛОВ (регистронезависимые)
FORBIDDEN_PDF_NAMES = [
    "политика обработки персональных данных",
    "условия комплексного банковского обслуживания",
]

# 🔥 Ключевые слова для пропуска файлов
FORBIDDEN_KEYWORDS = [
    "_terms_and_definitions", "region-office", "_pamyatka", "instruction",
    "anketa", "_ios_", "_pravila_", "_pravyla_", "_obrazec_"
]

# 🔥 Паттерны для исключения универсальных ссылок на тарифы
EXCLUDED_TARIFF_PATTERNS = [
    "/mobile-operator/tariffs/",      
    "/business/tariffs/",             
    "/corporate/tariffs/",            
    "/cards/tariffs/",                
    "/tariffs/",                      
]


# ==================== УТИЛИТЫ ====================

def make_folder_name_from_last_segment(url: str) -> str:
    """Создаёт имя папки из ПОСЛЕДНЕГО сегмента URL. Заменяет '-' на '_'."""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    
    if not path_parts:
        return 'misc'
    
    last_segment = path_parts[-1]
    folder_name = last_segment.replace('-', '_')
    folder_name = re.sub(r'[<>:"/\\|?*]', '_', folder_name)
    folder_name = re.sub(r'\s+', '_', folder_name).strip('_')
    
    return folder_name[:200] or 'misc'


def sanitize_filename(filename: str) -> str:
    """Убирает опасные символы из имени файла"""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    filename = re.sub(r' +', ' ', filename)
    return filename[:200]


def is_forbidden_filename(filename: str) -> bool:
    """Проверяет, запрещено ли скачивать файл с таким именем"""
    filename_lower = filename.lower()
    
    for forbidden in FORBIDDEN_PDF_NAMES:
        if forbidden in filename_lower:
            return True
    
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in filename_lower:
            return True
    
    return False


def download_pdf(
    url: str, 
    save_dir: Path, 
    display_name: str,
    downloaded_in_session: Set[str]
) -> bool:
    """
    Скачивает PDF с чистым именем (без нумерации).
    Пропускает, если файл с таким именем уже скачан в этой сессии.
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    
    # 🔥 ФОРМИРОВАНИЕ ИМЕНИ ФАЙЛА
    base_name = display_name.strip() if display_name else ""
    
    if not base_name:
        base_name = url.split("/")[-1].split("?")[0]
        if not base_name or "." not in base_name.lower():
            base_name = f"document_{uuid.uuid4().hex[:8]}"
    
    if not base_name.lower().endswith('.pdf'):
        base_name += '.pdf'
    
    # Санитизация
    filename = sanitize_filename(base_name)

    # 🚫 Пропускаем файлы с запрещёнными именами
    if is_forbidden_filename(filename):
        print(f"   ⏭ Пропущено (запрещённое имя): {filename}")
        return True

    # 🔥 ПРОВЕРКА НА ДУБЛИКАТ в рамках текущей сессии/папки
    if filename in downloaded_in_session:
        print(f"   ⏭ Пропущено (уже скачан в этой папке): {filename}")
        return True

    final_path = save_dir / filename
    
    # Если файл физически уже есть на диске — добавляем уникальный суффикс
    if final_path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        unique_id = uuid.uuid4().hex[:6]
        filename = f"{stem}_{unique_id}{suffix}"
        final_path = save_dir / filename
    
    save_dir.mkdir(parents=True, exist_ok=True)

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        print(f"   💾 {display_name} -> {filename}")
        
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()

        with open(final_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        size_kb = final_path.stat().st_size / 1024
        print(f"   ✓ {filename} ({size_kb:.1f} КБ)")
        
        # 🔥 Добавляем в кэш скачанных для этой папки
        downloaded_in_session.add(filename)
        return True
        
    except Exception as e:
        print(f"   ✗ Ошибка: {type(e).__name__}: {e}")
        return False


# ==================== ПОИСК ССЫЛКИ "ТАРИФЫ" ====================

def find_tariff_link_on_page(
    page_url: str, 
    headless: bool = True, 
    search_pattern: str = r"тариф"
) -> Optional[Tuple[str, str]]:
    """
    Ищет ссылку на тарифы, исключая футер, меню и ненужные разделы.
    Возвращает кортеж: (url, link_type) где link_type: 'pdf' | 'page' | None
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(page_url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            
            regex = re.compile(search_pattern, re.IGNORECASE)
            link_locator = page.locator("a").filter(has_text=regex)
            
            count = link_locator.count()
            print(f"   🔍 Найдено ссылок с текстом 'тариф': {count}")
            
            for i in range(count):
                element = link_locator.nth(i)
                
                # 🔻 Проверка: ссылка в футере?
                try:
                    is_in_footer = element.evaluate("""
                        el => {
                            const footer = el.closest('footer');
                            const qaFooter = el.closest('[data-qa="footer"]');
                            const roleContentinfo = el.closest('[role="contentinfo"]');
                            return footer !== null || qaFooter !== null || roleContentinfo !== null;
                        }
                    """)
                except:
                    is_in_footer = False
                
                if is_in_footer:
                    print(f"   ⏭ Пропущена ссылка в футере (#{i+1})")
                    continue
                
                # 🔻 Проверка: ссылка в навигации/меню?
                try:
                    is_in_nav = element.evaluate("""
                        el => {
                            const nav = el.closest('nav');
                            const header = el.closest('header');
                            const menu = el.closest('[data-schema-path="items"]');
                            const popover = el.closest('[data-item-type="popover"]');
                            return nav !== null || header !== null || menu !== null || popover !== null;
                        }
                    """)
                except:
                    is_in_nav = False
                
                if is_in_nav:
                    print(f"   ⏭ Пропущена ссылка в меню навигации (#{i+1})")
                    continue
                
                try:
                    href = element.get_attribute("href")
                except:
                    continue
                
                if not href:
                    continue
                
                full_url = urljoin(page_url, href.strip())
                
                # 🔻 Пропускаем ссылки на текущую страницу
                if full_url.rstrip('/') == page_url.rstrip('/'):
                    print(f"   ⏭ Пропущена ссылка на текущую страницу")
                    continue
                
                # 🔻 Пропускаем универсальные разделы по паттерну
                if any(pattern in full_url for pattern in EXCLUDED_TARIFF_PATTERNS):
                    print(f"   ⏭ Пропущена универсальная ссылка: {full_url}")
                    continue
                
                # 🔻 Пропускаем прямые ссылки на другие домены
                if 'tbank.ru' not in full_url:
                    print(f"   ⏭ Пропущена ссылка на внешний домен: {full_url}")
                    continue
                
                # ✅ ОПРЕДЕЛЯЕМ ТИП ССЫЛКИ
                if full_url.lower().endswith('.pdf') or '.pdf?' in full_url.lower():
                    print(f"   ✅ Найдена прямая ссылка на PDF: {full_url}")
                    return (full_url, 'pdf')
                else:
                    print(f"   ✅ Найдена страница с тарифами: {full_url}")
                    return (full_url, 'page')
            
            return None
            
        except Exception as e:
            print(f"   ⚠ Ошибка поиска тарифов на {page_url}: {e}")
            return None
        finally:
            browser.close()


# ==================== ИЗВЛЕЧЕНИЕ PDF С ВИДИМЫМИ ИМЕНАМИ ====================

def extract_pdf_links_from_page(
    page_url: str, 
    headless: bool = True,
    name_filter: Optional[str] = None
) -> List[Tuple[str, str]]:
    """
    Извлекает ссылки на PDF и их ВИДИМЫЕ имена (текст ссылки).
    Возвращает список кортежей: [(url, display_name), ...]
    """
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            page.goto(page_url, timeout=60000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            raw_data = page.eval_on_selector_all('a', """
                links => links
                    .filter(a => {
                        const href = a.href?.toLowerCase() || '';
                        return href.endsWith('.pdf') || href.includes('.pdf?');
                    })
                    .map(a => ({
                        href: a.href,
                        text: (a.textContent || a.innerText || '').trim()
                    }))
            """)

            seen = set()
            for item in raw_data:
                href = item.get('href')
                text = item.get('text', '')
                
                if not href:
                    continue
                
                full_url = urljoin(page_url, href.split('#')[0].strip())
                
                # Проверка на дубли и домен
                if full_url in seen or 'tbank.ru' not in full_url:
                    continue
                
                # 🔥 ФИЛЬТРАЦИЯ по видимому имени
                if name_filter and name_filter.lower() not in text.lower():
                    print(f"   ⏭ Пропущено (фильтр '{name_filter}'): {text}")
                    continue
                
                seen.add(full_url)
                results.append((full_url, text))

        except Exception as e:
            print(f"   ✗ Ошибка извлечения PDF: {e}")
        finally:
            browser.close()

    return results


# ==================== ЭТАП 1: Извлечение ссылок "Подробнее" ====================

def extract_podrobnee_links(main_url: str, headless: bool = True) -> List[str]:
    """Извлекает все уникальные ссылки с элементов, содержащих текст 'Подробнее'"""
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            print(f"🔍 Парсинг главной страницы: {main_url}")
            page.goto(main_url, timeout=60000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

            elements = page.locator("text=/подробнее/i").all()
            print(f"   Найдено элементов 'Подробнее': {len(elements)}")

            for el in elements:
                if not el.is_visible():
                    continue
                try:
                    href = el.evaluate("""
                        el => {
                            if (el.tagName.toLowerCase() === 'a' && el.href) return el.href;
                            const parentA = el.closest('a');
                            return parentA ? parentA.href : null;
                        }
                    """)
                    if href and isinstance(href, str) and href.startswith('http'):
                        clean_href = href.split('#')[0].strip()
                        if 'tbank.ru' in clean_href and clean_href not in results:
                            results.append(clean_href)
                except:
                    continue

        except Exception as e:
            print(f"   ✗ Ошибка при парсинге: {e}")
        finally:
            browser.close()

    print(f"✅ Всего уникальных ссылок: {len(results)}\n")
    return results


# ==================== ЭТАП 2: Скачивание PDF (универсальная функция) ====================

def download_pdfs_from_page(
    page_url: str, 
    save_dir: Path, 
    headless: bool = True,
    pdf_name_filter: Optional[str] = None,
    direct_pdf_url: Optional[str] = None,
    downloaded_in_session: Optional[Set[str]] = None
) -> int:
    """
    Скачивает PDF: либо напрямую по URL, либо извлекает со страницы.
    """
    if downloaded_in_session is None:
        downloaded_in_session = set()
    
    print(f"\n📄 Обработка: {page_url}")
    print(f"   📁 Сохранение в: {save_dir}")
    if pdf_name_filter:
        print(f"   🔎 Фильтр имён: '{pdf_name_filter}'")

    # 🔥 СЦЕНАРИЙ 1: Прямая ссылка на PDF
    if direct_pdf_url:
        print(f"   📥 Скачивание прямого PDF: {direct_pdf_url}")
        filename = direct_pdf_url.split("/")[-1].split("?")[0]
        if not filename or "." not in filename.lower():
            filename = "tariff_document.pdf"
        if download_pdf(direct_pdf_url, save_dir=save_dir, display_name=filename, downloaded_in_session=downloaded_in_session):
            return 1
        return 0

    # 🔥 СЦЕНАРИЙ 2: Извлекаем PDF со страницы
    pdf_data = extract_pdf_links_from_page(
        page_url, 
        headless=headless,
        name_filter=pdf_name_filter
    )
    
    if not pdf_data:
        print("   ℹ PDF-файлы не найдены (или отфильтрованы)")
        return 0

    print(f"   📊 Найдено PDF: {len(pdf_data)}")

    success = 0
    for pdf_url, display_name in pdf_data:
        if download_pdf(pdf_url, save_dir=save_dir, display_name=display_name, downloaded_in_session=downloaded_in_session):
            success += 1
        time.sleep(0.8)

    print(f"   ✅ Скачано: {success}/{len(pdf_data)}")
    return success


# ==================== ГЛАВНЫЙ ПАЙПЛАЙН ====================

def run_pipeline(
    main_url: str,
    output_root: Path,
    headless: bool = True,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    tariff_search_pattern: str = r"тариф",
    pdf_name_filter: Optional[str] = None
) -> int:
    """
    Запускает полный пайплайн.
    🔥 ВСЕ PDF с одной главной URL сохраняются в ОДНУ папку!
    """
    print("🚀 Запуск пайплайна TBank PDF Downloader\n")

    # 🔥 Создаём ОДНУ папку для всей главной URL (из последнего сегмента)
    folder_name = make_folder_name_from_last_segment(main_url)
    target_dir = output_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Все PDF будут сохранены в: {target_dir}\n")

    # 🔥 Одно множество для всех дублей в этой папке
    downloaded_in_session: Set[str] = set()

    detail_links = extract_podrobnee_links(main_url, headless=headless)
    if not detail_links:
        print("❌ Не найдено ссылок для обработки. Завершение.")
        return 0

    total_downloaded = 0
    
    for idx, link in enumerate(detail_links, 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{len(detail_links)}] Обработка ссылки: {link}")
        print(f"{'='*70}")
        
        print(f"   🔎 Поиск ссылки 'Тарифы'...")
        tariff_result = find_tariff_link_on_page(
            link, 
            headless=headless, 
            search_pattern=tariff_search_pattern
        )
        
        if tariff_result:
            tariff_url, link_type = tariff_result
            print(f"   ✅ Найдено: тип='{link_type}', ссылка={tariff_url}")
            
            if link_type == 'pdf':
                print(f"   📥 Режим: скачивание прямого PDF")
                count = download_pdfs_from_page(
                    tariff_url, 
                    save_dir=target_dir,  # 🔥 Одна папка для всех
                    headless=headless,
                    pdf_name_filter=pdf_name_filter,
                    direct_pdf_url=tariff_url,
                    downloaded_in_session=downloaded_in_session
                )
            else:
                print(f"   📥 Режим: парсинг страницы с тарифами")
                count = download_pdfs_from_page(
                    tariff_url, 
                    save_dir=target_dir,  # 🔥 Одна папка для всех
                    headless=headless,
                    pdf_name_filter=pdf_name_filter,
                    direct_pdf_url=None,
                    downloaded_in_session=downloaded_in_session
                )
            total_downloaded += count
        else:
            print(f"   ⚠ Ссылка 'Тарифы' не найдена, пробуем исходную страницу")
            count = download_pdfs_from_page(
                link, 
                save_dir=target_dir,  # 🔥 Одна папка для всех
                headless=headless,
                pdf_name_filter=pdf_name_filter,
                downloaded_in_session=downloaded_in_session
            )
            total_downloaded += count

        if idx < len(detail_links):
            delay = random.uniform(min_delay, max_delay)
            print(f"   ⏱ Пауза {delay:.1f} сек...")
            time.sleep(delay)

    return total_downloaded


# ==================== ТОЧКА ВХОДА ====================

if __name__ == "__main__":
    # 🔧 НАСТРОЙКИ
    URLS = [
        "https://www.tbank.ru/mortgage",
        # "https://www.tbank.ru/savings/deposit/",
        # "https://www.tbank.ru/loans/",        
        # "https://www.tbank.ru/cards/debit-cards/",
        # "https://www.tbank.ru/cards/credit-cards/",
    ]
    
    # 🔥 КОРНЕВАЯ ПАПКА → внутри будут подпапки по ГЛАВНЫМ URL
    OUTPUT_ROOT = "tbank_downloads"
    
    HEADLESS = False  # True для работы без окна браузера
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0
    TARIFF_SEARCH_PATTERN = r"тарифы"
    PDF_NAME_FILTER = None  # None — все файлы, или "Тарифы" для фильтрации

    # 🔥 Создаём корневую папку
    output_root = Path(OUTPUT_ROOT)
    if not output_root.is_absolute():
        output_root = SCRIPT_DIR / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    
    total = 0
    for idx, url in enumerate(URLS, 1):
        url = url.strip()
        if not url:
            continue
            
        print(f"\n{'#'*70}")
        print(f"📦 [{idx}/{len(URLS)}] Группа: {url}")
        print(f"{'#'*70}\n")
        
        count = run_pipeline(
            main_url=url,
            output_root=output_root,
            headless=HEADLESS,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            tariff_search_pattern=TARIFF_SEARCH_PATTERN,
            pdf_name_filter=PDF_NAME_FILTER
        )
        total += count
        
        if url != URLS[-1]:
            print(f"\n⏳ Пауза между группами...")
            time.sleep(random.uniform(2.0, 5.0))

    print(f"\n{'='*70}")
    print(f"🏁 Пайплайн завершён!")
    print(f"📁 Путь: {output_root.resolve()}")
    print(f"📊 Всего скачано: {total}")
    print(f"{'='*70}")