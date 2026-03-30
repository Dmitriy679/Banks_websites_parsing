#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единый пайплайн для скачивания PDF:
1. Извлекает ссылки с кнопок "Подробнее" с главной страницы
2. Для каждой ссылки: находит и скачивает все PDF в папку,
   названную по последним 2 сегментам URL
3. Все папки группируются внутри подпапки, имя которой берётся
   из последнего сегмента главной ссылки
"""

import os
import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright


def make_folder_name_from_url(url: str, segments: int = 2) -> str:
    """Создаёт имя папки из последних N сегментов пути URL"""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return 'misc'
    selected = path_parts[-segments:] if len(path_parts) >= segments else path_parts
    safe_parts = [re.sub(r'[^\w\-]', '_', unquote(p)) for p in selected]
    return '_'.join(safe_parts) if safe_parts else 'misc'


def sanitize_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов"""
    return re.sub(r'[<>:"/\\|?*]', '_', filename).strip()


def download_pdf(url: str, save_dir: Path, prefix: str = "") -> bool:
    """Скачивает PDF и сохраняет в указанную папку"""
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    raw_name = url.split("/")[-1].split("?")[0]
    if not raw_name or "." not in raw_name.lower():
        raw_name = f"document_{uuid.uuid4().hex[:8]}.pdf"
    
    filename = sanitize_filename(f"{prefix}{raw_name}")
    
    if any(kw in filename.lower() for kw in ["_ios_","pamyatka","usloviya","dogovor", "rules", "bankform", "ru.pdf", "troubleshooting-time"]):
        print(f"   Пропущено: {filename}")
        return True
    
    final_path = save_dir / filename
    if final_path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        unique_id = uuid.uuid4().hex[:6]
        final_path = save_dir / f"{stem}_{unique_id}{suffix}"
    
    save_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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
        print(f"   Ошибка: {type(e).__name__}: {e}")
        return False


def extract_podrobnee_links(main_url: str, headless: bool = True) -> List[str]:
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        
        try:
            print(f"Парсинг главной страницы: {main_url}")
            page.goto(main_url, wait_until="domcontentloaded", timeout=60000)
            
            # Ждем появления элементов, а не просто таймаут
            try:
                page.wait_for_selector("text=/подробнее/i", timeout=10000)
            except:
                print("Элементы 'Подробнее' не найдены через wait_for_selector")
            
            page.wait_for_timeout(3000) # Небольшая задержка для JS рендера
            
            # Скролл для подгрузки lazy-content
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            
            # Ищем все элементы с текстом
            elements = page.locator("text=/подробнее/i").all()
            print(f"Найдено элементов с текстом 'Подробнее': {len(elements)}")
            
            for i, el in enumerate(elements):
                if not el.is_visible():
                    continue
                
                try:
                    # Расширенный JS для поиска ссылки
                    href = el.evaluate("""
                        (el) => {
                            // 1. Проверка самого элемента
                            if (el.tagName.toLowerCase() === 'a' && el.href) return el.href;
                            if (el.getAttribute('href')) return el.getAttribute('href');
                            
                            // 2. Проверка популярных data-атрибутов
                            const dataAttrs = ['data-url', 'data-href', 'data-link', 'to', 'href'];
                            for (let attr of dataAttrs) {
                                const val = el.getAttribute(attr);
                                if (val) return val;
                            }

                            // 3. Поднимаемся вверх по дереву (до 5 уровней)
                            let parent = el.parentElement;
                            let depth = 0;
                            while (parent && depth < 5) {
                                if (parent.tagName.toLowerCase() === 'a' && parent.href) return parent.href;
                                
                                // Проверяем data-атрибуты у родителей
                                for (let attr of dataAttrs) {
                                    const val = parent.getAttribute(attr);
                                    if (val) return val;
                                }
                                
                                // Часто ссылка на карточке с ролью button или link
                                if (parent.getAttribute('role') === 'button' || parent.getAttribute('role') === 'link') {
                                     if (parent.href) return parent.href;
                                }

                                parent = parent.parentElement;
                                depth++;
                            }
                            return null;
                        }
                    """)
                    
                    if href and isinstance(href, str):
                        # Если ссылка относительная, делаем абсолютной
                        if href.startswith('/'):
                            from urllib.parse import urljoin
                            href = urljoin(main_url, href)
                        
                        clean_href = href.split('#')[0].strip()
                        
                        # 🔥 НОВОЕ УСЛОВИЕ: Пропускаем ссылки с package_premium
                        if 'package/premium' in clean_href.lower():
                            print(f"   [✕] Пропущено (package/premium): {clean_href}")
                            continue  # Переходим к следующей ссылке
                        # 🔥 КОНЕЦ НОВОГО УСЛОВИЯ
                        
                        # Фильтр домена (оставил ваш, но можно сделать параметром)
                        if 'alfabank.ru' in clean_href and clean_href not in results:
                            results.append(clean_href)
                            print(f"   [+] Найдена ссылка: {clean_href}")
                        else:
                            # ОТЛАДКА: Выводим, что нашли, но отфильтровали
                            if href.startswith('http'):
                                print(f"   [-] Ссылка найдена, но не прошла фильтр домена: {clean_href}")
                            else:
                                print(f"   [?] Найдено что-то похожее на ссылку, но формат странный: {href}")
                                
                except Exception as e:
                    # ОТЛАДКА: Выводим HTML элемента, на котором упали
                    outer_html = el.evaluate("el => el.outerHTML")
                    print(f"   [!] Ошибка обработки элемента: {e}")
                    print(f"       HTML: {outer_html[:100]}...")
                    continue
                    
        except Exception as e:
            print(f"Критическая ошибка при парсинге: {e}")
        finally:
            browser.close()
    
    print(f"\nВсего уникальных подходящих ссылок: {len(results)}")
    return results

def download_pdfs_from_page(page_url: str, save_root: Path, headless: bool = True, base_subfolder: str = None) -> int:
    folder_name = make_folder_name_from_url(page_url, segments=2)
    
    if base_subfolder:
        target_dir = save_root / base_subfolder / folder_name
    else:
        target_dir = save_root / folder_name
        
    print(f"\nОбработка: {page_url}")
    print(f"   Папка: {target_dir}")
    
    pdf_urls = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        
        # 🔧 ИСПРАВЛЕНО: Добавляем логирование навигации для отладки
        page.on("framenavigated", lambda frame: print(f""))
        
        # Перехват событий network для поиска PDF
        pdf_from_network = set()
        def handle_response(response):
            try:
                url = response.url.lower()
                if '.pdf' in url or response.headers.get('content-type', '').lower() == 'application/pdf':
                    pdf_from_network.add(response.url.split('#')[0])
            except:
                pass
        
        page.on("response", handle_response)
        
        try:
            # 🔧 ИСПРАВЛЕНО: wait_until="networkidle" + увеличенный таймаут
            print(f"   Загрузка страницы...")
            response = page.goto(page_url, wait_until="networkidle", timeout=60000)
            
            # 🔧 ИСПРАВЛЕНО: Проверяем редиректы
            if response and response.url != page_url:
                print(f"   🔄 Редирект: {page_url} → {response.url}")
                page_url = response.url  # Обновляем URL для дальнейшей работы
            
            # 🔧 ИСПРАВЛЕНО: Безопасная функция скролла с повторной попыткой
            def safe_scroll(page, timeout=5000):
                for attempt in range(2):
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        return True
                    except Exception as e:
                        if "Execution context was destroyed" in str(e) and attempt == 0:
                            print("   🔄 Контекст уничтожен, ждём завершения навигации...")
                            try:
                                page.wait_for_load_state("networkidle", timeout=timeout)
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                return True
                            except:
                                return False
                        else:
                            raise
                return False
            
            # 🔧 ИСПРАВЛЕНО: Используем безопасный скролл вместо прямого evaluate
            page.wait_for_timeout(2000)
            safe_scroll(page)
            page.wait_for_timeout(2000)
            safe_scroll(page)  # Скролл вверх тоже через безопасную функцию
            page.wait_for_timeout(1000)
            
            # 1. Ищем в тегах <a> (стандарт) - оборачиваем в защиту
            try:
                raw_links = page.eval_on_selector_all('a', """
                    links => links
                        .filter(a => {
                            const href = a.href?.toLowerCase();
                            return href?.endsWith('.pdf') || href?.includes('.pdf?');
                        })
                        .map(a => a.href)
                """)
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    print("   ⚠ Контекст уничтожен при поиске <a>, пробуем ещё раз...")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    raw_links = page.eval_on_selector_all('a', """
                        links => links
                            .filter(a => {
                                const href = a.href?.toLowerCase();
                                return href?.endsWith('.pdf') || href?.includes('.pdf?');
                            })
                            .map(a => a.href)
                    """)
                else:
                    raise
            
            # 2. Ищем в data-атрибутах (расширенный поиск) - тоже с защитой
            try:
                data_links = page.eval_on_selector_all('[data-url], [data-href], [data-file], [data-src]', """
                    elements => elements
                        .map(el => {
                            const attrs = ['data-url', 'data-href', 'data-file', 'data-src'];
                            for (let attr of attrs) {
                                const val = el.getAttribute(attr);
                                if (val && val.toLowerCase().includes('.pdf')) {
                                    return val;
                                }
                            }
                            return null;
                        })
                        .filter(val => val !== null)
                """)
            except Exception as e:
                if "Execution context was destroyed" in str(e):
                    print("   ⚠ Контекст уничтожен при поиске data-атрибутов, пропускаем...")
                    data_links = []
                else:
                    raise
            
            # 3. Ищем элементы с текстом "PDF" или "Скачать"
            text_elements = page.locator("text=/pdf|скачать|download/i").all()
            for el in text_elements[:20]:
                try:
                    if not el.is_visible():
                        continue
                    link_info = el.evaluate("""
                        (el) => {
                            let parent = el;
                            for (let i = 0; i < 5; i++) {
                                if (!parent) break;
                                if (parent.href) return parent.href;
                                const attrs = ['data-url', 'data-href', 'onclick'];
                                for (let attr of attrs) {
                                    const val = parent.getAttribute(attr);
                                    if (val && val.toLowerCase().includes('.pdf')) return val;
                                }
                                parent = parent.parentElement;
                            }
                            return null;
                        }
                    """)
                    if link_info and '.pdf' in link_info.lower():
                        raw_links.append(link_info)
                except Exception as e:
                    if "Execution context was destroyed" not in str(e):
                        print(f"   [!] Ошибка при обработке элемента: {e}")
                    continue
            
            # Объединяем результаты
            all_hrefs = list(raw_links) + list(data_links) + list(pdf_from_network)
            
            seen = set()
            for href in all_hrefs:
                if not href:
                    continue
                try:
                    full_url = urljoin(page_url, href.strip()).split('#')[0]
                    parsed = urlparse(full_url.lower())
                    
                    is_pdf = parsed.path.endswith('.pdf') or '.pdf?' in full_url.lower()
                    
                    if is_pdf and full_url not in seen:
                        seen.add(full_url)
                        pdf_urls.append(full_url)
                        print(f"   [+] Найдено PDF: {full_url}")
                except Exception as e:
                    print(f"   [!] Ошибка парсинга ссылки {href}: {e}")
            
            # Если в DOM ничего нет, но сеть перехватила PDF
            if not pdf_urls and pdf_from_network:
                print("   [i] В DOM ссылок нет, но найдено в сетевых запросах")
                for url in pdf_from_network:
                    if url not in seen:
                        pdf_urls.append(url)
                        print(f"   [+] Из сети: {url}")
                        
        except Exception as e:
            print(f"Ошибка загрузки страницы: {e}")
            # 🔧 ИСПРАВЛЕНО: Делаем скриншот для отладки в headless-режиме
            if headless:
                try:
                    page.screenshot(path=f"debug_error_{int(time.time())}.png", full_page=True)
                    print(f"   📸 Скриншот сохранён: debug_error_{int(time.time())}.png")
                except:
                    pass
            import traceback
            traceback.print_exc()
        finally:
            browser.close()
    
    if not pdf_urls:
        print("   PDF-файлы не найдены")
        return 0
    
    print(f"\nВсего найдено PDF: {len(pdf_urls)}")
    
    success = 0
    for i, pdf_url in enumerate(pdf_urls, 1):
        prefix = f"{i:02d}_"
        if download_pdf(pdf_url, save_dir=target_dir, prefix=prefix):
            success += 1
        time.sleep(0.8)
    
    print(f"Скачано: {success}/{len(pdf_urls)}")
    return success


def run_pipeline(
    main_url: str,
    output_root: str = "alfa_downloads",
    headless: bool = True,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    base_subfolder: str = None
):
    """
    Запускает полный пайплайн:
    1. Извлекает ссылки "Подробнее"
    2. Для каждой — скачивает PDF в папку (имя из 2 последних сегментов URL)
    3. Если указан base_subfolder, все папки создаются внутри него
    Задержка между переходами: случайная от min_delay до max_delay секунд
    """
    print("Запуск пайплана ALFAbank PDF Downloader\n")
    
    detail_links = extract_podrobnee_links(main_url, headless=headless)
    if not detail_links:
        print("Не найдено ссылок для обработки. Завершение.")
        return
    
    root_path = Path(output_root)
    root_path.mkdir(parents=True, exist_ok=True)
    
    total_downloaded = 0
    for idx, link in enumerate(detail_links, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(detail_links)}] Обработка ссылки")
        print(f"{'='*60}")
        
        count = download_pdfs_from_page(
            link, 
            save_root=root_path, 
            headless=headless,
            base_subfolder=base_subfolder
        )
        total_downloaded += count
        
        if idx < len(detail_links):
            delay = random.uniform(min_delay, max_delay)
            print(f"Пауза {delay:.1f} сек перед следующей...")
            time.sleep(delay)
    
    print(f"\n{'='*60}")
    print(f"Все файлы сохранены в: {root_path.resolve()}")
    print(f"Всего скачано PDF: {total_downloaded}")
    print(f"{'='*60}")


if __name__ == "__main__":
    # 1. Вычисляем абсолютный путь к папке со скриптом
    # __file__ — путь к файлу скрипта, .parent — его папка
    script_dir = Path(__file__).resolve().parent
    
    # 2. Формируем полный путь к папке загрузок, присоединяя его к пути скрипта
    OUTPUT_FOLDER = script_dir / "alfa_downloads"
    
    # Остальные настройки
    URLS = [

        #"https://alfabank.ru/mobile/",
        #"https://alfabank.ru/get-money/",
        "https://alfabank.ru/make-money/",
        "https://alfabank.ru/everyday/debit-cards/",                       
    ]    
    HEADLESS = False
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0

    for url in URLS:
        # Имя подпапки берём из последнего сегмента главной ссылки
        subfolder = make_folder_name_from_url(url, segments=1)
        print(f"\n{'#'*60}")
        print(f"Обработка группы: {subfolder}")
        print(f"{'#'*60}\n")
        
        run_pipeline(
            main_url=url,
            output_root=OUTPUT_FOLDER,  # ← Теперь здесь абсолютный путь
            headless=HEADLESS,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            base_subfolder=subfolder
        )
        # Пауза между разными главными страницами
        if url != URLS[-1]:
            time.sleep(random.uniform(1.0, 3.0))