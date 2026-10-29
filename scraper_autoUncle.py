# FILE: scraper_autoUncle.py
"""
Scraper optimizat pentru AutoUncle.ro
- Mod ZILNIC (Daily Incremental): extrage rapid cele mai noi anunturi in 15-30 secunde.
- Mod COMPLET (Full Backfill): extrage pe ani/categorii.
- Parsare semantica rezistenta la schimbarea claselor CSS.
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
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from db_helper import save_scraped_data, get_known_car_ids_and_prices

# --- Configurare ---
YEARS_TO_SCRAPE = range(2014, 2027)
MAX_PAGES_DEFAULT_DAILY = 20
MAX_PAGES_DEFAULT_FULL = 50
MAX_WORKERS = 4

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text = text.replace('.', '').replace(',', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


def parse_autouncle_article(art) -> Dict[str, Any]:
    """Extragere semantica rezistenta la schimbarea claselor CSS."""
    data = {}
    try:
        # 1. URL si car_id
        link_el = art.find('a', href=lambda h: h and '/d/' in h)
        if not link_el:
            return {}

        href = link_el.get('href', '')
        data['url'] = f"https://www.autouncle.ro{href}" if href.startswith('/') else href

        m = re.search(r'/d/(\d+)-', data['url'])
        data['car_id'] = m.group(1) if m else None
        if not data['car_id']:
            return {}

        # 2. Titlu
        title_el = art.find(['h2', 'h3', 'h4'])
        if title_el:
            data['title'] = title_el.get_text(strip=True)
        else:
            img = art.find('img', alt=True)
            if img and img.get('alt'):
                data['title'] = img['alt'].replace('Second-hand ', '').strip()
            else:
                data['title'] = link_el.get_text(strip=True).split('|')[0].strip()

        # 3. Pret
        all_text = art.get_text(" ", strip=True)
        prices_found = re.findall(r'(\d+[\.\d]*)\s*(?:EUR|€)', all_text)
        if prices_found:
            data['price'] = normalize_number(prices_found[0])
            data['currency'] = 'EUR'
        else:
            data['price'] = None
            data['currency'] = None

        # 4. An si Kilometraj
        data['year'] = None
        data['mileage_km'] = None

        km_match = re.search(r'([\d\.\s]+)\s*km\b', all_text, re.IGNORECASE)
        if km_match:
            data['mileage_km'] = normalize_number(km_match.group(1))

        year_matches = re.findall(r'\b(20[12]\d)\b', all_text)
        if year_matches:
            data['year'] = int(year_matches[0])

        # 5. Combustibil
        data['fuel_type'] = None
        for f in ['Benzină', 'Benzina', 'Diesel', 'Hibrid', 'Hybrid', 'Electric', 'GPL']:
            if re.search(rf'\b{f}\b', all_text, re.IGNORECASE):
                data['fuel_type'] = 'Benzina' if 'benzin' in f.lower() else ('Hibrid' if 'hib' in f.lower() or 'hyb' in f.lower() else f.capitalize())
                break

        # 6. Metadata
        dealer_match = re.search(r'(Dealer|Dealer autorizat|Privat)', all_text, re.IGNORECASE)
        data['seller_type'] = dealer_match.group(0).capitalize() if dealer_match else 'Privat'
        data['seller'] = None
        data['location'] = None
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception:
        return {}

    return data


def scrape_page(session: requests.Session, url: str) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    for attempt in range(3):
        try:
            resp = session.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.find_all('article')
            page_results = []
            for art in articles:
                item = parse_autouncle_article(art)
                if item and item.get('car_id') and item.get('price'):
                    page_results.append(item)
            return page_results
        except Exception:
            time.sleep(3)
    return []


def scrape_autouncle(
    daily_mode: bool = True,
    max_pages: int = MAX_PAGES_DEFAULT_DAILY,
    early_stopping: bool = True,
    early_stop_threshold: int = 25
) -> pd.DataFrame:
    """
    Functie apelabila direct din pipeline-ul zilnic sau individual.
    - `daily_mode=True`: Scaneaza cele mai recente pagini rapide cu Early Stopping,
      apoi verifica sectiunea de preturi reduse recent.
    - `daily_mode=False`: Scaneaza exhaustiv pe categorii de ani.
    """
    print(f"[*] [AutoUncle] Pornire scraping (Mod {'ZILNIC' if daily_mode else 'FULL'}, max {max_pages} pagini)...")
    start_time = time.time()
    results = []
    visited_ids = set()
    session = requests.Session()

    if daily_mode:
        known_cars = get_known_car_ids_and_prices(source="autouncle") if early_stopping else {}
        consecutive_unchanged = 0

        # 1. Rulare pe cele mai noi anunturi (created_at_desc)
        for page_num in range(1, max_pages + 1):
            url = f"https://www.autouncle.ro/ro/masini-second-hand?s%5Bmax_km%5D=250000&s%5Bmax_price%5D=35000&s%5Bsort%5D=created_at_desc&page={page_num}"
            print(f"    [AutoUncle Daily] Pagina {page_num}/{max_pages} (Cele mai noi)...")
            items = scrape_page(session, url)
            if not items:
                break

            for it in items:
                cid = it['car_id']
                price = it.get('price')
                if cid not in visited_ids:
                    results.append(it)
                    visited_ids.add(cid)

                if early_stopping and known_cars:
                    if cid in known_cars:
                        old_p = known_cars[cid]
                        if old_p and price and abs(price - old_p) < 10:
                            consecutive_unchanged += 1
                        else:
                            consecutive_unchanged = 0
                    else:
                        consecutive_unchanged = 0

            if early_stopping and consecutive_unchanged >= early_stop_threshold:
                print(f"    [*] [AutoUncle] Early Stopping la pagina {page_num}: s-a atins granita anunturilor deja existente ({consecutive_unchanged} neschimbate).")
                break

            time.sleep(random.uniform(0.6, 1.4))

        # 2. Rulare rapida pe masini cu pret redus recent (recently_price_dropped)
        print("    [AutoUncle Daily] Scanare sectiune 'Pret redus recent'...")
        for p_drop in range(1, 4):
            url_drop = f"https://www.autouncle.ro/ro/masini-second-hand?s%5Bmax_km%5D=250000&s%5Bmax_price%5D=35000&s%5Bsort%5D=recently_price_dropped&page={p_drop}"
            items_drop = scrape_page(session, url_drop)
            if not items_drop:
                break
            for it in items_drop:
                cid = it['car_id']
                if cid not in visited_ids:
                    results.append(it)
                    visited_ids.add(cid)
            time.sleep(random.uniform(0.5, 1.0))

    else:
        # Full mode
        def scrape_for_year(year: int):
            year_results = []
            s = requests.Session()
            for p in range(1, max_pages + 1):
                url = f"https://www.autouncle.ro/ro/masini-second-hand?s%5Bmax_km%5D=250000&s%5Bmax_price%5D=30000&s%5Bmax_year%5D={year}&s%5Bmin_year%5D={year}&page={p}"
                items = scrape_page(s, url)
                if not items:
                    break
                year_results.extend(items)
                time.sleep(random.uniform(1.0, 2.0))
            return year_results

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(scrape_for_year, y): y for y in YEARS_TO_SCRAPE}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    for it in res:
                        cid = it['car_id']
                        if cid not in visited_ids:
                            results.append(it)
                            visited_ids.add(cid)
                except Exception as e:
                    print(f"[!] Eroare thread an: {e}")

    df = pd.DataFrame(results)
    elapsed = time.time() - start_time
    print(f"[+] [AutoUncle] Finalizat in {elapsed:.1f}s. Anunturi extrase: {len(df)}")

    if not df.empty:
        save_scraped_data(df, source_name="autouncle")

    return df


def main():
    parser = argparse.ArgumentParser(description="AutoUncle Scraper")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul complet pe ani")
    parser.add_argument("--pages", type=int, default=5, help="Numar pagini de scanat")
    args = parser.parse_args()

    scrape_autouncle(daily_mode=not args.full, max_pages=args.pages)


if __name__ == "__main__":
    main()