# download_psb_pdfs.py
from playwright.sync_api import sync_playwright
import requests
import os
import sys
from urllib.parse import urlparse, unquote

# 🔹 Папка для сохранения — КОРНЕВАЯ директория проекта
DOWNLOAD_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"📁 Файлы будут сохранены в: {DOWNLOAD_DIR}")

print("🚀 Запуск скачивания PDF с ПСБ...")

try:
    with sync_playwright() as p:
        print("✓ Playwright инициализирован")
        
        browser = p.chromium.launch(
            headless=False,
            slow_mo=50
        )
        print("✓ Браузер запущен")
        
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        print("✓ Страница создана")
        
        # 🔹 Переход на целевую страницу
        url = "https://www.psbank.ru/bank/emitters/openinfo"
        print(f"🌐 Переход на {url}...")
        response = page.goto(url, wait_until="networkidle", timeout=60000)
        print(f"✓ Статус ответа: {response.status}")
        
        # 🔹 Ждём появления списка документов
        print("⏳ Ожидаем загрузку списка документов...")
        page.wait_for_selector(".documents-list__link", timeout=30000)
        
        # 🔹 Собираем данные о PDF-файлах: текст + URL
        pdf_items = []
        links = page.locator(".documents-list__link[href$='.pdf']").all()
        
        for link in links:
            href = link.get_attribute("href").strip()
            text = link.text_content().strip()
            # 🔹 Приводим относительные пути к абсолютным
            if href.startswith("/"):
                href = "https://www.psbank.ru" + href
            pdf_items.append({"text": text, "url": href})
        
        print(f"📄 Найдено файлов для скачивания: {len(pdf_items)}")
        
        if not pdf_items:
            print("⚠️ Не найдено PDF-файлов. Проверьте селекторы или структуру страницы.")
        else:
            # 🔹 Создаём сессию requests с теми же заголовками, что у браузера
            session = requests.Session()
            session.headers.update({
                "User-Agent": page.evaluate("() => navigator.userAgent"),
                "Referer": url,
                "Accept": "application/pdf,*/*",
            })
            
            # 🔹 Копируем cookies из браузера в сессию (если есть авторизация)
            for cookie in context.cookies():
                session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"])
            
            # 🔹 Скачиваем каждый файл напрямую через HTTP
            for i, item in enumerate(pdf_items, 1):
                filename_raw = unquote(urlparse(item["url"]).path.split("/")[-1])
                # 🔹 Формируем безопасное имя файла
                filename = "".join(c for c in filename_raw if c.isalnum() or c in "._- ")
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                
                print(f"\n[{i}/{len(pdf_items)}] Скачивание: {item['text']}")
                print(f"🔗 URL: {item['url']}")
                
                try:
                    resp = session.get(item["url"], timeout=60, stream=True)
                    resp.raise_for_status()
                    
                    # 🔹 Пошаговая запись файла (экономит память)
                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    size_kb = os.path.getsize(filepath) / 1024
                    print(f"✅ Сохранён: {filename} ({size_kb:.1f} КБ)")
                    
                except requests.exceptions.RequestException as e:
                    print(f"❌ Ошибка скачивания {filename}: {e}")
        
        print(f"\n🎉 Готово! Все доступные файлы в папке: {DOWNLOAD_DIR}")
        
        # 🔹 Скриншот для отладки
        page.screenshot(path="test_ok.png")
        print("📸 Скриншот сохранён: test_ok.png")
        
        context.close()
        browser.close()
        print("🏁 Успешно завершено!")
        
except ImportError:
    print("\n❌ Не установлена библиотека requests")
    print("💡 Выполните: pip install requests")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {type(e).__name__}: {e}", file=sys.stderr)
    print("\n💡 Возможные причины:")
    print("   1. Не установлен браузер: 'python -m playwright install chromium'")
    print("   2. Сайт блокирует прямые запросы — попробуйте добавить больше заголовков")
    print("   3. Требуется авторизация — cookies копируются автоматически, но может не хватить")
    print("   4. Сетевые проблемы или таймауты")
    sys.exit(1)