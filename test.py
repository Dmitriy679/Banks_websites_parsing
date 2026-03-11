# test_playwright.py
from playwright.sync_api import sync_playwright
import sys

print("🚀 Запуск теста Playwright...")

try:
    with sync_playwright() as p:
        print("✓ Playwright инициализирован")
        
        browser = p.chromium.launch(
            headless=False,  # видим браузер
            slow_mo=50       # замедление для отладки
        )
        print("✓ Браузер запущен")
        
        context = browser.new_context(
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        print("✓ Страница создана")
        
        # 🔹 Тестируем на максимально простом сайте
        print("🌐 Переход на example.com...")
        response = page.goto("https://www.psbank.ru/bank/emitters/openinfo", wait_until="domcontentloaded", timeout=30000)
        print(f"✓ Статус ответа: {response.status}")
        
        print("📸 Делаем скриншот...")
        page.screenshot(path="test_ok.png")
        print("✅ Скриншот сохранён: test_ok.png")
        
        context.close()
        browser.close()
        print("🏁 Успешно завершено!")
        
except Exception as e:
    print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {type(e).__name__}: {e}", file=sys.stderr)
    print("\n💡 Возможные причины:")
    print("   1. Не установлен браузер: выполните 'python -m playwright install chromium'")
    print("   2. Антивирус/брандмауэр блокирует запуск Chromium")
    print("   3. Повреждена виртуальная среда — попробуйте пересоздать venv")
    print("   4. Конфликт версий — обновите: 'pip install --upgrade playwright'")
    sys.exit(1)