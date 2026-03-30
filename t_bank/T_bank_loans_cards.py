#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔗 Единый пайплайн для скачивания PDF (ОБНОВЛЁННАЯ ВЕРСИЯ):
1. Извлекает ссылки с кнопок "Подробнее"
2. Ищет страницу с тарифами (исключая футер)
3. Скачивает PDF с ИМЕНЕМ ИЗ ТЕКСТА ССЫЛКИ (видимое название)
4. 🔥 БЕЗ НУМЕРАЦИИ в именах файлов
5. 🔥 ФИЛЬТРАЦИЯ по нежелательным фразам в названии
"""

import os
import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright


# ==================== ГЛОБАЛЬНЫЕ КОНСТАНТЫ ====================
SCRIPT_DIR = Path(__file__).parent.resolve()

# 🔒 Технические ключевые слова для пропуска (оригинальные)
SKIP_KEYWORDS = [
    "_terms_and_definitions", "region-office", "_pamyatka", "instruction",
    "anketa", "_ios_", "_pravila_", "_pravyla_", "_obrazec_"
]

# 🔥 НОВЫЙ СПИСОК: фразы для исключения документов (в нижнем регистре)
SKIP_PHRASES = [
    "условия передачи информации",
    "политика обработки персональных данных",
    "условия комплексного банковского обслуживания",
    "безопасное использование банковской карты",
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


def download_pdf(url: str, save_dir: Path, display_name: str, prefix: str = "") -> bool:
    """
    🔥 Скачивает PDF и сохраняет строго с display_name (видимое имя ссылки).
    Имя файла в URL полностью игнорируется.
    ⚠️ БЕЗ НУМЕРАЦИИ — имя файла чистое!
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    
    # 🔥 ФОРМИРОВАНИЕ ИМЕНИ ФАЙЛА
    # 1. Берем видимое имя ссылки
    base_name = display_name.strip() if display_name else ""
    
    # 2. Если видимое имя пустое, только тогда берем из URL (fallback)
    if not base_name:
        base_name = url.split("/")[-1].split("?")[0]
        if not base_name or "." not in base_name.lower():
            base_name = f"document_{uuid.uuid4().hex[:8]}"
    
    # 3. Гарантированно добавляем .pdf
    if not base_name.lower().endswith('.pdf'):
        base_name += '.pdf'
    
    # 4. Санитизация (🔥 БЕЗ ПРЕФИКСА-НУМЕРАЦИИ)
    filename = sanitize_filename(f"{prefix}{base_name}")
    filename_lower = filename.lower()

    # 🚫 Проверка 1: старые ключевые слова
    if any(kw in filename_lower for kw in SKIP_KEYWORDS):
        print(f"   ⏭ Пропущено (ключевое слово): {filename}")
        return True
    
    # 🔥 Проверка 2: новые фразы для исключения
    if any(phrase in filename_lower for phrase in SKIP_PHRASES):
        print(f"   ⏭ Пропущено (исключённая фраза): {filename}")
        return True

    final_path = save_dir / filename
    
    # Уникальность имени (если файл уже существует)
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
        return True
        
    except Exception as e:
        print(f"   ✗ Ошибка: {type(e).__name__}: {e}")
        return False


# ==================== ПОИСК ССЫЛКИ "ТАРИФЫ" ====================

def find_tariff_link_on_page(page_url: str, headless: bool = True, search_pattern: str = r"тариф") -> Optional[str]:
    """
    Ищет ссылку на тарифы, исключая футер, меню и PDF-файлы.
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
            
            excluded_patterns = [
                "/mobile-operator/tariffs/",      
                "/business/tariffs/",             
                "/corporate/tariffs/",            
                "/cards/tariffs/",                
                "/tariffs/",
                "/mortgage/",                      
            ]
            
            for i in range(count):
                element = link_locator.nth(i)
                
                # Проверка на футер
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
                
                # Проверка на навигацию
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
                
                # Исключаем прямые ссылки на PDF
                if href.lower().endswith(".pdf"):
                    print(f"   ⏭ Пропущена ссылка на PDF-файл: {href}")
                    continue
                
                # Исключаем универсальные ссылки по паттерну
                if any(pattern in href for pattern in excluded_patterns):
                    print(f"   ⏭ Пропущена универсальная ссылка: {href}")
                    continue
                
                # Исключаем ссылки на текущую страницу
                full_url = urljoin(page_url, href.strip())
                if full_url.rstrip('/') == page_url.rstrip('/'):
                    print(f"   ⏭ Пропущена ссылка на текущую страницу")
                    continue
                
                # ✅ Нашли подходящую ссылку
                print(f"   ✅ Найдена релевантная ссылка: {full_url}")
                return full_url
            
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
    🔥 Извлекает ссылки на PDF и их ВИДИМЫЕ имена (текст ссылки).
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

            # 🔥 Извлекаем href и видимый текст (textContent)
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
                # 🔥 Сохраняем кортеж (URL, Видимое_Имя)
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
    print(*results)
    return results


# ==================== ЭТАП 2: Поиск и скачивание PDF ====================

def download_pdfs_from_page(
    page_url: str, 
    save_dir: Path, 
    headless: bool = True,
    pdf_name_filter: Optional[str] = None
) -> int:
    """
    Переходит на страницу, находит PDF с видимыми именами и скачивает их.
    🔥 БЕЗ НУМЕРАЦИИ в именах файлов
    """
    print(f"\n📄 Обработка: {page_url}")
    print(f"   📁 Сохранение в: {save_dir}")
    if pdf_name_filter:
        print(f"   🔎 Фильтр имён: '{pdf_name_filter}'")

    # 🔥 Извлекаем URL + видимые имена
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
    for i, (pdf_url, display_name) in enumerate(pdf_data, 1):
        # 🔥 УБРАНА НУМЕРАЦИЯ: prefix больше не добавляется
        # prefix = f"{i:02d}_"  ← удалено
        if download_pdf(pdf_url, save_dir=save_dir, display_name=display_name, prefix=""):
            success += 1
        time.sleep(0.8)

    print(f"   ✅ Скачано: {success}/{len(pdf_data)}")
    return success


# ==================== ГЛАВНЫЙ ПАЙПЛАЙН ====================

def run_pipeline(
    main_url: str,
    output_root: str = "tbank_downloads",
    headless: bool = True,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    base_subfolder: str = None,
    tariff_search_pattern: str = r"тариф",
    pdf_name_filter: Optional[str] = None
):
    """Запускает полный пайплайн с фильтрацией по именам PDF."""
    print("🚀 Запуск пайплайна TBank PDF Downloader\n")

    detail_links = extract_podrobnee_links(main_url, headless=headless)
    if not detail_links:
        print("❌ Не найдено ссылок для обработки. Завершение.")
        return

    root_path = Path(output_root)
    if not root_path.is_absolute():
        root_path = SCRIPT_DIR / root_path
    root_path.mkdir(parents=True, exist_ok=True)

    total_downloaded = 0
    for idx, link in enumerate(detail_links, 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{len(detail_links)}] Обработка ссылки")
        print(f"{'='*70}")
        
        folder_name = make_folder_name_from_last_segment(link)
        print(f"   📁 Имя папки: '{folder_name}'")
        
        if base_subfolder:
            target_dir = root_path / base_subfolder / folder_name
        else:
            target_dir = root_path / folder_name
        
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"   📂 Путь: {target_dir}")
        
        print(f"   🔎 Поиск ссылки 'Тарифы' на: {link}")
        tariff_url = find_tariff_link_on_page(
            link, 
            headless=headless, 
            search_pattern=tariff_search_pattern
        )
        
        if tariff_url:
            print(f"   ✅ Найдена тарифная страница: {tariff_url}")
            target_url = tariff_url
        else:
            print(f"   ⚠ Ссылка 'Тарифы' не найдена, используем исходную")
            target_url = link
        
        count = download_pdfs_from_page(
            target_url, 
            save_dir=target_dir,
            headless=headless,
            pdf_name_filter=pdf_name_filter
        )
        total_downloaded += count

        if idx < len(detail_links):
            delay = random.uniform(min_delay, max_delay)
            print(f"   ⏱ Пауза {delay:.1f} сек...")
            time.sleep(delay)

    print(f"\n{'='*70}")
    print(f"🏁 Пайплайн завершён!")
    print(f"📁 Путь: {root_path.resolve()}")
    print(f"📊 Всего скачано: {total_downloaded}")
    print(f"{'='*70}")


# ==================== ТОЧКА ВХОДА ====================

if __name__ == "__main__":
    # 🔧 НАСТРОЙКИ
    URLS = [
        "https://www.tbank.ru/loans/",        
        "https://www.tbank.ru/cards/debit-cards/",
        "https://www.tbank.ru/cards/credit-cards/",
    ]
    
    OUTPUT_FOLDER = "tbank_downloads"
    HEADLESS = False
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0
    TARIFF_SEARCH_PATTERN = r"тарифы"
    
    # 🔥 ФИЛЬТР ИМЁН PDF
    # None или "" — скачает ВСЕ найденные PDF
    # "Тарифы" — скачает только файлы с "Тарифы" в видимом названии
    PDF_NAME_FILTER = None

    for url in URLS:
        url = url.strip()
        if not url:
            continue
            
        base_subfolder = make_folder_name_from_last_segment(url)
        
        print(f"\n{'#'*70}")
        print(f"📦 Группа: {base_subfolder}")
        print(f"🔗 URL: {url}")
        print(f"{'#'*70}\n")
        
        run_pipeline(
            main_url=url,
            output_root=OUTPUT_FOLDER,
            headless=HEADLESS,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            base_subfolder=base_subfolder,
            tariff_search_pattern=TARIFF_SEARCH_PATTERN,
            pdf_name_filter=PDF_NAME_FILTER
        )
        
        if url != URLS[-1]:
            print(f"\n⏳ Пауза между группами...")
            time.sleep(random.uniform(2.0, 5.0))