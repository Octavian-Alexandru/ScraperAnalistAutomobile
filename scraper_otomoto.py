# FILE: scraper_otomoto.py
"""
Scraper pentru Otomoto.pl — Piața Auto #1 din Polonia (+250.000 mașini second-hand).
Polonia este cel mai mare hub auto de tranzit și import din Europa Centrală și de Est către România.
Avantaje import Polonia:
- Prețuri extrem de competitive la autoturisme rulate
- Verificare guvernamentală gratuită și strictă prin CEPiK / HistoriaPojazdu.gov.pl
- Emitere frecventă de factură cu TVA deductibil (Faktura VAT 23% / Netto VIES)
- Distanță rezonabilă (Cracovia / Katowice / Varșovia: 800 - 1.200 km până la granița RO)

Extrage date direct din structura JSON structurată (Next.js __NEXT_DATA__ / urqlState):
- car_id, titlu, pret (convertit automat din PLN în EUR), an, km, combustibil, capacitate cilindrica,
  vânzător, TVA deductibil, CEPiK verified, locație, link, country='PL'
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
from currency_helper import convert_to_eur
from logger_config import logger

BASE_URL = "https://www.otomoto.pl"
SEARCH_URL = "https://www.otomoto.pl/osobowe?page={page}"

MAX_PAGES_DEFAULT_DAILY = 5
MAX_PAGES_DEFAULT_FULL = 25


def parse_otomoto_item(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parsează un anunț auto din payload-ul JSON Otomoto.pl."""
    try:
        ad_id = str(node.get("id", "")).strip()
        if not ad_id:
            return None

        title = node.get("title", "").strip()
        if not title:
            return None

        # Preț și valută
        price_obj = node.get("price", {})
        amt_obj = price_obj.get("amount", {})
        raw_price_val = amt_obj.get("units") or amt_obj.get("value")
        currency = (amt_obj.get("currencyCode") or "PLN").upper().strip()

        if not raw_price_val:
            return None

        try:
            raw_price = float(raw_price_val)
            if raw_price <= 0:
                return None
        except (ValueError, TypeError):
            return None

        # Conversie în EUR pentru uniformitate cu piețele europene
        if currency == "PLN":
            price_eur = convert_to_eur(raw_price, "PLN")
        elif currency == "EUR":
            price_eur = round(raw_price, 2)
        else:
            price_eur = convert_to_eur(raw_price, currency)

        if price_eur < 500 or price_eur > 300000:
            return None

        # Parametri tehnici
        raw_params = node.get("parameters", [])
        params = {}
        for p in raw_params:
            k = p.get("key")
            v = p.get("value")
            if k and v is not None:
                params[k] = v

        # Kilometraj
        mileage_km = None
        km_raw = params.get("mileage")
        if km_raw:
            try:
                mileage_km = int(float(str(km_raw).replace(" ", "")))
            except ValueError:
                mileage_km = None

        # An fabricație
        year = None
        year_raw = params.get("year")
        if year_raw:
            try:
                year = int(year_raw)
                if year < 1990 or year > 2026:
                    year = None
            except ValueError:
                year = None

        # Combustibil
        fuel_raw = str(params.get("fuel_type", "")).lower()
        if "diesel" in fuel_raw:
            fuel_type = "Diesel"
        elif any(h in fuel_raw for h in ["hybrid", "hybryda", "mhev", "phev"]):
            fuel_type = "Hybrid"
        elif any(e in fuel_raw for e in ["electric", "elektryczny"]):
            fuel_type = "Electric"
        elif "lpg" in fuel_raw or "cng" in fuel_raw or "gaz" in fuel_raw:
            fuel_type = "GPL"
        elif any(b in fuel_raw for b in ["petrol", "benzyna"]):
            fuel_type = "Benzina"
        else:
            fuel_type = "Benzina"

        # Capacitate cilindrică
        engine_size = None
        cc_raw = params.get("engine_capacity")
        if cc_raw:
            try:
                cc = float(cc_raw)
                if cc > 400:
                    engine_size = round(cc / 1000.0, 1)
            except ValueError:
                engine_size = None

        # Cutie de viteze
        gearbox_raw = str(params.get("gearbox", "")).lower()
        transmission = "Automata" if "auto" in gearbox_raw else ("Manuala" if "manual" in gearbox_raw else None)

        # TVA deductibil / Factură
        price_badges = price_obj.get("badges", [])
        has_vat_deductible = 1 if "INVOICE_ISSUED" in price_badges or price_obj.get("netPrice") is not None else 0

        # Locație
        loc_obj = node.get("location", {})
        city_name = loc_obj.get("city", {}).get("name", "") if isinstance(loc_obj.get("city"), dict) else ""
        region_name = loc_obj.get("region", {}).get("name", "") if isinstance(loc_obj.get("region"), dict) else ""
        loc_parts = [p for p in [city_name, region_name, "Polonia"] if p]
        location = ", ".join(loc_parts) if loc_parts else "Polonia"

        # Vânzător
        seller_obj = node.get("seller", {})
        seller_type_name = seller_obj.get("__typename", "")
        seller_type = "Dealer" if "Professional" in seller_type_name else "Particular"
        seller = f"Otomoto {seller_type} ({city_name or 'PL'})"

        # URL anunț
        url = node.get("url", "")
        if url and not url.startswith("http"):
            url = f"{BASE_URL}{url}"

        # Imagine thumbnail
        thumbnail = node.get("thumbnail", {}).get("x1") if isinstance(node.get("thumbnail"), dict) else None

        return {
            "car_id": f"otomoto_{ad_id}",
            "title": title,
            "price": price_eur,
            "currency": "EUR",
            "mileage_km": mileage_km,
            "year": year,
            "fuel_type": fuel_type,
            "engine_size": engine_size,
            "transmission": transmission,
            "seller": seller,
            "seller_type": seller_type,
            "location": location,
            "country": "PL",
            "url": url or f"{BASE_URL}/oferta/{ad_id}",
            "image_url": thumbnail,
            "has_vat_deductible": has_vat_deductible,
            "scrape_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }

    except Exception as e:
        logger.debug(f"[otomoto] Eroare la parsarea anuntului {node.get('id')}: {e}")
        return None


def scrape_otomoto(daily_mode: bool = True, max_pages: int = MAX_PAGES_DEFAULT_DAILY, early_stopping: Optional[bool] = None) -> pd.DataFrame:
    """
    Scrapează cele mai recente anunțuri de pe Otomoto.pl folosind cloudscraper.
    Datele sunt extrase din state-ul GraphQL / Next.js urqlState pentru viteză mare și stabilitate.
    """
    if early_stopping is None:
        early_stopping = daily_mode
    if not daily_mode and max_pages == MAX_PAGES_DEFAULT_DAILY:
        max_pages = MAX_PAGES_DEFAULT_FULL

    logger.info(f"[otomoto] Pornire scraping pentru piața auto din Polonia (max {max_pages} pagini, daily={daily_mode})...")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )

    known_cars = get_known_car_ids_and_prices(source="otomoto") if early_stopping else {}
    results = []
    consecutive_known = 0

    for page_num in range(1, max_pages + 1):
        url = SEARCH_URL.format(page=page_num)
        try:
            time.sleep(random.uniform(1.2, 2.4))
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"[otomoto] Status {resp.status_code} la pagina {page_num}.")
                break

            soup = BeautifulSoup(resp.text, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            if not script_tag or not script_tag.string:
                logger.warning(f"[otomoto] Nu s-a gasit __NEXT_DATA__ la pagina {page_num}.")
                break

            data = json.loads(script_tag.string)
            urql_state = data.get('props', {}).get('pageProps', {}).get('urqlState', {})

            items = []
            for _, v in urql_state.items():
                data_str = v.get('data')
                if data_str and 'advertSearch' in data_str:
                    try:
                        inner = json.loads(data_str)
                        edges = inner.get('advertSearch', {}).get('edges', [])
                        items = [e.get('node', {}) for e in edges if e.get('node')]
                        if items:
                            break
                    except Exception:
                        pass

            if not items:
                logger.info(f"[otomoto] Nu s-au detectat anunturi in urqlState la pagina {page_num}.")
                break

            logger.info(f"[otomoto] Pagina {page_num}: {len(items)} anunturi detectate.")
            page_extracted = 0

            for it in items:
                car = parse_otomoto_item(it)
                if car and car.get('price'):
                    cid = car['car_id']
                    if early_stopping and cid in known_cars:
                        consecutive_known += 1
                        if consecutive_known >= 12:
                            logger.info(f"[otomoto] Early stopping activat la pagina {page_num} (12 anunturi cunoscute).")
                            break
                    else:
                        consecutive_known = 0

                    results.append(car)
                    page_extracted += 1

            if consecutive_known >= 12:
                break

        except Exception as e:
            logger.error(f"[otomoto] Eroare la pagina {page_num}: {e}")
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.drop_duplicates(subset=['car_id'])
        stats = save_scraped_data(df, source_name="otomoto")
        logger.info(f"[otomoto] Salvare SQLite finalizata: {len(df)} masini ({stats.get('new', 0)} noi).")
    else:
        logger.warning("[otomoto] Nu s-au extras anunturi in aceasta sesiune.")

    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER OTOMOTO (POLONIA) ===")
    df_res = scrape_otomoto(daily_mode=True, max_pages=1, early_stopping=False)
    print(f"Extrase: {len(df_res)} autoturisme din Polonia.")
    if not df_res.empty:
        print(df_res[['title', 'price', 'mileage_km', 'year', 'fuel_type', 'location', 'country']].head(5))
