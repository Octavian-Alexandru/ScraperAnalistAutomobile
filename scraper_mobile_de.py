# FILE: scraper_mobile_de.py
"""
Scraper pentru Mobile.de (Piața Auto din Germania).
Cea mai mare platformă auto din Europa. Esențial pentru:
- Comparație cross-border (România vs Germania)
- Oportunități de import profitabil direct din Germania
- Salvare în SQLite prin `db_helper.save_scraped_data` cu source='mobile_de'
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
import cloudscraper

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
    digits = ''.join(filter(str.isdigit, str(text)))
    return int(digits) if digits else None


def parse_mobile_card(soup_item) -> Dict[str, Any]:
    """Extrage detaliile unui card de autoturism de pe Mobile.de."""
    try:
        link_el = soup_item.find('a', href=lambda h: h and '/auto-inserat/' in h)
        if not link_el:
            link_el = soup_item.find('a', href=lambda h: h and 'id=' in h)
        if not link_el:
            return {}

        url = link_el.get('href', '')
        if not url.startswith('http'):
            url = f"https://www.mobile.de{url}"

        # Extragere car_id din URL
        id_match = re.search(r'id=(\d+)', url) or re.search(r'/auto-inserat/.*?/(\d+)\.html', url)
        car_id = id_match.group(1) if id_match else hashlib.md5(url.encode()).hexdigest()[:10]

        title_el = soup_item.find('h2') or soup_item.find('span', class_=lambda c: c and 'headline' in str(c).lower())
        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)

        price_el = soup_item.find('span', class_=lambda c: c and 'price' in str(c).lower())
        price = normalize_number(price_el.get_text(strip=True)) if price_el else None

        # Parametri tehnici (an, km, combustibil, transmisie)
        year = None
        mileage_km = None
        fuel_type = None

        text_block = soup_item.get_text(" ", strip=True)

        # An fabricație (ex: 05/2019 sau 2019)
        year_match = re.search(r'\b(?:0[1-9]|1[0-2])/(\d{4})\b', text_block) or re.search(r'\b(20[0-2]\d)\b', text_block)
        if year_match:
            year = int(year_match.group(1))

        # Kilometraj (ex: 145.000 km)
        km_match = re.search(r'([\d\.\s]+)\s*km\b', text_block, re.IGNORECASE)
        if km_match:
            mileage_km = normalize_number(km_match.group(1))

        # Combustibil
        if re.search(r'\b(diesel)\b', text_block, re.IGNORECASE):
            fuel_type = "Diesel"
        elif re.search(r'\b(benzin|petrol)\b', text_block, re.IGNORECASE):
            fuel_type = "Benzina"
        elif re.search(r'\b(hybrid|elektro/benzin|elektro/diesel)\b', text_block, re.IGNORECASE):
            fuel_type = "Hibrid"
        elif re.search(r'\b(elektro|electric)\b', text_block, re.IGNORECASE):
            fuel_type = "Electric"

        location_el = soup_item.find('div', class_=lambda c: c and 'seller' in str(c).lower())
        location = location_el.get_text(strip=True) if location_el else "Germania"

        return {
            "car_id": car_id,
            "url": url,
            "title": title,
            "price": price,
            "currency": "EUR",
            "year": year,
            "mileage_km": mileage_km,
            "fuel_type": fuel_type,
            "seller": "Mobile.de Dealer",
            "seller_type": "Dealer",
            "location": location,
            "scrape_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }
    except Exception:
        return {}


def scrape_mobile_de(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: Optional[bool] = None) -> pd.DataFrame:
    """
    Scrapează cele mai recente oferte de pe Mobile.de folosind cloudscraper cu anti-bot bypass.
    """
    if early_stopping is None:
        early_stopping = daily_mode
    if not daily_mode and max_pages == MAX_PAGES_DEFAULT_DAILY:
        max_pages = MAX_PAGES_DEFAULT_FULL
    logger.info(f"[mobile_de] Pornim scraping pentru primele {max_pages} pagini...")
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )

    known_cars = get_known_car_ids_and_prices(source="mobile_de") if early_stopping else {}
    results = []
    consecutive_known = 0

    # Căutare mașini recente (an >= 2014) sortate descrescător după data adăugării
    base_url = "https://suchen.mobile.de/fahrzeuge/search.html?dam=0&isSearchRequest=true&minFirstRegistrationDate=2014-01-01&s=Car&sb=doc&vc=Car&pageNumber={}"

    for page_num in range(1, max_pages + 1):
        url = base_url.format(page_num)
        try:
            time.sleep(random.uniform(1.5, 3.0))
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"[mobile_de] Status {resp.status_code} la pagina {page_num}.")
                break

            soup = BeautifulSoup(resp.text, 'lxml' if 'lxml' in sys.modules else 'html.parser')
            # Căutăm cardurile de anunțuri
            items = soup.find_all('article') or soup.find_all('div', class_=lambda c: c and 'result-item' in str(c).lower())
            if not items:
                items = soup.find_all('div', class_=lambda c: c and 'cBox' in str(c))

            logger.info(f"[mobile_de] Pagina {page_num}: găsite {len(items)} elemente.")
            page_extracted = 0

            for it in items:
                car = parse_mobile_card(it)
                if car and car.get('title') and car.get('price'):
                    cid = f"mobile_de_{car['car_id']}"
                    if early_stopping and cid in known_cars:
                        consecutive_known += 1
                        if consecutive_known >= 12:
                            logger.info(f"[mobile_de] Early stopping activat la pagina {page_num} (12 anunțuri deja cunoscute).")
                            break
                    else:
                        consecutive_known = 0

                    results.append(car)
                    page_extracted += 1

            if consecutive_known >= 12 or len(items) == 0:
                break

        except Exception as e:
            logger.error(f"[mobile_de] Eroare la pagina {page_num}: {e}")
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.drop_duplicates(subset=['car_id'])
        stats = save_scraped_data(df, source_name="mobile_de")
        logger.info(f"[mobile_de] Salvare SQLite finalizată: {len(df)} mașini ({stats.get('new', 0)} noi).")
    else:
        logger.warning("[mobile_de] Nu s-au extras date în această sesiune.")

    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER MOBILE.DE ===")
    df_res = scrape_mobile_de(max_pages=1, early_stopping=False)
    print(f"Extrase: {len(df_res)} anunțuri.")
