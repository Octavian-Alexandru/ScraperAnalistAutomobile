# FILE: scraper_olx.py
"""
Scraper optimizat pentru OLX.ro
- Mod ZILNIC (Daily Incremental): extrage rapid primele pagini sortate dupa cele mai noi anunturi.
- Mod COMPLET (Full Backfill): extrage pe ani/categorii.
- Salveaza direct in SQLite prin `db_helper.save_scraped_data`.
"""

import os
import time
import random
import re
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed
from db_helper import save_scraped_data, get_known_car_ids_and_prices

# --- Configurare ---
YEARS_TO_SCRAPE = range(2014, 2027)
MAX_PAGES_DEFAULT_DAILY = 20
MAX_PAGES_DEFAULT_FULL = 30
MAX_WORKERS = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


def random_sleep(min_delay=1.5, max_delay=3.5):
    time.sleep(random.uniform(min_delay, max_delay))


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = ''.join(filter(str.isdigit, text.replace('.', '').replace(',', '').replace(' ', '').replace('\xa0', '')))
    return int(digits) if digits else None


def parse_olx_card(element) -> Dict[str, Any]:
    soup = None
    if isinstance(element, str):
        soup = BeautifulSoup(element, "html.parser")
    elif hasattr(element, "evaluate"):
        try:
            html = element.evaluate("el => el.outerHTML")
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return {}
    elif isinstance(element, BeautifulSoup) or hasattr(element, "select_one"):
        soup = element
    else:
        return {}

    data = {}

    try:
        div = soup.select_one('div[data-cy="l-card"]') or soup

        link_el = div.select_one('a[href*="/d/oferta/"]')
        url = link_el.get('href') if link_el else None
        if url and not url.startswith('http'):
            url = "https://www.olx.ro" + url
        data['url'] = url

        data['car_id'] = None
        if url:
            match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
            if match:
                data['car_id'] = match.group(1)

        title_el = div.select_one('h6') or div.select_one('h4')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        price_el = div.select_one('p[data-testid="ad-price"]')
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data['currency'] = 'EUR' if price_text and '€' in price_text else 'RON' if price_text and 'lei' in price_text.lower() else 'EUR'

        loc_el = div.select_one('p[data-testid="location-date"]')
        data['location'] = loc_el.get_text(strip=True).split('-')[0].strip() if loc_el else None

        data['year'] = None
        data['mileage_km'] = None

        info_tags = div.select('span[class*="css-"]')
        for tag in info_tags:
            text = tag.get_text(strip=True).lower()
            if 'km' in text:
                parts = text.replace('-', ' ').split()
                try:
                    if len(parts[0]) == 4 and parts[0].isdigit():
                        data['year'] = int(parts[0])
                    km_text = "".join(filter(str.isdigit, text[4:]))
                    data['mileage_km'] = int(km_text) if km_text else None
                except Exception:
                    pass
            elif len(text) == 4 and text.isdigit() and not data['year']:
                data['year'] = int(text)

        # Fallback euristic Regex
        if not data.get('year') or not data.get('mileage_km'):
            try:
                from fallback_engine import extract_regex_card_fallback
                raw_txt = div.get_text(" ")
                fb = extract_regex_card_fallback(raw_txt)
                if not data.get('year') and fb.get('year'):
                    data['year'] = fb['year']
                if not data.get('mileage_km') and fb.get('mileage_km'):
                    data['mileage_km'] = fb['mileage_km']
                if not data.get('price') and fb.get('price'):
                    data['price'] = fb['price']
                    data['currency'] = fb.get('currency', 'EUR')
            except Exception:
                pass

        data['seller'] = None
        data['seller_type'] = None
        data['description'] = None
        data['fuel_type'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception:
        return {}

    return data


def scrape_olx_http_fallback(max_pages: int, early_stopping: bool, known_cars: dict, visited_ids: set) -> List[Dict[str, Any]]:
    """Fallback HTTP/Cloudscraper pentru OLX când Playwright este indisponibil."""
    from fallback_engine import fetch_with_full_fallback, extract_json_ld_car_data
    results = []
    consecutive_unchanged = 0
    EARLY_STOP_THRESHOLD = 30

    print("    [*] [OLX Fallback] Rulare prin modul HTTP/Cloudscraper + JSON-LD...")
    for page_num in range(1, max_pages + 1):
        url = f"https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/?currency=EUR&search%5Border%5D=created_at:desc&search%5Bfilter_float_price:to%5D=35000&page={page_num}"
        html, status, method = fetch_with_full_fallback(url, timeout=15)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")

        # 1. Extragere Schema.org JSON-LD
        ld_items = extract_json_ld_car_data(soup)
        for item in ld_items:
            cid = None
            u = item.get('url', '')
            match = re.search(r'-ID([a-zA-Z0-9]+)\.html', u)
            if match:
                cid = match.group(1)
            elif item.get('title'):
                import hashlib
                cid = hashlib.md5(item['title'].encode()).hexdigest()[:10]
            item['car_id'] = cid
            item['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if cid and cid not in visited_ids and item.get('price'):
                results.append(item)
                visited_ids.add(cid)

        # 2. Extragere carduri HTML
        cards = soup.select('div[data-cy="l-card"], div.css-1sw7q4x')
        for card in cards:
            listing = parse_olx_card(card)
            cid = listing.get('car_id')
            price = listing.get('price')
            if cid and cid not in visited_ids and price:
                results.append(listing)
                visited_ids.add(cid)

                if early_stopping and known_cars and cid in known_cars:
                    old_p = known_cars[cid]
                    if old_p and abs(price - old_p) < 10:
                        consecutive_unchanged += 1
                    else:
                        consecutive_unchanged = 0

        if early_stopping and consecutive_unchanged >= EARLY_STOP_THRESHOLD:
            print(f"    [*] [OLX Fallback] Early Stopping atins la pagina {page_num}.")
            break
        random_sleep(1.0, 2.0)

    return results


def scrape_olx_daily(max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: bool = True) -> List[Dict[str, Any]]:
    """Scrapeaza cele mai noi anunturi de pe OLX (sortate dupa created_at desc) cu Early Stopping și fallback HTTP."""
    results = []
    visited_ids = set()
    known_cars = get_known_car_ids_and_prices(source="olx") if early_stopping else {}
    consecutive_unchanged = 0
    EARLY_STOP_THRESHOLD = 30

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            page.route("**/*", lambda route: route.abort()
                       if route.request.resource_type in ["image", "stylesheet", "media", "font"]
                       else route.continue_())

            for page_num in range(1, max_pages + 1):
                url = f"https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/?currency=EUR&search%5Border%5D=created_at:desc&search%5Bfilter_float_price:to%5D=35000&page={page_num}"
                print(f"    [OLX Daily] Pagina {page_num}/{max_pages} (Cele mai noi)...")

                page_success = False
                for attempt in range(3):
                    try:
                        page.goto(url, timeout=30000)
                        page.wait_for_selector('div[data-cy="l-card"]', timeout=12000)
                        page_success = True
                        break
                    except Exception:
                        random_sleep(2.0, 4.0)

                if not page_success:
                    print(f"    [OLX Daily] Pagina {page_num} indisponibila sau rate-limit.")
                    break

                try:
                    cards = page.query_selector_all('div[data-cy="l-card"]')
                    if not cards:
                        break
                    for card in cards:
                        listing = parse_olx_card(card)
                        cid = listing.get('car_id')
                        price = listing.get('price')
                        if cid and cid not in visited_ids and price:
                            results.append(listing)
                            visited_ids.add(cid)

                            if early_stopping and known_cars:
                                if cid in known_cars:
                                    old_p = known_cars[cid]
                                    if old_p and abs(price - old_p) < 10:
                                        consecutive_unchanged += 1
                                    else:
                                        consecutive_unchanged = 0
                                else:
                                    consecutive_unchanged = 0

                    if early_stopping and consecutive_unchanged >= EARLY_STOP_THRESHOLD:
                        print(f"    [*] [OLX] Early Stopping la pagina {page_num}: s-a atins granita anunturilor deja existente ({consecutive_unchanged} neschimbate).")
                        break

                    random_sleep(1.0, 2.0)
                except Exception as e:
                    print(f"    [!] Eroare parsare OLX pagina {page_num}: {e}")
                    break

            browser.close()

    except Exception as e:
        print(f"    [!] Playwright indisponibil sau blocat ({e}). Activăm fallback HTTP/Cloudscraper pe OLX...")
        return scrape_olx_http_fallback(max_pages, early_stopping, known_cars, visited_ids)

    return results



def scrape_olx(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY) -> pd.DataFrame:
    print(f"[*] [OLX] Pornire scraping (Mod {'ZILNIC' if daily_mode else 'FULL'}, max {max_pages} pagini)...")
    start_time = time.time()

    if daily_mode:
        results = scrape_olx_daily(max_pages=max_pages, early_stopping=True)
    else:
        results = scrape_olx_daily(max_pages=max_pages, early_stopping=False)

    df = pd.DataFrame(results)
    if not df.empty:
        df.drop_duplicates(subset=['car_id'], inplace=True)
        save_scraped_data(df, source_name="olx")

    elapsed = time.time() - start_time
    print(f"[+] [OLX] Finalizat in {elapsed:.1f}s. Anunturi extrase: {len(df)}")
    return df


def main():
    parser = argparse.ArgumentParser(description="OLX Scraper")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul complet")
    parser.add_argument("--pages", type=int, default=3, help="Numar pagini de scanat")
    args = parser.parse_args()

    scrape_olx(daily_mode=not args.full, max_pages=args.pages)


if __name__ == "__main__":
    main()