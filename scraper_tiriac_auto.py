# FILE: scraper_tiriac_auto.py
"""
Scraper pentru Țiriac Auto Rulate (tiriacautorulate.ro).
Cel mai mare dealer autorizat de mașini rulate certificate din România.
- Date curate, kilometraj garantat, istoric service, TVA deductibil
- Salvare directă în SQLite prin `save_scraped_data` cu source='tiriac_auto'
"""

import sys
import re
import time
import random
import hashlib
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
from bs4 import BeautifulSoup
import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import save_scraped_data, get_known_car_ids_and_prices, DB_PATH
from logger_config import logger

MAX_PAGES_DEFAULT_DAILY = 5
MAX_PAGES_DEFAULT_FULL = 20


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text_clean = str(text).split(',')[0].replace('.', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text_clean))
    return int(digits) if digits else None


def parse_tiriac_card(soup_item) -> Dict[str, Any]:
    """Parsează un card auto de pe Tiriac Auto Rulate."""
    try:
        link_el = soup_item.find('a', href=lambda h: h and ('/auto-rulate/' in str(h) or '/masina/' in str(h)))
        if not link_el:
            link_el = soup_item.find('a', href=True)
        if not link_el:
            return {}

        url = link_el.get('href', '')
        if not url.startswith('http'):
            url = f"https://www.tiriacautorulate.ro{url}"

        # Car ID
        id_match = re.search(r'-(\d+)/?$', url) or re.search(r'/(\d+)/?$', url)
        car_id = id_match.group(1) if id_match else hashlib.md5(url.encode()).hexdigest()[:10]

        title_el = soup_item.find('h3') or soup_item.find('h2') or link_el
        title = title_el.get_text(strip=True) if title_el else None

        price_el = soup_item.find('span', class_=lambda c: c and 'price' in str(c).lower()) or soup_item.find('div', class_=lambda c: c and 'price' in str(c).lower())
        price = normalize_number(price_el.get_text(strip=True)) if price_el else None

        text_block = soup_item.get_text(" ", strip=True)

        # An fabricație
        year_match = re.search(r'\b(20[0-2]\d)\b', text_block)
        year = int(year_match.group(1)) if year_match else None

        # Kilometraj
        km_match = re.search(r'([\d\.\s]+)\s*km\b', text_block, re.IGNORECASE)
        mileage_km = normalize_number(km_match.group(1)) if km_match else None

        # Combustibil
        fuel_type = None
        if re.search(r'\b(diesel)\b', text_block, re.IGNORECASE):
            fuel_type = "Diesel"
        elif re.search(r'\b(benzina|benzină)\b', text_block, re.IGNORECASE):
            fuel_type = "Benzina"
        elif re.search(r'\b(hibrid|hybrid)\b', text_block, re.IGNORECASE):
            fuel_type = "Hibrid"
        elif re.search(r'\b(electric)\b', text_block, re.IGNORECASE):
            fuel_type = "Electric"

        # Locație showroom
        loc_el = soup_item.find('span', class_=lambda c: c and 'location' in str(c).lower())
        location = loc_el.get_text(strip=True) if loc_el else "București (Țiriac Auto)"

        return {
            "car_id": car_id,
            "url": url,
            "title": title,
            "price": price,
            "currency": "EUR",
            "year": year,
            "mileage_km": mileage_km,
            "fuel_type": fuel_type,
            "seller": "Țiriac Auto Rulate",
            "seller_type": "Dealer Autorizat",
            "location": location,
            "scrape_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }
    except Exception:
        return {}


def scrape_tiriac_auto(max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: bool = True) -> pd.DataFrame:
    """Scrapează catalogul de mașini rulate de pe Țiriac Auto."""
    logger.info(f"[tiriac_auto] Pornim culegerea datelor pentru primele {max_pages} pagini...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })

    known_cars = get_known_car_ids_and_prices(source="tiriac_auto") if early_stopping else {}
    results = []
    consecutive_known = 0

    base_url = "https://www.tiriacautorulate.ro/auto-rulate?page={}"

    for page_num in range(1, max_pages + 1):
        url = base_url.format(page_num)
        try:
            time.sleep(random.uniform(1.2, 2.5))
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[tiriac_auto] Status {resp.status_code} la pagina {page_num}.")
                break

            soup = BeautifulSoup(resp.text, 'lxml' if 'lxml' in sys.modules else 'html.parser')
            items = soup.find_all('div', class_=lambda c: c and ('product' in str(c).lower() or 'car-item' in str(c).lower() or 'card' in str(c).lower()))

            logger.info(f"[tiriac_auto] Pagina {page_num}: detectate {len(items)} carduri.")

            for it in items:
                car = parse_tiriac_card(it)
                if car and car.get('title') and car.get('price'):
                    cid = f"tiriac_auto_{car['car_id']}"
                    if early_stopping and cid in known_cars:
                        consecutive_known += 1
                        if consecutive_known >= 10:
                            logger.info(f"[tiriac_auto] Early stopping activat la pagina {page_num}.")
                            break
                    else:
                        consecutive_known = 0

                    results.append(car)

            if consecutive_known >= 10:
                break

        except Exception as e:
            logger.error(f"[tiriac_auto] Eroare la pagina {page_num}: {e}")
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.drop_duplicates(subset=['car_id'])
        stats = save_scraped_data(df, source_name="tiriac_auto")
        logger.info(f"[tiriac_auto] Salvare finalizată: {len(df)} mașini ({stats.get('new', 0)} noi).")
    else:
        logger.warning("[tiriac_auto] Nu s-au extras date în această sesiune.")

    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER TIRIAC AUTO ===")
    df_tir = scrape_tiriac_auto(max_pages=1, early_stopping=False)
    print(f"Extrase: {len(df_tir)} anunțuri.")
