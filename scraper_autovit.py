# FILE: scraper_autovit.py
"""
Scraper optimizat pentru Autovit.ro
- Mod ZILNIC (Daily Incremental): extrage rapid cele mai noi anunturi in mod cronologic descrescator.
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
MAX_PAGES_DEFAULT_FULL = 50
MAX_WORKERS = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


def random_sleep(min_delay=1.0, max_delay=2.5):
    time.sleep(random.uniform(min_delay, max_delay))


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text_without_decimals = text.split(',')[0]
    digits = ''.join(filter(str.isdigit, text_without_decimals))
    return int(digits) if digits else None


def parse_autovit_card(element) -> Dict[str, Any]:
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
        link_el = soup.select_one('h2 a') or soup.find('a', href=lambda h: h and '/anunt/' in h)
        url = link_el.get('href') if link_el else None
        data['url'] = url
        data['car_id'] = url.split('-ID')[-1].replace('.html', '') if url and '-ID' in url else None

        data['title'] = link_el.get_text(strip=True) if link_el else None

        price_el = soup.select_one('h3')
        currency_el = price_el.find_next_sibling('p') if price_el else None
        data['price'] = normalize_number(price_el.get_text(strip=True)) if price_el else None
        data['currency'] = currency_el.get_text(strip=True) if currency_el else 'EUR'

        list_items = soup.select('ul.ooa-1o0axny li p, ul li p')
        data['location'] = list_items[0].get_text(strip=True) if len(list_items) >= 1 else None

        if len(list_items) >= 2:
            seller_info = list_items[1].get_text(strip=True)
            data['seller_type'] = seller_info.split('•')[0].strip() if '•' in seller_info else seller_info
        else:
            data['seller_type'] = None

        year_el = soup.select_one('dd[data-parameter="year"]')
        mileage_el = soup.select_one('dd[data-parameter="mileage"]')
        fuel_el = soup.select_one('dd[data-parameter="fuel_type"]')

        data['year'] = int(normalize_number(year_el.get_text(strip=True))) if year_el else None
        data['mileage_km'] = normalize_number(mileage_el.get_text(strip=True)) if mileage_el else None
        data['fuel_type'] = fuel_el.get_text(strip=True) if fuel_el else None

        # Fallback euristic Regex dacă lipsesc anul sau kilometrajul
        if not data.get('year') or not data.get('mileage_km'):
            try:
                from fallback_engine import extract_regex_card_fallback
                raw_txt = soup.get_text(" ")
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
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception:
        return {}

    return data


def scrape_autovit_http_fallback(max_pages: int, early_stopping: bool, known_cars: dict, visited_ids: set) -> List[Dict[str, Any]]:
    """Mecanism de rezervă prin HTTP direct și Cloudscraper când Playwright nu poate fi pornit."""
    from fallback_engine import fetch_with_full_fallback, extract_json_ld_car_data
    results = []
    consecutive_unchanged = 0
    EARLY_STOP_THRESHOLD = 30

    print("    [*] [Autovit Fallback] Rulare prin modul HTTP/Cloudscraper + JSON-LD...")
    for page_num in range(1, max_pages + 1):
        url = f"https://www.autovit.ro/autoturisme?search%5Bfilter_float_mileage%3Ato%5D=250000&search%5Bfilter_float_price%3Ato%5D=35000&search%5Border%5D=created_at%3Adesc&page={page_num}"
        html, status, method = fetch_with_full_fallback(url, timeout=15)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")

        # 1. Extragere Schema.org JSON-LD
        ld_items = extract_json_ld_car_data(soup)
        for item in ld_items:
            cid = None
            u = item.get('url', '')
            if '-ID' in u:
                cid = u.split('-ID')[-1].replace('.html', '')
            elif item.get('title'):
                import hashlib
                cid = hashlib.md5(item['title'].encode()).hexdigest()[:10]
            item['car_id'] = cid
            item['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if cid and cid not in visited_ids and item.get('price'):
                results.append(item)
                visited_ids.add(cid)

        # 2. Extragere carduri HTML
        cards = soup.select('article[data-id], article')
        for card in cards:
            listing = parse_autovit_card(card)
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
            print(f"    [*] [Autovit Fallback] Early Stopping atins la pagina {page_num}.")
            break
        random_sleep(1.0, 2.0)

    return results


def scrape_autovit_daily(max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: bool = True) -> List[Dict[str, Any]]:
    """Scrapeaza cele mai noi anunturi folosind un singur browser Playwright cu Early Stopping și fallback HTTP."""
    results = []
    visited_ids = set()
    known_cars = get_known_car_ids_and_prices(source="autovit") if early_stopping else {}
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
                url = f"https://www.autovit.ro/autoturisme?search%5Bfilter_float_mileage%3Ato%5D=250000&search%5Bfilter_float_price%3Ato%5D=35000&search%5Border%5D=created_at%3Adesc&page={page_num}"
                print(f"    [Autovit Daily] Pagina {page_num}/{max_pages} (Cele mai noi)...")

                page_success = False
                for attempt in range(3):
                    try:
                        page.goto(url, timeout=30000)
                        page.wait_for_selector('article[data-id]', timeout=10000)
                        page_success = True
                        break
                    except Exception:
                        random_sleep(2.0, 3.5)

                if not page_success:
                    print(f"    [Autovit Daily] Timeout sau rate-limit la pagina {page_num}. Oprim.")
                    break

                try:
                    cards = page.query_selector_all('article[data-id]')
                    if not cards:
                        break
                    for card in cards:
                        listing = parse_autovit_card(card)
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
                        print(f"    [*] [Autovit] Early Stopping la pagina {page_num}: s-a atins granita anunturilor deja existente ({consecutive_unchanged} neschimbate).")
                        break

                    random_sleep(1.0, 2.0)
                except Exception as e:
                    print(f"    [!] Eroare parsare pagina {page_num}: {e}")
                    break

            browser.close()

    except Exception as e:
        print(f"    [!] Playwright indisponibil sau blocat ({e}). Activăm fallback HTTP/Cloudscraper...")
        return scrape_autovit_http_fallback(max_pages, early_stopping, known_cars, visited_ids)

    return results


def scrape_year_worker(year: int, max_pages: int) -> List[Dict[str, Any]]:
    results = []
    visited_ids = set()
    delay_start = random.uniform(1.0, 4.0)
    time.sleep(delay_start)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=random.choice(USER_AGENTS), viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        page.route("**/*", lambda route: route.abort()
                   if route.request.resource_type in ["image", "stylesheet", "media", "font"]
                   else route.continue_())

        for page_num in range(1, max_pages + 1):
            url = f"https://www.autovit.ro/autoturisme?search%5Bfilter_float_mileage%3Ato%5D=250000&search%5Bfilter_float_price%3Ato%5D=25000&search%5Bfilter_float_year%3Afrom%5D={year}&search%5Bfilter_float_year%3Ato%5D={year}&search%5Border%5D=created_at%3Adesc&page={page_num}"
            try:
                page.goto(url, timeout=30000)
                page.wait_for_selector('article[data-id]', timeout=10000)
                cards = page.query_selector_all('article[data-id]')
                if not cards:
                    break
                for card in cards:
                    listing = parse_autovit_card(card)
                    cid = listing.get('car_id')
                    if cid and cid not in visited_ids and listing.get('price'):
                        results.append(listing)
                        visited_ids.add(cid)
                random_sleep(1.0, 2.0)
            except Exception:
                break
        browser.close()
    return results


def scrape_autovit(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY) -> pd.DataFrame:
    print(f"[*] [Autovit] Pornire scraping (Mod {'ZILNIC' if daily_mode else 'FULL'}, max {max_pages} pagini)...")
    start_time = time.time()

    if daily_mode:
        results = scrape_autovit_daily(max_pages=max_pages)
    else:
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(scrape_year_worker, y, max_pages): y for y in YEARS_TO_SCRAPE}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    results.extend(res)
                except Exception as e:
                    print(f"[!] Eroare worker an: {e}")

    df = pd.DataFrame(results)
    if not df.empty:
        df.drop_duplicates(subset=['car_id'], inplace=True)
        save_scraped_data(df, source_name="autovit")

    elapsed = time.time() - start_time
    print(f"[+] [Autovit] Finalizat in {elapsed:.1f}s. Anunturi extrase: {len(df)}")
    return df


def main():
    parser = argparse.ArgumentParser(description="Autovit Scraper")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul complet pe ani")
    parser.add_argument("--pages", type=int, default=5, help="Numar pagini de scanat")
    args = parser.parse_args()

    scrape_autovit(daily_mode=not args.full, max_pages=args.pages)


if __name__ == "__main__":
    main()