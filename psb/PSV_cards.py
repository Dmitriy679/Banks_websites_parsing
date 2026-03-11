#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔗 Единый пайплайн: 
1. Извлекает ссылки с кнопок "Подробнее" с главной страницы
2. Для каждой ссылки: находит и скачивает все PDF в папку, 
   названную по последним 2 сегментам URL
"""

import os
import re
import time
import uuid
import requests
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright, Page, Browser


# ==================== УТИЛИТЫ ====================

def make_folder_name_from_url(url: str) -> str:
    """
    Создаёт имя папки из последних 2 сегментов пути URL.
    Пример: https://psbank.ru/a/b/c → 'b_c'
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]  # убираем пустые
    last_two = path_parts[-2:] if len(path_parts) >= 2 else path_parts
    # Заменяем опасные символы, оставляем буквы/цифры/дефисы/подчёркивания
    safe_parts = [re.sub(r'[^\w\-]', '_', unquote(p)) for p in last_two]
    return '_'.join(safe_parts) if safe_parts else 'misc'


def sanitize_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов"""
    return re.sub(r'[<>:"/\\|?*]', '_', filename).strip()


def download_pdf(url: str, save_dir: Path, prefix: str = "") -> bool:
    """
    Скачивает PDF и сохраняет в указанную папку.
    Возвращает True при успехе.
    """
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    
    # Формируем имя файла
    raw_name = url.split("/")[-1].split("?")[0]
    if not raw_name or "." not in raw_name.lower():
        raw_name = f"document_{uuid.uuid4().hex[:8]}.pdf"
    
    filename = sanitize_filename(f"{prefix}{raw_name}")
    
    # 🚫 ПРОПУСКАЕМ файлы с "instruction" в названии (регистронезависимо)
    if "instruction" in filename.lower():
        print(f"   ⊗ Пропущено (instruction): {filename}")
        return True  # Возвращаем True, чтобы не считать это ошибкой
    
    final_path = save_dir / filename
    
    # Уникальность имени
    if final_path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        unique_id = uuid.uuid4().hex[:6]
        final_path = save_dir / f"{stem}_{unique_id}{suffix}"
    
    save_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        print(f"   ↓ {url}")
        
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        
        with open(final_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        size_kb = final_path.stat().st_size / 1024
        print(f"   ✓ {final_path.name} ({size_kb:.1f} КБ)")
        return True
        
    except Exception as e:
        print(f"   ✗ Ошибка: {type(e).__name__}: {e}")
        return False


# ==================== ЭТАП 1: Извлечение ссылок "Подробнее" ====================

def extract_podrobnee_links(main_url: str, headless: bool = True) -> List[str]:
    """
    Извлекает все уникальные ссылки с элементов, содержащих текст "Подробнее"
    """
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        try:
            print(f"🔍 Парсинг главной страницы: {main_url}")
            page.goto(main_url, wait_until="networkidle", timeout=60000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            
            # Ищем элементы с текстом "Подробнее" (регистронезависимо)
            elements = page.locator("text=/подробнее/i").all()
            print(f"✅ Найдено элементов 'Подробнее': {len(elements)}")
            
            for el in elements:
                if not el.is_visible():
                    continue
                try:
                    # Пробуем получить ссылку напрямую или через родителя <a>
                    href = el.evaluate("""
                        el => {
                            if (el.tagName.toLowerCase() === 'a' && el.href) return el.href;
                            const link = el.closest('a');
                            return link?.href || el.getAttribute('data-url') || null;
                        }
                    """)
                    if href and isinstance(href, str) and href.startswith('http'):
                        # Нормализуем и фильтруем
                        clean_href = href.split('#')[0].strip()
                        if 'psbank.ru' in clean_href and clean_href not in results:
                            results.append(clean_href)
                            print(f"   → {clean_href}")
                except:
                    continue
                    
        except Exception as e:
            print(f"⚠️ Ошибка при парсинге: {e}")
        finally:
            browser.close()
    
    print(f"📋 Всего уникальных ссылок: {len(results)}\n")
    return results


# ==================== ЭТАП 2: Поиск и скачивание PDF со страницы ====================

def download_pdfs_from_page(page_url: str, save_root: Path, headless: bool = True) -> int:
    """
    Переходит на страницу, находит все PDF и скачивает их в папку,
    сформированную из последних 2 сегментов URL страницы.
    Возвращает количество успешно скачанных файлов.
    """
    # Формируем путь к папке
    folder_name = make_folder_name_from_url(page_url)
    target_dir = save_root / folder_name
    print(f"\n📁 Обработка: {page_url}")
    print(f"   → Папка: {target_dir}")
    
    pdf_urls = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            page.goto(page_url, wait_until="networkidle", timeout=30000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            
            # 🔍 Ищем все ссылки, ведущие на .pdf (через eval для скорости)
            raw_links = page.eval_on_selector_all('a', """
                links => links
                    .filter(a => {
                        const href = a.href?.toLowerCase();
                        return href?.endsWith('.pdf') || href?.includes('.pdf?');
                    })
                    .map(a => a.href)
            """)
            
            # Нормализуем и фильтруем
            seen = set()
            for href in raw_links:
                if href:
                    full_url = urljoin(page_url, href.strip()).split('#')[0]
                    parsed = urlparse(full_url.lower())
                    if parsed.path.endswith('.pdf') and full_url not in seen:
                        seen.add(full_url)
                        pdf_urls.append(full_url)
                        
        except Exception as e:
            print(f"   ⚠️ Ошибка загрузки страницы: {e}")
        finally:
            browser.close()
    
    if not pdf_urls:
        print("   ℹ️ PDF-файлы не найдены")
        return 0
    
    print(f"   📄 Найдено PDF: {len(pdf_urls)}")
    
    # 📥 Скачиваем
    success = 0
    for i, pdf_url in enumerate(pdf_urls, 1):
        prefix = f"{i:02d}_"
        if download_pdf(pdf_url, save_dir=target_dir, prefix=prefix):
            success += 1
        time.sleep(0.8)  # Вежливая пауза
    
    print(f"   🎯 Скачано: {success}/{len(pdf_urls)}")
    return success


# ==================== ГЛАВНЫЙ ПАЙПЛАЙН ====================

def run_pipeline(
    main_url: str,
    output_root: str = "psb_downloads",
    headless: bool = True,
    delay_between: float = 2.0
):
    """
    Запускает полный пайплайн:
    1. Извлекает ссылки "Подробнее"
    2. Для каждой — скачивает PDF в отдельную папку
    """
    print("🚀 Запуск пайплана PSBank PDF Downloader\n")
    
    # 1️⃣ Извлекаем ссылки
    detail_links = extract_podrobnee_links(main_url, headless=headless)
    if not detail_links:
        print("❌ Не найдено ссылок для обработки. Завершение.")
        return
    
    # 2️⃣ Обрабатываем каждую ссылку
    root_path = Path(output_root)
    root_path.mkdir(parents=True, exist_ok=True)
    
    total_downloaded = 0
    for idx, link in enumerate(detail_links, 1):
        print(f"\n{'='*60}")
        print(f"🔗 [{idx}/{len(detail_links)}] Обработка ссылки")
        print(f"{'='*60}")
        
        count = download_pdfs_from_page(link, save_root=root_path, headless=headless)
        total_downloaded += count
        
        if idx < len(detail_links):
            print(f"⏳ Пауза {delay_between} сек перед следующей...")
            time.sleep(delay_between)
    
    # 📊 Итоги
    print(f"\n{'='*60}")
    print(f"🏁 Пайплайн завершён!")
    print(f"📁 Все файлы сохранены в: {root_path.resolve()}")
    print(f"📥 Всего скачано PDF: {total_downloaded}")
    print(f"{'='*60}")


# ==================== ТОЧКА ВХОДА ====================

if __name__ == "__main__":
    # 🔧 НАСТРОЙКИ
    MAIN_URL = "https://www.psbank.ru/personal/cards?tab=drugiye-predlozheniya"
    OUTPUT_FOLDER = "psb_downloads"      # Корневая папка для всех загрузок
    HEADLESS = True                      # False — чтобы видеть браузер при отладке
    DELAY_BETWEEN_PAGES = 2.0            # Пауза между обработкой страниц (сек)
    
    # ▶️ ЗАПУСК
    run_pipeline(
        main_url=MAIN_URL,
        output_root=OUTPUT_FOLDER,
        headless=HEADLESS,
        delay_between=DELAY_BETWEEN_PAGES
    )