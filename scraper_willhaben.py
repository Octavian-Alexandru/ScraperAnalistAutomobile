# FILE: scraper_willhaben.py
"""
Scraper pentru Willhaben.at — Piața Auto #1 din Austria (+100.000 mașini second-hand).
Austria este cea mai apropiată piață vestică de România (Viena e la doar 800 - 1.050 km).
Avantaje import Austria:
- Verificare tehnică periodică foarte strictă ("Pickerl" §57a KFG)
- Costuri reduse de transport (cu 30-40% mai mici decât din Germania de Nord sau Olanda)
- Mașini bine întreținute cu istoric verificabil

Extrage datele direct din payload-ul JSON structurat (__NEXT_DATA__) pentru precizie 100%:
- car_id, titlu, pret (EUR), an, km, combustibil, capacitate cilindrica, dealer/privat, locatie, url, country='AT'
"""

import os
import sys
import json
import time
import random
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

BASE_URL = "https://www.willhaben.at"
SEARCH_URL = "https://www.willhaben.at/iad/gebrauchtwagen/auto/gebrauchtwagenboerse?page={page}&rows=30"

MAX_PAGES_DEFAULT_DAILY = 5
MAX_PAGES_DEFAULT_FULL = 25


def parse_willhaben_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parsează un anunț auto din payload-ul JSON Willhaben."""
    try:
        car_id = str(item.get("id", "")).strip()
        if not car_id:
            return None

        # Extragere atribute cheie
        raw_attrs = item.get("attributes", {}).get("attribute", [])
        attrs = {}
        for a in raw_attrs:
            name = a.get("name")
            vals = a.get("values", [])
            if name and vals:
                attrs[name] = vals[0]

        # Titlu
        title = attrs.get("HEADING") or item.get("description", "")
        if not title:
            return None

        # Preț
        price_raw = attrs.get("PRICE") or attrs.get("PRICE/AMOUNT")
        if not price_raw:
            return None
        try:
            price = float(price_raw)
            if price < 500 or price > 250000:
                return None
        except ValueError:
            return None

        # Kilometraj
        km_raw = attrs.get("MILEAGE")
        mileage_km = None
        if km_raw:
            try:
                mileage_km = int(float(km_raw))
            except ValueError:
                mileage_km = None

        # An fabricație
        year_raw = attrs.get("YEAR_MODEL")
        year = None
        if year_raw:
            try:
                year = int(year_raw)
                if year < 1990 or year > 2026:
                    year = None
            except ValueError:
                year = None

        # Combustibil
        fuel_type = attrs.get("ENGINE/FUEL_RESOLVED") or "Benzina"
        if "diesel" in fuel_type.lower():
            fuel_type = "Diesel"
        elif any(h in fuel_type.lower() for h in ["hybrid", "hibrid"]):
            fuel_type = "Hybrid"
        elif "elektro" in fuel_type.lower() or "electric" in fuel_type.lower():
            fuel_type = "Electric"
        elif "benzin" in fuel_type.lower():
            fuel_type = "Benzina"

        # Capacitate cilindrică
        engine_size = None
        cc_raw = attrs.get("ENGINEVOLUME")
        if cc_raw:
            try:
                engine_size = round(float(cc_raw) / 1000.0, 1)
            except ValueError:
                engine_size = None

        # Locație și regiune
        loc_city = attrs.get("LOCATION", "Austria")
        loc_state = attrs.get("STATE", "")
        postcode = attrs.get("POSTCODE", "")
        location_parts = [p for p in [loc_city, loc_state, f"AT-{postcode}" if postcode else ""] if p]
        location = ", ".join(location_parts) if location_parts else "Austria"

        # Vânzător
        is_private = attrs.get("ISPRIVATE") == "1"
        seller_type = "Particular" if is_private else "Dealer"
        seller = attrs.get("ORGNAME") if not is_private else "Particular (Austria)"

        # URL complet
        seo_url = attrs.get("SEO_URL", "")
        if seo_url:
            url = f"{BASE_URL}/iad/{seo_url}" if not seo_url.startswith("http") else seo_url
        else:
            url = f"{BASE_URL}/iad/object?adId={car_id}"

        return {
            "car_id": f"willhaben_{car_id}",
            "title": title.strip(),
            "price": price,
            "currency": "EUR",
            "mileage_km": mileage_km,
            "year": year,
            "fuel_type": fuel_type,
            "engine_size": engine_size,
            "seller": seller or "Willhaben Seller",
            "seller_type": seller_type,
            "location": location,
            "country": "AT",
            "url": url,
            "scrape_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }

    except Exception as e:
        logger.debug(f"[willhaben] Eroare la parsarea anuntului: {e}")
        return None


def scrape_willhaben(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: Optional[bool] = None) -> pd.DataFrame:
    """
    Scrapează cele mai recente anunțuri de pe Willhaben.at folosind cloudscraper.
    Extrage datele din structura JSON __NEXT_DATA__ pentru viteză și fidelitate maximă.
    """
    if early_stopping is None:
        early_stopping = daily_mode
    if not daily_mode and max_pages == MAX_PAGES_DEFAULT_DAILY:
        max_pages = MAX_PAGES_DEFAULT_FULL

    logger.info(f"[willhaben] Pornire scraping pentru piața auto din Austria (max {max_pages} pagini, daily={daily_mode})...")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )

    known_cars = get_known_car_ids_and_prices(source="willhaben") if early_stopping else {}
    results = []
    consecutive_known = 0

    for page_num in range(1, max_pages + 1):
        url = SEARCH_URL.format(page=page_num)
        try:
            time.sleep(random.uniform(1.2, 2.5))
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"[willhaben] Status {resp.status_code} la pagina {page_num}.")
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            if not script_tag or not script_tag.string:
                logger.warning(f"[willhaben] Nu s-a gasit __NEXT_DATA__ la pagina {page_num}.")
                break

            data = json.loads(script_tag.string)
            search_res = data.get('props', {}).get('pageProps', {}).get('searchResult', {})
            adv_list = search_res.get('advertSummaryList', {})
            items = adv_list.get('advertSummary', []) if isinstance(adv_list, dict) else []

            if not items:
                logger.info(f"[willhaben] Nu mai exista articole la pagina {page_num}.")
                break

            logger.info(f"[willhaben] Pagina {page_num}: {len(items)} anunturi detectate.")
            page_extracted = 0

            for it in items:
                car = parse_willhaben_item(it)
                if car and car.get('price'):
                    cid = car['car_id']
                    if early_stopping and cid in known_cars:
                        consecutive_known += 1
                        if consecutive_known >= 12:
                            logger.info(f"[willhaben] Early stopping activat la pagina {page_num} (12 anunturi cunoscute).")
                            break
                    else:
                        consecutive_known = 0

                    results.append(car)
                    page_extracted += 1

            if consecutive_known >= 12:
                break

        except Exception as e:
            logger.error(f"[willhaben] Eroare la pagina {page_num}: {e}")
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.drop_duplicates(subset=['car_id'])
        stats = save_scraped_data(df, source_name="willhaben")
        logger.info(f"[willhaben] Salvare SQLite finalizata: {len(df)} masini ({stats.get('new', 0)} noi).")
    else:
        logger.warning("[willhaben] Nu s-au extras anunturi in aceasta sesiune.")

    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER WILLHABEN (AUSTRIA) ===")
    df_res = scrape_willhaben(daily_mode=True, max_pages=1, early_stopping=False)
    print(f"Extrase: {len(df_res)} autoturisme din Austria.")
    if not df_res.empty:
        print(df_res[['title', 'price', 'mileage_km', 'year', 'fuel_type', 'location', 'country']].head(5))
