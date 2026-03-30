#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline for downloading XLSX files from VTB tariff pages.
Extracts files exclusively from the "Сборники тарифов" tab.
Filenames preserved as visible link text from the website.
Files with "архив" in name are skipped.
"""

import re
import time
import uuid
import random
import requests
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, unquote

from playwright.sync_api import sync_playwright


def make_folder_name_from_url(url: str, segments: int = 2) -> str:
    """Generates folder name from last N segments of URL path."""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return 'misc'
    selected = path_parts[-segments:] if len(path_parts) >= segments else path_parts
    safe_parts = [re.sub(r'[^\w\-]', '_', unquote(p)) for p in selected]
    return '_'.join(safe_parts) if safe_parts else 'misc'


def sanitize_filename(filename: str) -> str:
    """Removes invalid characters and file size info from filename."""
    # Remove file size patterns (e.g., "1.7 Мб", "2.5 МБ", "500 Кб", "1.2 MB")
    filename = re.sub(r'\s*\(?\s*\d+[\.,]?\d*\s*[КKкk][БBбb]\s*\)?', '', filename, flags=re.IGNORECASE)
    
    # Remove invalid filesystem characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Collapse multiple spaces
    filename = re.sub(r'\s+', ' ', filename)
    
    # Clean up leading/trailing spaces, dots, underscores
    return filename.strip().strip('_.')


def download_file(
    url: str, 
    save_dir: Path, 
    display_name: str,
    file_type: str = "xlsx",
    skip_keywords: Optional[List[str]] = None
) -> bool:
    """Downloads file and saves with user-visible name."""
    if skip_keywords is None:
        skip_keywords = []
    
    # Add "архив" to skip keywords automatically
    skip_keywords = skip_keywords + ["архив"]
    
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    url_lower = url.lower()
    
    if any(kw.lower() in url_lower for kw in skip_keywords):
        return True
    
    base_name = sanitize_filename(display_name)
    if not base_name:
        base_name = f"document_{uuid.uuid4().hex[:8]}"
    
    filename = f"{base_name}.{file_type}" if not base_name.lower().endswith(f".{file_type}") else base_name
    
    # Check for "архив" in filename
    if any(kw.lower() in filename.lower() for kw in skip_keywords):
        return True
    
    final_path = save_dir / filename
    
    if final_path.exists():
        stem = sanitize_filename(base_name)
        unique_id = uuid.uuid4().hex[:6]
        final_path = save_dir / f"{stem}_{unique_id}.{file_type}"
    
    save_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
            "Referer": "https://www.vtb.ru/"
        }
        
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        
        with open(final_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        return True
        
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else None
        if status not in (403, 404):
            pass
        return False
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False


def extract_xlsx_links_from_page(
    page_url: str, 
    headless: bool = True,
    tab_text: str = "Сборники тарифов"
) -> List[Tuple[str, str]]:
    """
    Navigates to page, switches to specified tab, extracts XLSX links with visible text.
    Returns list of tuples: (url, display_name).
    """
    results = {}
    site_domain = "https://www.vtb.ru"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        def handle_response(response):
            url = response.url.split('#')[0]
            content_type = response.headers.get('content-type', '').lower()
            if url.lower().endswith('.xlsx') or 'spreadsheetml' in content_type or 'excel' in content_type:
                if site_domain in url and url not in results:
                    results[url] = None
        
        page.on("response", handle_response)
        
        try:
            page.goto(page_url.strip(), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("body", timeout=10000)
            page.wait_for_timeout(2000)
            
            if tab_text:
                try:
                    tab_locator = page.locator(
                        "li[class*='TabGrid'], li[data-testid]", 
                        has_text=tab_text
                    ).first
                    tab_locator.wait_for(state="visible", timeout=10000)
                    tab_locator.click()
                    page.wait_for_timeout(1500)
                    
                    xlsx_data = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a[href]'))
                            .map(a => ({
                                href: a.href,
                                text: (a.innerText || a.textContent || '').trim()
                            }))
                            .filter(item => {
                                const h = item.href.toLowerCase();
                                return (h.endsWith('.xlsx') || h.includes('.xlsx?')) && item.text;
                            });
                    }""")
                    
                    for item in xlsx_data:
                        clean_url = item['href'].split('#')[0]
                        if clean_url.startswith('/'):
                            clean_url = urljoin(site_domain, clean_url)
                        if site_domain in clean_url:
                            results[clean_url] = item['text']
                    
                    return [(url, name) for url, name in results.items() if name]
                    
                except Exception:
                    pass
            
            xlsx_data = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({
                        href: a.href,
                        text: (a.innerText || a.textContent || '').trim()
                    }))
                    .filter(item => {
                        const h = item.href.toLowerCase();
                        return (h.endsWith('.xlsx') || h.includes('.xlsx?')) && item.text;
                    });
            }""")
            
            for item in xlsx_data:
                clean_url = item['href'].split('#')[0]
                if clean_url.startswith('/'):
                    clean_url = urljoin(site_domain, clean_url)
                if site_domain in clean_url and clean_url not in results:
                    results[clean_url] = item['text']
                    
        except Exception:
            pass
        finally:
            browser.close()
    
    return [(url, name) for url, name in results.items() if name]


def download_xlsx_from_page(
    page_url: str, 
    save_root: Path, 
    headless: bool = True, 
    tab_text: str = "Сборники тарифов",
    skip_keywords: Optional[List[str]] = None
) -> int:
    """Finds XLSX files on page and downloads them with visible names."""
    page_url = page_url.strip()
    
    folder_name = make_folder_name_from_url(page_url, segments=2)
    target_dir = save_root / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    xlsx_data = extract_xlsx_links_from_page(
        page_url, 
        headless=headless,
        tab_text=tab_text
    )
    
    if not xlsx_data:
        return 0
    
    success = 0
    
    for i, (file_url, display_name) in enumerate(xlsx_data, 1):
        if download_file(
            file_url, 
            save_dir=target_dir, 
            display_name=display_name,
            file_type="xlsx",
            skip_keywords=skip_keywords
        ):
            success += 1
        time.sleep(0.5)
    
    return success


def run_pipeline(
    main_url: str,
    output_root: str = "vtb_downloads",
    headless: bool = True,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    tab_text: str = "Сборники тарифов",
    skip_keywords: Optional[List[str]] = None
):
    """Runs complete pipeline for downloading XLSX files."""
    root_path = Path(output_root)
    root_path.mkdir(parents=True, exist_ok=True)
    
    count = download_xlsx_from_page(
        main_url, 
        save_root=root_path, 
        headless=headless,
        tab_text=tab_text,
        skip_keywords=skip_keywords
    )
    
    return count


if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    OUTPUT_FOLDER = script_dir / "vtb_downloads"
    
    URLS = [
        "https://www.vtb.ru/tarify/chastnim-licam/",
    ]
    
    HEADLESS = False
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0
    TAB_TEXT = "Сборники тарифов"
    SKIP_KEYWORDS = []

    total_all = 0
    
    for idx, url in enumerate(URLS, 1):
        url = url.strip()
        if not url:
            continue
            
        count = run_pipeline(
            main_url=url,
            output_root=OUTPUT_FOLDER,
            headless=HEADLESS,
            min_delay=MIN_DELAY,
            max_delay=MAX_DELAY,
            tab_text=TAB_TEXT,
            skip_keywords=SKIP_KEYWORDS
        )
        total_all += count
        
        if idx < len(URLS):
            delay = random.uniform(1.0, 3.0)
            time.sleep(delay)