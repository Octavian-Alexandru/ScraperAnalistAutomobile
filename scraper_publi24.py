# FILE: scraper_publi24.py
"""
Scraper optimizat pentru Publi24.ro (Secțiunea Auto & Autoturisme România).
- Extrage oferte directe de la particulari și parcuri auto
- Detectează: titlu, preț, valută, an, km, combustibil, locație
- Include Early Stopping și salvare în SQLite prin `save_scraped_data` cu source='publi24'
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
MAX_PAGES_DEFAULT_FULL = 25


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text_clean = str(text).split(',')[0].replace('.', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text_clean))
    return int(digits) if digits else None


def parse_publi24_card(soup_item) -> Dict[str, Any]:
    """Parsează un anunț auto din lista Publi24.ro."""
    try:
        link_el = soup_item.find('a', href=lambda h: h and '/anunturi/' in str(h) and '.html' in str(h))
        if not link_el:
            return {}

        url = link_el.get('href', '')
        if not url.startswith('http'):
            url = f"https://www.publi24.ro{url}"

        # Extragere car_id
        id_match = re.search(r'([a-f0-9]{24,32})', url) or re.search(r'-(\d+)\.html', url)
        car_id = id_match.group(1) if id_match else hashlib.md5(url.encode()).hexdigest()[:10]

        title = link_el.get_text(strip=True) or link_el.get('title')
        if not title:
            t_el = soup_item.find('h2') or soup_item.find('h3')
            title = t_el.get_text(strip=True) if t_el else None

        price_el = soup_item.find('strong', class_=lambda c: c and 'price' in str(c).lower()) or soup_item.find('span', class_=lambda c: c and 'price' in str(c).lower())
        raw_price = price_el.get_text(strip=True) if price_el else ""

        price = normalize_number(raw_price)
        currency = "RON" if "ron" in raw_price.lower() or "lei" in raw_price.lower() else "EUR"

        text_block = soup_item.get_text(" ", strip=True)

        year_match = re.search(r'\b(20[0-2]\d)\b', text_block)
        year = int(year_match.group(1)) if year_match else None

        km_match = re.search(r'([\d\.\s]+)\s*km\b', text_block, re.IGNORECASE)
        mileage_km = normalize_number(km_match.group(1)) if km_match else None

        fuel_type = None
        if re.search(r'\b(diesel|motorina)\b', text_block, re.IGNORECASE):
            fuel_type = "Diesel"
        elif re.search(r'\b(benzina|benzină)\b', text_block, re.IGNORECASE):
            fuel_type = "Benzina"
        elif re.search(r'\b(hibrid|hybrid)\b', text_block, re.IGNORECASE):
            fuel_type = "Hibrid"
        elif re.search(r'\b(electric[a]?)\b', text_block, re.IGNORECASE):
            fuel_type = "Electric"

        loc_el = soup_item.find('span', class_=lambda c: c and ('location' in str(c).lower() or 'city' in str(c).lower()))
        location = loc_el.get_text(strip=True) if loc_el else "România"

        return {
            "car_id": car_id,
            "url": url,
            "title": title,
            "price": price,
            "currency": currency,
            "year": year,
            "mileage_km": mileage_km,
            "fuel_type": fuel_type,
            "seller": "Publi24 Vânzător",
            "seller_type": "Particular",
            "location": location,
            "scrape_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }
    except Exception:
        return {}


def scrape_publi24(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: Optional[bool] = None) -> pd.DataFrame:
    """Scrapează cele mai recente anunțuri de pe Publi24.ro."""
    if early_stopping is None:
        early_stopping = daily_mode
    if not daily_mode and max_pages == MAX_PAGES_DEFAULT_DAILY:
        max_pages = MAX_PAGES_DEFAULT_FULL
    logger.info(f"[publi24] Pornim culegerea datelor pentru primele {max_pages} pagini...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })

    known_cars = get_known_car_ids_and_prices(source="publi24") if early_stopping else {}
    results = []
    consecutive_known = 0

    base_url = "https://www.publi24.ro/anunturi/auto-moto-ambarcatiuni/autoturisme/?pag={}"

    for page_num in range(1, max_pages + 1):
        url = base_url.format(page_num)
        try:
            time.sleep(random.uniform(1.2, 2.5))
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[publi24] Status {resp.status_code} la pagina {page_num}.")
                break

            soup = BeautifulSoup(resp.text, 'lxml' if 'lxml' in sys.modules else 'html.parser')
            items = soup.find_all('li', class_=lambda c: c and 'listing-item' in str(c).lower())
            if not items:
                items = soup.find_all('div', class_=lambda c: c and 'listing' in str(c).lower())

            logger.info(f"[publi24] Pagina {page_num}: detectate {len(items)} elemente.")

            for it in items:
                car = parse_publi24_card(it)
                if car and car.get('title') and car.get('price'):
                    cid = f"publi24_{car['car_id']}"
                    if early_stopping and cid in known_cars:
                        consecutive_known += 1
                        if consecutive_known >= 10:
                            logger.info(f"[publi24] Early stopping activat la pagina {page_num}.")
                            break
                    else:
                        consecutive_known = 0

                    results.append(car)

            if consecutive_known >= 10:
                break

        except Exception as e:
            logger.error(f"[publi24] Eroare la pagina {page_num}: {e}")
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.drop_duplicates(subset=['car_id'])
        stats = save_scraped_data(df, source_name="publi24")
        logger.info(f"[publi24] Salvare finalizată: {len(df)} mașini ({stats.get('new', 0)} noi).")
    else:
        logger.warning("[publi24] Nu s-au extras date în această sesiune.")

    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER PUBLI24 ===")
    df_pub = scrape_publi24(max_pages=1, early_stopping=False)
    print(f"Extrase: {len(df_pub)} anunțuri.")
