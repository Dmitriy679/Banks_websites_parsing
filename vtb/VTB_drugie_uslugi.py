# vtb_parser.py
import os
import re
import pandas as pd
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

def get_last_url_part(url: str) -> str:
    """Извлекает последнюю часть ссылки после последнего '/'"""
    # Убираем конечный слэш и дробим
    cleaned = url.rstrip('/')
    last_part = cleaned.split('/')[-1]
    # Очищаем от недопустимых символов для имени файла
    return re.sub(r'[<>:"/\\|?*]', '_', last_part)

def parse_vtb_cards(page):
    """Парсит карточки с страницы и возвращает список словарей"""
    cards = []
    
    # Ждем загрузки основного контента
    page.wait_for_load_state('networkidle')
    
    # Ищем все карточки по характерному классу-родителю
    card_elements = page.locator('div.card-mediumstyles__ParentGroupStyled-card-base__sc-senydt-1').all()
    
    for card in card_elements:
        try:
            # Извлекаем заголовок
            title = card.locator('p.typographystyles__Box-foundation-kit__sc-14qzghz-0').first.text_content().strip()
            
            # Извлекаем описание из markdown-блока
            description = card.locator('div.markdown-paragraphstyles__ParagraphTypography-foundation-kit__sc-otngat-0').first.text_content().strip()
            
            # Извлекаем ссылку из кнопки "Подробнее"
            link_element = card.locator('a.buttonstyles__LinkBox-foundation-kit__sc-sa2uer-1').first
            href = link_element.get_attribute('href')
            
            # Приводим ссылку к абсолютному виду, если она относительная
            if href and not href.startswith('http'):
                href = f"https://www.vtb.ru{href}"
            
            if title and description and href:
                cards.append({
                    'Название': title,
                    'Краткое описание': description,
                    'Ссылка': href
                })
        except Exception as e:
            # Пропускаем карточки, которые не удалось распарсить
            print(f"⚠️ Ошибка при парсинге карточки: {e}")
            continue
    
    return cards

def save_to_excel(data: list, base_path: Path, url_suffix: str):
    """Сохраняет данные в Excel файл по указанному пути"""
    # Формируем путь: ./vtb_downloads/{url_part}/data.xlsx
    output_dir = base_path / 'vtb_downloads' / url_suffix
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / 'drugie_uslugi.xlsx'
    
    df = pd.DataFrame(data)
    df.to_excel(output_file, index=False, engine='openpyxl')
    
    return output_file

def main():
    url = 'https://www.vtb.ru/personal/drugie-uslugi/'
    
    # Путь к директории со скриптом
    script_dir = Path(__file__).parent.resolve()
    
    with sync_playwright() as p:
        # Запускаем браузер (headless=True для работы без GUI)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        print(f"🔄 Загружаем страницу: {url}")
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            
            # Небольшая пауза для подгрузки динамического контента
            page.wait_for_timeout(2000)
            
        except PlaywrightTimeout:
            print("⚠️ Таймаут при загрузке страницы, пробуем продолжить...")
        
        print("🔍 Парсим карточки...")
        cards = parse_vtb_cards(page)
        browser.close()
    
    if not cards:
        print("❌ Не найдено ни одной карточки для парсинга")
        return
    
    print(f"✅ Найдено карточек: {len(cards)}")
    
    # Формируем имя папки на основе URL
    url_suffix = get_last_url_part(url)
    
    # Сохраняем в Excel
    output_path = save_to_excel(cards, script_dir, url_suffix)
    
    print(f"💾 Данные сохранены в файл: {output_path}")
    print("\n📋 Пример данных:")
    for i, card in enumerate(cards[:3], 1):
        print(f"{i}. {card['Название']} — {card['Краткое описание'][:50]}...")

if __name__ == '__main__':
    main()