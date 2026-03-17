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


def download_pdf(url: str, save_dir: Path, prefix: str = "", skip_keywords: List[str] = None) -> bool:
    """Скачивает PDF и сохраняет в указанную папку с фильтрацией по ключевым словам"""
    if skip_keywords is None:
        skip_keywords = ["polozhenie", "положение", "оферта"]  # можно расширять
    
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    
    # 🔍 Фильтр по URL ДО запроса (экономим трафик)
    if any(kw in url.lower() for kw in skip_keywords):
        print(f"   ⏭ Пропущено по ключевому слову в URL: {url}")
        return True
    
    # Извлекаем имя файла из URL
    raw_name = url.split("/")[-1].split("?")[0]
    if not raw_name or "." not in raw_name.lower():
        raw_name = f"document_{uuid.uuid4().hex[:8]}.pdf"
    
    filename = sanitize_filename(f"{prefix}{raw_name}")
    
    # 🔍 Фильтр по имени файла
    if any(kw in filename.lower() for kw in skip_keywords):
        print(f"   ⏭ Пропущено по ключевому слову в имени: {filename}")
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
        
        # 🔍 Фильтр по заголовку Content-Disposition (если сервер присылает имя)
        content_disp = resp.headers.get('content-disposition', '')
        if 'filename=' in content_disp:
            import re
            match = re.search(r'filename\*?=?["\']?([^;"\']+)', content_disp)
            if match:
                server_filename = unquote(match.group(1)).lower()
                if any(kw in server_filename for kw in skip_keywords):
                    print(f"   ⏭ Пропущено по имени с сервера: {server_filename}")
                    return True
        
        # 🔍 Финальная проверка Content-Type
        content_type = resp.headers.get('content-type', '').lower()
        if 'application/pdf' not in content_type:
            print(f"   ⚠ Не PDF, пропущено: {content_type}")
            return True
        
        with open(final_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        size_kb = final_path.stat().st_size / 1024
        print(f"   ✓ {final_path.name} ({size_kb:.1f} КБ)")
        return True
        
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print(f"   ✗ 404: {url}")
        else:
            print(f"   ✗ HTTP ошибка: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Ошибка: {type(e).__name__}: {e}")
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
                        if 'vtb.ru' in clean_href and clean_href not in results:
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
    """Находит PDF на странице и скачивает их через download_pdf (с фильтрами)"""
    page_url = page_url.strip()
    
    folder_name = make_folder_name_from_url(page_url, segments=2)
    target_dir = save_root / base_subfolder / folder_name if base_subfolder else save_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nОбработка: {page_url}")
    print(f"   Папка: {target_dir}")
    
    pdf_urls = set()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # Перехват сетевых ответов
        def handle_response(response):
            url = response.url.split('#')[0]
            content_type = response.headers.get('content-type', '').lower()
            if url.lower().endswith('.pdf') or 'application/pdf' in content_type:
                pdf_urls.add(url)
                print(f"   [+] Сеть: {url}")
        
        page.on("response", handle_response)
        
        try:
            print("   Загрузка страницы...")
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("body", timeout=10000)
            
            # Скролл для ленивой загрузки
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            
            # Поиск ссылок <a> с .pdf
            pdf_links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.toLowerCase().includes('.pdf'));
            }""")
            
            for href in pdf_links:
                full_url = urljoin(page_url, href).split('#')[0]
                if full_url.lower().endswith('.pdf'):
                    pdf_urls.add(full_url)
                    print(f"   [+] DOM: {full_url}")
            
            # Поиск в data-атрибутах
            data_links = page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('[data-url], [data-href], [data-file]').forEach(el => {
                    ['data-url', 'data-href', 'data-file'].forEach(attr => {
                        const val = el.getAttribute(attr);
                        if (val && val.toLowerCase().includes('.pdf')) {
                            results.push(val);
                        }
                    });
                });
                return results;
            }""")
            
            for href in data_links:
                full_url = urljoin(page_url, href).split('#')[0]
                if full_url.lower().endswith('.pdf'):
                    pdf_urls.add(full_url)
                    print(f"   [+] Data-attr: {full_url}")
                    
        except Exception as e:
            print(f"⚠ Ошибка: {e}")
            if headless:
                try:
                    page.screenshot(path=f"debug_{int(time.time())}.png", full_page=True)
                    print("   📸 Скриншот сохранён")
                except:
                    pass
        finally:
            browser.close()
    
    # === Скачивание через download_pdf (с фильтрами!) ===
    if not pdf_urls:
        print("   PDF не найдены")
        return 0
    
    print(f"\nВсего найдено: {len(pdf_urls)}")
    success = 0
    
    for i, pdf_url in enumerate(pdf_urls, 1):
        prefix = f"{i:02d}_"
        if download_pdf(pdf_url, save_dir=target_dir, prefix=prefix):
            success += 1
        time.sleep(0.5)
    
    print(f"Итог: {success}/{len(pdf_urls)}")
    return success


def run_pipeline(
    main_url: str,
    output_root: str = "vtb_downloads",
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
    OUTPUT_FOLDER = script_dir / "vtb_downloads"
    
    # Остальные настройки
    URLS = [
        "https://www.vtb.ru/personal/ipoteka/",
        #"https://www.vtb.ru/personal/vklady-i-scheta/",                  
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