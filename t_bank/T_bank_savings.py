#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔗 ФИНАЛЬНЫЙ пайплайн для скачивания PDF:
1. Берёт исходный URL напрямую
2. Ищет ссылку "Тарифы" (может вести на страницу или сразу на PDF)
3. Скачивает PDF с ИМЕНЕМ ИЗ ТЕКСТА ССЫЛКИ (без нумерации!)
4. Фильтрует нежелательные документы по фразам в названии
"""

import os
import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


# ==================== ГЛОБАЛЬНЫЕ КОНСТАНТЫ ====================
SCRIPT_DIR = Path(__file__).parent.resolve()

# 🔒 Технические ключевые слова для пропуска
SKIP_KEYWORDS = [
    "_terms_and_definitions", "region-office", "_pamyatka", "instruction",
    "anketa", "_ios_", "_pravila_", "_pravyla_", "_obrazec_"
]

# 🔥 Фразы для исключения документов (в нижнем регистре)
SKIP_PHRASES = [
    "условия передачи информации",
    "политика обработки персональных данных",
    "условия комплексного банковского обслуживания",
    "безопасное использование банковской карты",
]


# ==================== УТИЛИТЫ ====================

def make_folder_name_from_last_segment(url: str) -> str:
    """Создаёт имя папки из последнего сегмента URL"""
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
    return filename[:200] or 'document'


def download_pdf(url: str, save_dir: Path, display_name: str) -> bool:
    """
    🔥 Скачивает PDF и сохраняет с именем из видимого текста ссылки.
    ⚠️ БЕЗ НУМЕРАЦИИ — имя файла чистое!
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    
    # Формирование имени файла
    base_name = display_name.strip() if display_name else ""
    
    if not base_name:
        base_name = url.split("/")[-1].split("?")[0]
        if not base_name or "." not in base_name.lower():
            base_name = f"document_{uuid.uuid4().hex[:8]}"
    
    if not base_name.lower().endswith('.pdf'):
        base_name += '.pdf'
    
    # 🔥 БЕЗ ПРЕФИКСА — сразу санитизация
    filename = sanitize_filename(base_name)
    filename_lower = filename.lower()

    # 🚫 Проверка: ключевые слова
    if any(kw in filename_lower for kw in SKIP_KEYWORDS):
        print(f"   ⏭ Пропущено (ключевое слово): {filename}")
        return True
    
    # 🔥 Проверка: исключённые фразы
    if any(phrase in filename_lower for phrase in SKIP_PHRASES):
        print(f"   ⏭ Пропущено (исключённая фраза): {filename}")
        return True

    final_path = save_dir / filename
    
    # Уникальность имени (если файл уже есть)
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

def find_tariff_link_on_page(
    page_url: str, 
    headless: bool = True, 
    search_pattern: str = r"тариф"
) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    🔥 Ищет ссылку на тарифы.
    Возвращает кортеж: (url, is_direct_pdf, display_name)
    - url: найденный URL или None
    - is_direct_pdf: True если ссылка ведёт сразу на PDF
    - display_name: видимый текст ссылки (для имени файла)
    """
    page_url = page_url.strip()
    
    # 🔙 Исключения: универсальные страницы тарифов
    EXCLUDED_PATTERNS = [
        "/mobile-operator/tariffs/",
        "/business/tariffs/",
        "/corporate/tariffs/",
        "/cards/tariffs/",
        "/invest/tariffs/",
        "/insurance/tariffs/",
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        
        try:
            page.goto(page_url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)  # Пауза для рендера
            
            regex = re.compile(search_pattern, re.IGNORECASE)
            link_locator = page.locator("a").filter(has_text=regex)
            
            count = link_locator.count()
            
            for i in range(count):
                element = link_locator.nth(i)
                
                # 🔒 Проверка на футер
                try:
                    is_in_footer = element.evaluate("""
                        el => el.closest('footer, [data-qa="footer"], [role="contentinfo"]') !== null
                    """)
                except:
                    is_in_footer = False
                if is_in_footer:
                    continue
                
                # 🔒 Проверка на навигацию
                try:
                    is_in_nav = element.evaluate("""
                        el => el.closest('nav, header, [data-schema-path="items"]') !== null
                    """)
                except:
                    is_in_nav = False
                if is_in_nav:
                    continue
                
                # 🔥 Получаем href и видимый текст
                try:
                    href = element.get_attribute("href")
                    text = element.text_content().strip()
                except:
                    continue
                
                if not href:
                    continue
                
                full_url = urljoin(page_url, href.strip())
                
                # 🔥 Если ссылка ведёт на PDF — возвращаем сразу!
                if full_url.lower().endswith(".pdf") or ".pdf?" in full_url.lower():
                    print(f"   ✅ Прямая ссылка на PDF: {full_url}")
                    return full_url, True, text if text else full_url.split('/')[-1]
                
                # 🔒 Исключаем универсальные страницы
                if any(pattern in full_url for pattern in EXCLUDED_PATTERNS):
                    continue
                
                # 🔒 Исключаем ссылку на текущую страницу
                if full_url.rstrip('/') == page_url.rstrip('/'):
                    continue
                
                # ✅ Нашли страницу с тарифами
                print(f"   ✅ Страница тарифов: {full_url}")
                return full_url, False, text
            
            return None, False, None
            
        except Exception as e:
            print(f"   ⚠ Ошибка поиска: {type(e).__name__}: {str(e)[:150]}")
            return None, False, None
        finally:
            browser.close()


# ==================== ИЗВЛЕЧЕНИЕ ВСЕХ PDF СО СТРАНИЦЫ ====================

def extract_all_pdf_links_from_page(
    page_url: str, 
    headless: bool = True,
    name_filter: Optional[str] = None
) -> List[Tuple[str, str]]:
    """
    Извлекает все PDF со страницы + их видимые имена.
    Возвращает: [(url, display_name), ...]
    """
    results = []
    page_url = page_url.strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            page.goto(page_url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

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
                
                if full_url in seen or 'tbank.ru' not in full_url:
                    continue
                
                # Фильтрация по имени (если задана)
                if name_filter and name_filter.lower() not in text.lower():
                    continue
                
                seen.add(full_url)
                display_name = text if text else full_url.split('/')[-1].replace('.pdf', '')
                results.append((full_url, display_name))

        except Exception as e:
            print(f"   ✗ Ошибка извлечения PDF: {e}")
        finally:
            browser.close()

    return results


# ==================== СКАЧИВАНИЕ СПИСКА PDF ====================

def download_pdfs_from_list(
    pdf_list: List[Tuple[str, str]], 
    save_dir: Path,
    name_filter: Optional[str] = None
) -> int:
    """Скачивает список PDF без нумерации в именах"""
    if not pdf_list:
        print("   ℹ Нет файлов для скачивания")
        return 0

    print(f"   📊 К скачиванию: {len(pdf_list)} файлов")
    success = 0
    
    for pdf_url, display_name in pdf_list:
        # Дополнительная фильтрация
        if name_filter and name_filter.lower() not in display_name.lower():
            continue
            
        if download_pdf(pdf_url, save_dir=save_dir, display_name=display_name):
            success += 1
        time.sleep(0.5)

    print(f"   ✅ Скачано: {success}/{len(pdf_list)}")
    return success


# ==================== 🔥 ГЛАВНЫЙ ПАЙПЛАЙН ====================

def run_pipeline_direct(
    main_url: str,
    output_root: str = "tbank_downloads",
    headless: bool = True,
    tariff_search_pattern: str = r"тариф",
    pdf_name_filter: Optional[str] = None
):
    """
    🔥 ФИНАЛЬНЫЙ ПАЙПЛАЙН:
    1. Ищет "Тарифы" (страница или прямой PDF)
    2. Скачивает PDF с именем из текста ссылки (БЕЗ НУМЕРАЦИИ)
    3. Применяет фильтрацию по фразам
    """
    main_url = main_url.strip()
    if not main_url.startswith(('http://', 'https://')):
        main_url = 'https://' + main_url
    
    print(f"🚀 Старт: {main_url}\n")

    root_path = Path(output_root)
    if not root_path.is_absolute():
        root_path = SCRIPT_DIR / root_path
    root_path.mkdir(parents=True, exist_ok=True)

    folder_name = make_folder_name_from_last_segment(main_url)
    save_dir = root_path / folder_name
    save_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Сохранение в: {save_dir}\n")

    # 🔍 Ищем ссылку "Тарифы"
    print(f"🔎 Поиск: '{tariff_search_pattern}' на {main_url}")
    found_url, is_direct_pdf, display_name = find_tariff_link_on_page(
        main_url, 
        headless=headless, 
        search_pattern=tariff_search_pattern
    )

    if found_url and is_direct_pdf:
        # 🔥 Прямая ссылка на PDF — скачиваем один файл
        print(f"   📄 Скачиваем прямой PDF...")
        download_pdf(found_url, save_dir=save_dir, display_name=display_name)
        total_downloaded = 1
        
    elif found_url and not is_direct_pdf:
        # 🔥 Страница с тарифами — ищем на ней все PDF
        print(f"   📄 Ищем PDF на странице тарифов...")
        pdf_list = extract_all_pdf_links_from_page(
            found_url, 
            headless=headless, 
            name_filter=pdf_name_filter
        )
        total_downloaded = download_pdfs_from_list(pdf_list, save_dir, pdf_name_filter)
        
    else:
        # 🔥 Не нашли "Тарифы" — пробуем скачать все PDF с исходной страницы
        print(f"   ⚠ Не найдено, ищем PDF на исходной странице...")
        pdf_list = extract_all_pdf_links_from_page(
            main_url, 
            headless=headless, 
            name_filter=pdf_name_filter
        )
        total_downloaded = download_pdfs_from_list(pdf_list, save_dir, pdf_name_filter)

    print(f"\n{'='*70}")
    print(f"🏁 Готово!")
    print(f"📁 Путь: {save_dir.resolve()}")
    print(f"📊 Скачано файлов: {total_downloaded}")
    print(f"{'='*70}")
    
    return total_downloaded


# ==================== 🔥 ТОЧКА ВХОДА ====================

if __name__ == "__main__":
    # 🔧 НАСТРОЙКИ
    TARGET_URLS = [
        "https://www.tbank.ru/savings/deposit/",
        "https://www.tbank.ru/savings/saving-account/",        
        # ➕ Добавьте свои ссылки
    ]
    
    OUTPUT_FOLDER = "tbank_downloads"
    HEADLESS = False  # 👀 False = видим браузер (удобно для отладки)
    TARIFF_SEARCH_PATTERN = r"тарифы?"  # Паттерн поиска кнопки
    
    # 🔥 ФИЛЬТР ИМЁН:
    # None — скачать все найденные PDF
    # "Тариф" — только файлы с "Тариф" в названии
    PDF_NAME_FILTER = None

    for idx, url in enumerate(TARGET_URLS, 1):
        url = url.strip()
        if not url:
            continue
            
        print(f"\n{'#'*70}")
        print(f"[{idx}/{len(TARGET_URLS)}] Обработка: {url}")
        print(f"{'#'*70}\n")
        
        run_pipeline_direct(
            main_url=url,
            output_root=OUTPUT_FOLDER,
            headless=HEADLESS,
            tariff_search_pattern=TARIFF_SEARCH_PATTERN,
            pdf_name_filter=PDF_NAME_FILTER
        )
        
        if idx < len(TARGET_URLS):
            delay = random.uniform(2.0, 5.0)
            print(f"\n⏳ Пауза {delay:.1f} сек...\n")
            time.sleep(delay)
    
    print(f"\n🎉 Все ссылки обработаны!")