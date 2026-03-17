#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсинг карточек VTB: ссылка «Подробнее» + описание выше кнопки
"""

import json
import time
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright


def parse_cards(page, main_url: str):
    """
    Извлекает карточки:
    - ссылка из кнопки «Подробнее»
    - текст описания выше кнопки
    """
    cards = []
    
    # 🔍 Находим все кнопки «Подробнее»
    more_buttons = page.locator("a:has-text('Подробнее')").all()
    
    for btn in more_buttons:
        try:
            if not btn.is_visible():
                continue
            
            # 🔹 1. Ссылка из кнопки «Подробнее»
            detail_href = btn.get_attribute("href")
            if detail_href:
                if detail_href.startswith('/'):
                    detail_href = urljoin(main_url, detail_href)
                detail_href = detail_href.split('#')[0].strip()
            else:
                continue  # нет ссылки — пропускаем карточку
            
            # 🔹 2. Поднимаемся к контейнеру карточки (3-4 уровня вверх)
            card_container = btn
            for _ in range(4):
                card_container = card_container.locator("..")
            
            # 🔹 3. Ищем описание выше кнопки
            # Вариант A: в блоке с классом markdown
            description = None
            try:
                markdown_block = card_container.locator('[class*="markdown"]').first
                if markdown_block.is_visible():
                    description = markdown_block.text_content().strip()
            except:
                pass
            
            # Вариант B: если markdown не найден — берём текст из <p> или <div> выше кнопки
            if not description:
                try:
                    # Ищем все текстовые элементы внутри карточки
                    all_texts = card_container.evaluate("""el => {
                        const texts = [];
                        el.querySelectorAll('p, div, span').forEach(node => {
                            const txt = node.textContent.trim();
                            // Фильтр: не пустой, не слишком длинный, не кнопка
                            if (txt && txt.length > 10 && txt.length < 300) {
                                const lower = txt.toLowerCase();
                                if (!lower.includes('подробнее') && 
                                    !lower.includes('перейти') && 
                                    !lower.includes('втб онлайн')) {
                                    texts.push(txt);
                                }
                            }
                        });
                        return texts;
                    }""")
                    
                    # Обычно описание — второй по счёту текст (первый — заголовок)
                    if len(all_texts) >= 1:
                        description = all_texts[0]  # или all_texts[1] если есть заголовок
                except:
                    pass
            
            # 🔹 4. Заголовок (опционально)
            title = None
            try:
                title_el = card_container.locator("p").first
                if title_el.is_visible():
                    title_text = title_el.text_content().strip()
                    if len(title_text) < 100:  # защита от ложных заголовков
                        title = title_text
            except:
                pass
            
            # 🔹 5. Остальные кнопки в карточке (опционально)
            other_buttons = []
            all_links = card_container.locator("a").all()
            for link in all_links:
                try:
                    link_text = link.text_content().strip()
                    link_href = link.get_attribute("href")
                    if link_href and link_text and link_text.lower() != 'подробнее':
                        if link_href.startswith('/'):
                            link_href = urljoin(main_url, link_href)
                        other_buttons.append({
                            "text": link_text,
                            "href": link_href.split('#')[0]
                        })
                except:
                    continue
            
            # ✅ Сохраняем карточку
            cards.append({
                "title": title,
                "description": description,
                "detail_link": detail_href,  # ← главное: ссылка «Подробнее»
                "other_buttons": other_buttons,
                "source_url": main_url
            })
            
            print(f"   ✓ {title or '[без заголовка]'}")
            print(f"      Описание: {description[:60] if description else 'нет'}...")
            print(f"      Ссылка: {detail_href}")
            
        except Exception as e:
            print(f"   ⚠ Ошибка: {e}")
            continue
    
    return cards


def main(
    url: str,
    headless: bool = False,
    output_file: str = None,
    wait_time: float = 2.0
):
    """Главная функция парсинга"""
    print(f"🚀 Парсинг: {url}")
    
    cards = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        try:
            # Загрузка страницы
            print("   📡 Загрузка...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("body", timeout=10000)
            
            # Ожидание + скролл для ленивой подгрузки
            if wait_time > 0:
                page.wait_for_timeout(int(wait_time * 1000))
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            
            # Парсинг
            print("   🔎 Поиск карточек...")
            cards = parse_cards(page, url)
            
            # Статистика
            print(f"\n📈 Найдено: {len(cards)} карточек")
            
            # Сохранение
            if output_file and cards:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(cards, f, ensure_ascii=False, indent=2)
                print(f"💾 Сохранено: {output_path.resolve()}")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()
    
    return cards


if __name__ == "__main__":
    # === НАСТРОЙКИ ===
    TARGET_URL = "https://www.vtb.ru/personal/platezhi/"
    HEADLESS = False
    WAIT_TIME = 2.5
    OUTPUT_JSON = "output/vtb_cards.json"
    
    # === ЗАПУСК ===
    result = main(
        url=TARGET_URL,
        headless=HEADLESS,
        output_file=OUTPUT_JSON,
        wait_time=WAIT_TIME
    )
    
    # === Извлечь только ссылки «Подробнее» для дальнейшего использования ===
    if result:
        detail_links = [card['detail_link'] for card in result if card.get('detail_link')]
        print(f"\n🔗 Ссылки 'Подробнее' ({len(detail_links)} шт):")
        for link in detail_links:
            print(f"   • {link}")