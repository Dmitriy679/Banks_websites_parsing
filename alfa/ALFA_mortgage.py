# mortgage_parser_alfabank.py
import re
import time
import random
import pandas as pd
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# === Исходная ссылка ===
URL = "https://alfabank.ru/get-money/mortgage/podbor/"

# === Генерация пути для сохранения (ОТНОСИТЕЛЬНО СКРИПТА) ===
def generate_output_path(url: str, base_folder: str = "alfa_downloads", extension: str = ".xlsx") -> str:
    """
    Генерирует путь для сохранения файла ОТНОСИТЕЛЬНО РАСПОЛОЖЕНИЯ СКРИПТА
    """
    # 🔥 Путь к папке со скриптом
    script_dir = Path(__file__).parent.resolve()
    
    # Парсим URL
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    
    # Берём последние 2 элемента
    if len(path_parts) >= 2:
        folder_name = path_parts[-2]
        file_name = path_parts[-1]
    elif len(path_parts) == 1:
        folder_name = path_parts[-1]
        file_name = "data"
    else:
        folder_name = "root"
        file_name = "data"
    
    # Очищаем от запрещённых символов
    folder_name = re.sub(r'[\\/*?:\[\]<>|]', '_', folder_name)
    file_name = re.sub(r'[\\/*?:\[\]<>|]', '_', file_name)
    
    # 🔥 Создаём папку внутри директории скрипта
    full_folder = script_dir / base_folder / folder_name
    full_folder.mkdir(parents=True, exist_ok=True)
    
    return str(full_folder / (file_name + extension))

# === Генерируем путь автоматически ===
OUTPUT_FILE = generate_output_path(URL)

# === Селекторы ===
TABLIST_SELECTOR = '[role="tablist"]'
TAB_SELECTOR = '[role="tab"]'
CONTENT_SELECTOR = '[data-widget-name="Block"]'
HEADER_SELECTOR = '[data-test-id="text"]'
LIST_ITEM_SELECTOR = 'li'

def random_delay(min_ms: float = 300, max_ms: float = 800):
    time.sleep(random.uniform(min_ms, max_ms) / 1000)

def safe_scroll(page, direction: str = "down", timeout: int = 5000) -> bool:
    for attempt in range(2):
        try:
            if direction == "down":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                page.evaluate("window.scrollTo(0, 0)")
            elif direction == "to":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.85)")
            return True
        except Exception as e:
            if "Execution context was destroyed" in str(e) and attempt == 0:
                print("   🔄 Контекст уничтожен, ждём...")
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout)
                    if direction == "down":
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    elif direction == "up":
                        page.evaluate("window.scrollTo(0, 0)")
                    elif direction == "to":
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.85)")
                    return True
                except:
                    return False
            else:
                print(f"   ⚠ Ошибка скролла: {e}")
                return False
    return False

def find_tablist_smart(page, max_scrolls: int = 8, scroll_step: int = 400) -> bool:
    print("🔍 Ищем меню вкладок...")
    if page.query_selector(TABLIST_SELECTOR):
        tabs = page.query_selector_all(TAB_SELECTOR)
        if tabs:
            print("✅ Меню найдено без скролла")
            return True
    
    max_scroll = page.evaluate("() => document.body.scrollHeight - window.innerHeight")
    for i in range(max_scrolls):
        scroll_pos = min((i + 1) * scroll_step, max_scroll)
        try:
            page.evaluate(f"window.scrollTo(0, {scroll_pos})")
        except Exception as e:
            if "Execution context was destroyed" in str(e):
                page.wait_for_load_state("networkidle", timeout=5000)
                page.evaluate(f"window.scrollTo(0, {scroll_pos})")
        random_delay(200, 400)
        if page.query_selector(TABLIST_SELECTOR):
            tabs = page.query_selector_all(TAB_SELECTOR)
            if tabs:
                page.evaluate(f"window.scrollTo(0, {max(0, scroll_pos - 250)})")
                random_delay(150, 300)
                print(f"✅ Меню найдено на позиции {scroll_pos}px")
                return True
    print("❌ Меню вкладок не найдено")
    return False

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text.replace('\xa0', ' ')

def get_panel_id_from_tab(tab) -> str:
    controls_id = tab.get_attribute('aria-controls')
    if controls_id:
        return controls_id
    test_id = tab.get_attribute('data-test-id')
    if test_id:
        panel_id = test_id.replace('TabsHeader-', '').replace('-title', '')
        if panel_id and panel_id != test_id:
            return panel_id
    tab_id = tab.get_attribute('id')
    if tab_id and not tab_id.endswith('-title'):
        return tab_id
    return None

def extract_mixed_text_content(page, element) -> list:
    """Обрабатывает элементы со смешанным текстом (жирный + обычный в одном теге)"""
    results = []
    
    try:
        children_info = element.evaluate("""el => {
            const computed = window.getComputedStyle(el);
            const parentWeight = parseInt(computed.fontWeight);
            const parentText = el.textContent.trim();
            
            const children = [];
            for (let child of el.childNodes) {
                if (child.nodeType === 3) {
                    const text = child.textContent.trim();
                    if (text) {
                        children.push({
                            type: 'text',
                            text: text,
                            isBold: parentWeight >= 600
                        });
                    }
                } else if (child.nodeType === 1) {
                    const style = window.getComputedStyle(child);
                    const weight = parseInt(style.fontWeight);
                    const text = child.textContent.trim();
                    if (text) {
                        children.push({
                            type: 'element',
                            text: text,
                            isBold: weight >= 600,
                            tag: child.tagName.toLowerCase()
                        });
                    }
                }
            }
            
            return {
                parentText: parentText,
                parentIsBold: parentWeight >= 600,
                children: children
            };
        }""")
        
        parent_text = children_info['parentText']
        parent_is_bold = children_info['parentIsBold']
        children = children_info['children']
        
        if len(children) > 0:
            bold_parts = [c['text'] for c in children if c['isBold']]
            normal_parts = [c['text'] for c in children if not c['isBold']]
            
            if bold_parts and normal_parts:
                header = ' '.join(bold_parts).rstrip(':').rstrip()
                content = ' '.join(normal_parts)
                if header and content:
                    results.append((header, content))
            elif bold_parts and not normal_parts:
                header = ' '.join(bold_parts)
                if header:
                    results.append((header, None))
            elif normal_parts and not bold_parts:
                content = ' '.join(normal_parts)
                if content:
                    results.append((None, content))
        else:
            if parent_is_bold:
                results.append((parent_text, None))
            else:
                results.append((None, parent_text))
    
    except Exception:
        text = clean_text(element.text_content())
        if text:
            results.append((None, text))
    
    return results

def extract_content_from_tab(page, tab) -> list:
    """Извлекает контент с обработкой смешанного текста и удалением дублей"""
    data = []
    
    panel_id = get_panel_id_from_tab(tab)
    panel = None
    
    if panel_id:
        selectors = [f'#{panel_id}', f'[data-test-id="{panel_id}"]']
        for selector in selectors:
            try:
                panel = page.wait_for_selector(selector, timeout=8000, state='visible')
                if panel:
                    print(f"   🔍 Панель найдена по: {selector}")
                    break
            except:
                continue
    
    if not panel or not panel.is_visible():
        print(f"   ⚠️ Панель не найдена, пробуем видимые блоки")
        blocks = page.query_selector_all(f'{CONTENT_SELECTOR}:visible')
    else:
        blocks = panel.query_selector_all(CONTENT_SELECTOR)
        blocks = [b for b in blocks if b.is_visible()]
    
    if not blocks:
        return [["Нет данных", ""]]
    
    def is_leaf_element(el):
        """Проверяет, что элемент не содержит других блочных элементов с текстом"""
        try:
            has_children = el.evaluate("""el => {
                const blockTags = ['P', 'LI', 'DIV', 'SPAN'];
                for (let child of el.children) {
                    if (blockTags.includes(child.tagName)) {
                        if (child.textContent.trim().length > 0) {
                            return true;
                        }
                    }
                }
                return false;
            }""")
            return not has_children
        except:
            return True
    
    current_header = None
    
    for block in blocks:
        all_elements = block.query_selector_all('h1, h2, h3, h4, h5, h6, p, li, div, span')
        
        leaf_elements = [el for el in all_elements if is_leaf_element(el)]
        if not leaf_elements:
            leaf_elements = block.query_selector_all('p, li')
        
        for el in leaf_elements:
            text = clean_text(el.text_content())
            
            if not text or text in ['•', '-', '*', '']:
                continue
            
            mixed_results = extract_mixed_text_content(page, el)
            
            has_valid_results = False
            if mixed_results:
                for header_part, content_part in mixed_results:
                    if header_part or content_part:
                        has_valid_results = True
                        break
            
            if has_valid_results:
                for header_part, content_part in mixed_results:
                    if header_part is not None and content_part is not None:
                        data.append([header_part, content_part])
                        current_header = header_part
                    elif header_part is not None and content_part is None:
                        current_header = header_part
                    elif header_part is None and content_part is not None:
                        if current_header:
                            content_part = re.sub(r'^[•\-\*]\s*', '', content_part)
                            if content_part:
                                data.append([current_header, content_part])
                continue
            
            try:
                is_bold = el.evaluate("""el => {
                    const computed = window.getComputedStyle(el);
                    return parseInt(computed.fontWeight) >= 600;
                }""")
                
                if is_bold:
                    current_header = text
                else:
                    if current_header:
                        text = re.sub(r'^[•\-\*]\s*', '', text)
                        if text:
                            data.append([current_header, text])
            except:
                pass
    
    # Удаление дубликатов
    if data:
        unique_data = []
        seen = set()
        for row in data:
            row_tuple = (row[0], row[1])
            if row_tuple not in seen:
                seen.add(row_tuple)
                unique_data.append(row)
        
        print(f"   🧹 Удалено дубликатов: {len(data) - len(unique_data)}")
        data = unique_data
    
    # Фоллбэк
    if not data:
        print("   ⚠️ Не найдено элементов, пробуем резервный метод")
        for block in blocks:
            headers = block.query_selector_all(HEADER_SELECTOR)
            for header in headers:
                header_text = clean_text(header.text_content())
                if not header_text:
                    continue
                next_el = header.evaluate_handle('el => el.nextElementSibling')
                if next_el:
                    try:
                        next_tag = next_el.evaluate('el => el.tagName?.toLowerCase()')
                        if next_tag == 'ul':
                            items = next_el.query_selector_all(LIST_ITEM_SELECTOR)
                            for item in items:
                                p = item.query_selector('p')
                                if p:
                                    item_text = clean_text(p.text_content())
                                    if item_text:
                                        item_text = re.sub(r'^[•\-\*]\s*', '', item_text)
                                        data.append([header_text, item_text])
                    except Exception as e:
                        if "Execution context was destroyed" not in str(e):
                            print(f"⚠️ Ошибка извлечения: {e}")
        
        if data:
            unique_data = []
            seen = set()
            for row in data:
                row_tuple = (row[0], row[1])
                if row_tuple not in seen:
                    seen.add(row_tuple)
                    unique_data.append(row)
            data = unique_data

    return data if data else [["Нет данных", ""]]

def get_tab_name(tab) -> str:
    test_id = tab.get_attribute('data-test-id')
    if test_id:
        name = test_id.replace('TabsHeader-', '').replace('-title', '')
        name = name.replace('_', ' ').title()
    else:
        name = clean_text(tab.text_content())
    name = re.sub(r'[\\/*?:\[\]]', '', name).strip()[:31]
    return name if name else "Вкладка"

def should_skip_tab(tab_name: str) -> bool:
    if tab_name.startswith('Tabs-List'):
        return True
    if re.match(r'^Tabs-List-Tabtitle-\d+$', tab_name, re.IGNORECASE):
        return True
    return False

def save_to_excel(data_dict: dict, filename: str):
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        used = set()
        for sheet_name, rows in data_dict.items():
            if should_skip_tab(sheet_name):
                print(f"   ⏭️ Пропущена служебная вкладка: {sheet_name}")
                continue
            
            safe = re.sub(r'[\\/*?:\[\]]', '', sheet_name).strip()[:31]
            base = safe
            cnt = 1
            while safe in used:
                safe = f"{base}_{cnt}"[:31]
                cnt += 1
            used.add(safe)
            df = pd.DataFrame(rows, columns=['Заголовок', 'Содержание'])
            df.to_excel(writer, sheet_name=safe, index=False)
            print(f"📄 {safe}: {len(rows)} строк")
    print(f"\n✅ Сохранено: {filename}")

def main():
    print("🚀 Запуск парсера Альфа-Банк (ипотека)")
    print(f"📁 Путь сохранения: {OUTPUT_FILE}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
            timezone_id='Europe/Moscow',
            extra_http_headers={'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'}
        )
        page = context.new_page()
        
        print(f"🌐 Открываем {URL}")
        try:
            response = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            if response and response.url != URL:
                print(f"🔄 Редирект: {URL} → {response.url}")
            page.wait_for_load_state('networkidle', timeout=30000)
        except PlaywrightTimeout:
            print("⚠️ Таймаут загрузки, продолжаем...")
        
        random_delay(1500, 2500)
        safe_scroll(page, "to")
        random_delay(1000, 2000)
        safe_scroll(page, "up")
        random_delay(800, 1500)
        
        if not find_tablist_smart(page):
            print("❌ Не найдено меню вкладок")
            browser.close()
            return
        
        tabs = page.query_selector_all(TAB_SELECTOR)
        print(f"📑 Найдено вкладок: {len(tabs)}")
        if not tabs:
            browser.close()
            return
        
        results = {}
        
        for i, tab in enumerate(tabs):
            tab_name = get_tab_name(tab)
            
            if should_skip_tab(tab_name):
                print(f"\n[{i+1}/{len(tabs)}] ⏭️ '{tab_name}' — пропущена (служебная)")
                continue
            
            is_selected = tab.get_attribute('aria-selected') == 'true'
            panel_id = get_panel_id_from_tab(tab)
            
            print(f"\n[{i+1}/{len(tabs)}] 🗂️ '{tab_name}' (активна: {is_selected}, панель: '{panel_id}')")
            
            if not is_selected:
                try:
                    tab.scroll_into_view_if_needed(timeout=5000)
                    random_delay(200, 400)
                    tab.click(timeout=10000)
                    page.wait_for_load_state('networkidle', timeout=15000)
                    random_delay(800, 1500)
                except PlaywrightTimeout as e:
                    print(f"⚠️ Таймаут переключения: {e}")
                    results[tab_name] = [["Ошибка переключения", ""]]
                    continue
                except Exception as e:
                    if "Execution context was destroyed" in str(e):
                        print("🔄 Контекст уничтожен, ждём...")
                        page.wait_for_load_state('networkidle', timeout=10000)
                        random_delay(500, 1000)
                    else:
                        print(f"⚠️ Ошибка: {e}")
                        results[tab_name] = [["Ошибка", str(e)[:100]]]
                        continue
            
            content = extract_content_from_tab(page, tab)
            results[tab_name] = content
            print(f"✅ Извлечено: {len(content)} строк (после удаления дублей)")
            random_delay(600, 1200)
        
        if results:
            save_to_excel(results, OUTPUT_FILE)
        else:
            print("❌ Нет данных для сохранения")
        
        browser.close()
        print("\n🎉 Парсинг завершён!")

if __name__ == "__main__":
    main()