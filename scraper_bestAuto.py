# FILE: scraper_bestAuto.py
"""
Scraper optimizat pentru BestAuto.ro
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


def random_sleep(min_delay=1.0, max_delay=3.0):
    time.sleep(random.uniform(min_delay, max_delay))


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text = text.replace('.', '').replace(',', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


def parse_bestauto_listing(element) -> Dict[str, Any]:
    try:
        html = element.evaluate("el => el.outerHTML")
    except Exception:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    data = {}

    try:
        div = soup.select_one('div.article-item') or soup

        data['car_id'] = div.get('data-articleid')

        a = div.select_one('a[href]')
        url = a.get('href') if a else None
        data['url'] = f"https://www.bestauto.ro{url}" if url and not url.startswith('http') else url

        title_el = div.select_one('h2.article-title a')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        desc_el = div.select_one('p.article-description')
        data['description'] = desc_el.get_text(strip=True) if desc_el else None

        loc_el = div.select_one('p.article-location span')
        data['location'] = loc_el.get_text(strip=True) if loc_el else None

        price_text = None
        price_el = div.select_one('span.new-price') or div.select_one('span[itemprop="price"]') or div.select_one('span.article-price')
        if price_el:
            price_text = price_el.get('content') or price_el.get_text(strip=True)

        data['price'] = normalize_number(price_text) if price_text else None
        data['currency'] = 'EUR' if price_text else None

        short_info = div.select_one('p.article-short-info span.article-lbl-txt')
        if short_info:
            parts = short_info.get_text(strip=True).split('|')
            try:
                data['year'] = normalize_number(parts[0])
                data['mileage_km'] = normalize_number(parts[2])
            except IndexError:
                data['year'] = None
                data['mileage_km'] = None

        data['seller'] = None
        data['seller_type'] = None
        data['fuel_type'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception:
        return {}

    return data


def scrape_bestauto_daily(max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: bool = True) -> List[Dict[str, Any]]:
    results = []
    visited_ids = set()
    known_cars = get_known_car_ids_and_prices(source="bestauto") if early_stopping else {}
    consecutive_unchanged = 0
    EARLY_STOP_THRESHOLD = 30

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
            url = f"https://www.bestauto.ro/auto/?currency=eur&maxprice=35000&damagedcar=neavariata&order=date&page={page_num}"
            print(f"    [BestAuto Daily] Pagina {page_num}/{max_pages} (Cele mai noi)...")

            page_success = False
            for attempt in range(3):
                try:
                    page.goto(url, timeout=30000)
                    page.wait_for_selector('div.article-item', timeout=12000)
                    page_success = True
                    break
                except Exception:
                    random_sleep(2.0, 4.0)

            if not page_success:
                print(f"    [BestAuto Daily] Pagina {page_num} indisponibila sau timeout.")
                break

            try:
                divs = page.query_selector_all('div.article-item')
                if not divs:
                    break
                for d in divs:
                    listing = parse_bestauto_listing(d)
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
                    print(f"    [*] [BestAuto] Early Stopping la pagina {page_num}: s-a atins granita anunturilor deja existente ({consecutive_unchanged} neschimbate).")
                    break

                random_sleep(1.0, 2.0)
            except Exception as e:
                print(f"    [!] Eroare parsare pagina {page_num}: {e}")
                break

        browser.close()

    return results


def scrape_bestauto(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY) -> pd.DataFrame:
    print(f"[*] [BestAuto] Pornire scraping (Mod {'ZILNIC' if daily_mode else 'FULL'}, max {max_pages} pagini)...")
    start_time = time.time()

    if daily_mode:
        results = scrape_bestauto_daily(max_pages=max_pages, early_stopping=True)
    else:
        results = scrape_bestauto_daily(max_pages=max_pages, early_stopping=False)

    df = pd.DataFrame(results)
    if not df.empty:
        df.drop_duplicates(subset=['car_id'], inplace=True)
        save_scraped_data(df, source_name="bestauto")

    elapsed = time.time() - start_time
    print(f"[+] [BestAuto] Finalizat in {elapsed:.1f}s. Anunturi extrase: {len(df)}")
    return df


def main():
    parser = argparse.ArgumentParser(description="BestAuto Scraper")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul complet")
    parser.add_argument("--pages", type=int, default=3, help="Numar pagini de scanat")
    args = parser.parse_args()

    scrape_bestauto(daily_mode=not args.full, max_pages=args.pages)


if __name__ == "__main__":
    main()