# download_pdf.py
import requests
from pathlib import Path

def download_pdf(save_path: str | Path = None, url: str = None, prefix: str = "PSB_vklad_") -> bool:
    """
    Скачивает PDF по прямой ссылке и сохраняет с префиксом в имени.
    
    :param save_path: Путь куда сохранить (папка или полный путь с именем файла)
    :param url: Ссылка на PDF
    :param prefix: Префикс для имени файла (по умолчанию "vklad_")
    :return: True если успешно, иначе False
    """
    # Значения по умолчанию
    if url is None:
        url = "https://www.psbank.ru/qpstorage/psb/images/conditionsterms.pdf"
    url = url.strip()
    
    # Определяем путь сохранения
    if save_path is None:
        save_dir = Path(__file__).parent
        # Имя файла из URL + префикс
        filename = prefix + url.split("/")[-1]
    else:
        save_path = Path(save_path)
        if save_path.suffix.lower() == ".pdf":
            # Указан полный путь с именем файла
            save_dir = save_path.parent
            # Добавляем префикс к имени, сохраняя расширение
            filename = prefix + save_path.name
        else:
            # Указана только папка
            save_dir = save_path
            filename = prefix + url.split("/")[-1]
    
    final_path = save_dir / filename
    save_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        print(f"→ Загрузка: {url}")
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        with open(final_path, "wb") as f:
            f.write(response.content)
        
        print(f"✓ Сохранено: {final_path} ({len(response.content)/1024:.1f} КБ)")
        return True
        
    except requests.exceptions.Timeout:
        print(f"✗ Таймаут: сервер не ответил за 30 сек")
        return False
    except requests.exceptions.ConnectionError:
        print(f"✗ Ошибка подключения: проверьте интернет или доступ к сайту")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"✗ HTTP ошибка: {e}")
        return False
    except Exception as e:
        print(f"✗ Неизвестная ошибка: {e}")
        return False


if __name__ == "__main__":
    # Примеры использования:
    
    # 1. Сохранить в папку со скриптом как vklad_conditionsterms.pdf
    # download_pdf()
    
    # 2. Сохранить в папку "docs" с префиксом
    download_pdf(save_path="./docs")
    
    # 3. Сохранить с полным путём (префикс добавится автоматически)
    # download_pdf(save_path="./files/mydoc.pdf")  → сохранит как ./files/vklad_mydoc.pdf
    
    # 4. Другой префикс
    # download_pdf(prefix="psb_")
    
    # 5. Без префикса (пустая строка)
    # download_pdf(prefix="")