# FILE: scraper_cautiMasina.py
"""
Scraper optimizat pentru CautiMasina.ro
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
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


def parse_cautimasina_listing(element) -> Dict[str, Any]:
    try:
        html = element.evaluate("el => el.outerHTML")
    except Exception:
        return {}

    soup = BeautifulSoup(html, 'html.parser')
    data = {}

    try:
        a_tag = soup.find('a') if soup.name != 'a' else soup
        url = a_tag.get('href') if a_tag else None
        data['url'] = f"https://cautimasina.ro{url}" if url and not url.startswith('http') else url
        data['car_id'] = url.split('-')[-1].split('?')[0] if url else None

        title_el = soup.find('h3')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        full_text = soup.get_text(separator=' ', strip=True)

        # Extragere pret
        price_m = re.search(r'([\d\.]+)\s*(?:€|EUR|RON|LEI)', full_text, re.IGNORECASE)
        if price_m:
            data['price'] = normalize_number(price_m.group(1))
            data['currency'] = 'RON' if any(c in price_m.group(0).upper() for c in ['RON', 'LEI']) else 'EUR'
        else:
            data['price'] = None
            data['currency'] = 'EUR'

        # Extragere an
        year_match = re.search(r'\b(20[0-2]\d|199\d)\b', data['title'] or full_text)
        data['year'] = int(year_match.group(0)) if year_match else None

        # Extragere kilometri
        km_m = re.search(r'([\d\.]+)\s*km', full_text, re.IGNORECASE)
        data['mileage_km'] = normalize_number(km_m.group(1)) if km_m else None

        # Extragere combustibil
        fuel_m = re.search(r'\b(diesel|motorina|benzina|benzină|hibrid|hybrid|electric|gpl)\b', full_text, re.IGNORECASE)
        if fuel_m:
            f_raw = fuel_m.group(1).lower()
            if f_raw in ['diesel', 'motorina']:
                data['fuel_type'] = 'Diesel'
            elif 'benzin' in f_raw:
                data['fuel_type'] = 'Benzina'
            elif 'hib' in f_raw or 'hyb' in f_raw:
                data['fuel_type'] = 'Hibrid'
            elif 'electr' in f_raw:
                data['fuel_type'] = 'Electric'
            elif 'gpl' in f_raw:
                data['fuel_type'] = 'GPL'
            else:
                data['fuel_type'] = f_raw.capitalize()
        else:
            data['fuel_type'] = None

        data['location'] = None
        data['seller'] = None
        data['seller_type'] = None
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception:
        return {}

    return data


def scrape_cautimasina_daily(max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: bool = True) -> List[Dict[str, Any]]:
    results = []
    visited_ids = set()
    known_cars = get_known_car_ids_and_prices(source="cautimasina") if early_stopping else {}
    consecutive_unchanged = 0
    EARLY_STOP_THRESHOLD = 30

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = f"https://cautimasina.ro/anunturi?sort=3&page={page_num}"
            print(f"    [CautiMasina Daily] Pagina {page_num}/{max_pages} (Cele mai noi)...")

            page_success = False
            for attempt in range(3):
                try:
                    page.goto(url, timeout=25000)
                    page.wait_for_selector('a[href*="-second-hand-info-"], h3', timeout=12000)
                    page_success = True
                    break
                except Exception:
                    random_sleep(2.0, 4.0)

            if not page_success:
                print(f"    [CautiMasina Daily] Pagina {page_num} indisponibila sau timeout.")
                break

            try:
                cards = [el for el in page.query_selector_all('a') if el.get_attribute('href') and '-second-hand-info-' in el.get_attribute('href')]
                if not cards:
                    break
                for card in cards:
                    listing = parse_cautimasina_listing(card)
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
                    print(f"    [*] [CautiMasina] Early Stopping la pagina {page_num}: s-a atins granita anunturilor deja existente ({consecutive_unchanged} neschimbate).")
                    break

                random_sleep(1.0, 2.0)
            except Exception as e:
                print(f"    [!] Eroare parsare pagina {page_num}: {e}")
                break

        browser.close()

    return results



def scrape_cautimasina(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY) -> pd.DataFrame:
    print(f"[*] [CautiMasina] Pornire scraping (Mod {'ZILNIC' if daily_mode else 'FULL'}, max {max_pages} pagini)...")
    start_time = time.time()

    if daily_mode:
        results = scrape_cautimasina_daily(max_pages=max_pages, early_stopping=True)
    else:
        results = scrape_cautimasina_daily(max_pages=max_pages, early_stopping=False)

    df = pd.DataFrame(results)
    if not df.empty:
        df.drop_duplicates(subset=['car_id'], inplace=True)
        save_scraped_data(df, source_name="cautimasina")

    elapsed = time.time() - start_time
    print(f"[+] [CautiMasina] Finalizat in {elapsed:.1f}s. Anunturi extrase: {len(df)}")
    return df


def main():
    parser = argparse.ArgumentParser(description="CautiMasina Scraper")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul complet")
    parser.add_argument("--pages", type=int, default=3, help="Numar pagini de scanat")
    args = parser.parse_args()

    scrape_cautimasina(daily_mode=not args.full, max_pages=args.pages)


if __name__ == "__main__":
    main()