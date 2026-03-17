#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсинг карточек VTB: только title, description, detail_link
Сохраняем только если все 3 поля заполнены
"""

import json
import time
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright


def parse_cards(page, main_url: str):
    """
    Извлекает карточки с 3 полями:
    - title
    - description
    - detail_link
    
    Сохраняет только если все 3 поля заполнены
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
                continue  # нет ссылки — пропускаем
            
            # 🔹 2. Поднимаемся к контейнеру карточки (3-4 уровня вверх)
            card_container = btn
            for _ in range(4):
                card_container = card_container.locator("..")
            
            # 🔹 3. Заголовок
            title = None
            try:
                title_el = card_container.locator("p").first
                if title_el.is_visible():
                    title_text = title_el.text_content().strip()
                    if 0 < len(title_text) < 100:
                        title = title_text
            except:
                pass
            
            # 🔹 4. Описание (из markdown-блока выше кнопки)
            description = None
            try:
                markdown_block = card_container.locator('[class*="markdown"]').first
                if markdown_block.is_visible():
                    description = markdown_block.text_content().strip()
            except:
                pass
            
            # Если markdown не найден — пробуем альтернативу
            if not description:
                try:
                    all_texts = card_container.evaluate("""el => {
                        const texts = [];
                        el.querySelectorAll('p, div, span').forEach(node => {
                            const txt = node.textContent.trim();
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
                    if len(all_texts) >= 1:
                        description = all_texts[0]
                except:
                    pass
            
            # ✅ СОХРАНЯЕМ ТОЛЬКО ЕСЛИ ВСЕ 3 ПОЛЯ ЗАПОЛНЕНЫ
            if title and description and detail_href:
                cards.append({
                    "title": title,
                    "description": description,
                    "detail_link": detail_href
                })
                print(f"   ✓ {title}")
                print(f"      Описание: {description[:60]}...")
                print(f"      Ссылка: {detail_href}")
            else:
                missing = []
                if not title:
                    missing.append("title")
                if not description:
                    missing.append("description")
                if not detail_href:
                    missing.append("detail_link")
                print(f"   ⏭ Пропущено (нет {', '.join(missing)})")
            
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
            print(f"\n📈 Найдено карточек с полным набором полей: {len(cards)}")
            
            # Сохранение
            if output_file and cards:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(cards, f, ensure_ascii=False, indent=2)
                print(f"💾 Сохранено: {output_path.resolve()}")
            elif not cards:
                print("⚠ Нет карточек для сохранения (все отфильтрованы)")
            
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
    OUTPUT_JSON = "vtb/vtb_downloads/vtb_platezhi.json"
    
    # === ЗАПУСК ===
    result = main(
        url=TARGET_URL,
        headless=HEADLESS,
        output_file=OUTPUT_JSON,
        wait_time=WAIT_TIME
    )
    
    # === Вывод ссылок для дальнейшего использования ===
    if result:
        detail_links = [card['detail_link'] for card in result]
        print(f"\n🔗 Ссылки 'Подробнее' ({len(detail_links)} шт):")
        for link in detail_links:
            print(f"   • {link}")
    else:
        print("\n⚠ Карточки не найдены или не прошли фильтр (нужны все 3 поля)")