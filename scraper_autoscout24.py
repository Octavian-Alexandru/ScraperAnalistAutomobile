# FILE: scraper_autoscout24.py
"""
Scraper pentru AutoScout24 — a doua piață germană/europeană majoră (+2M anunțuri active).
Implementează:
1. Parsare HTML a listărilor de pe AutoScout24.com
2. Extracție detaliată: preț, km, an, combustibil, locație (țară/oraș), dealer/privat
3. Anti-bot: delay natural 1.5-3.0s, cloudscraper fallback, User-Agent rotation
4. Suport pentru filtrare pe piața DE/AT/NL/BE (cele mai relevante pentru import RO)
5. Integrare cu cross_border_arbitrage.py pentru delta RO vs EU
"""

import os
import sys
import re
import time
import hashlib
import random
import datetime
from typing import Dict, Any, List, Optional
import requests
import pandas as pd
from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from base_scraper import BaseScraper
from logger_config import logger

# User-Agent-uri specifice pentru piața germană
DE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
]

BASE_URL = "https://www.autoscout24.com"

# Mărci populare cu ID-urile lor pe AutoScout24
BRAND_SLUGS = {
    "bmw": "9", "audi": "9", "mercedes-benz": "47", "volkswagen": "75",
    "opel": "54", "ford": "29", "renault": "60", "peugeot": "56",
    "skoda": "65", "seat": "63", "toyota": "72", "hyundai": "36",
    "kia": "39", "dacia": "21", "volvo": "76", "mazda": "44",
    "nissan": "52", "fiat": "27", "citroen": "18"
}


def normalize_autoscout_price(price_text: str) -> Optional[float]:
    """Normalizează prețul din format AutoScout24 (€ 12.990,-) în float."""
    if not price_text:
        return None
    # Elimină tot ce nu e cifră, virgulă sau punct
    cleaned = re.sub(r'[^\d.,]', '', price_text)
    if not cleaned:
        return None
    # Formatul german: 12.990 (punctul e separator de mii)
    cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_mileage(km_text: str) -> Optional[int]:
    """Normalizează kilometrajul din format AutoScout (123.456 km) în int."""
    if not km_text:
        return None
    cleaned = re.sub(r'[^\d]', '', km_text)
    try:
        val = int(cleaned)
        return val if val < 999999 else None
    except ValueError:
        return None


def parse_autoscout_card(card) -> Optional[Dict[str, Any]]:
    """
    Parsează un card/articol din pagina de rezultate AutoScout24.
    Extrage toate câmpurile relevante pentru baza de date.
    """
    try:
        # URL anunț
        link_el = card.select_one('a[href*="/offers/"]') or card.select_one('a[href*="/cls/"]')
        if not link_el:
            link_el = card.find('a', href=True)
        url = ""
        if link_el and link_el.get('href'):
            href = link_el['href']
            url = href if href.startswith('http') else BASE_URL + href

        # Titlu
        title_el = card.select_one('[data-testid="title"]') or card.select_one('h2') or card.select_one('.ListItem_title__ndA4s')
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            title_el = card.find(['h2', 'h3'])
            title = title_el.get_text(strip=True) if title_el else ""

        # Preț
        price = None
        price_el = card.select_one('[data-testid="price"]') or card.select_one('.Price_price__APlgs')
        if price_el:
            price = normalize_autoscout_price(price_el.get_text(strip=True))
        if not price:
            for el in card.find_all(string=re.compile(r'€|EUR')):
                p = normalize_autoscout_price(str(el))
                if p and p > 500:
                    price = p
                    break

        if not title or not price:
            return None

        # Detalii tehnice (km, an, combustibil)
        details_text = ""
        details_els = card.select('[data-testid="vehicle-details"] span') or card.select('.VehicleDetailTable_item__4n35N')
        if details_els:
            details_text = " ".join([d.get_text(strip=True) for d in details_els])
        else:
            details_text = card.get_text(" ", strip=True)

        # Kilometraj
        mileage = None
        km_match = re.search(r'(\d{1,3}[.\s]?\d{3})\s*km', details_text, re.I)
        if km_match:
            mileage = normalize_mileage(km_match.group(1))

        # An fabricație
        year = None
        year_match = re.search(r'\b(20[0-2]\d|19[9]\d)\b', details_text)
        if year_match:
            year = int(year_match.group(1))
        if not year:
            # Caută în titlu
            ym = re.search(r'\b(20[0-2]\d|19[9]\d)\b', title)
            if ym:
                year = int(ym.group(1))

        # Combustibil
        fuel_type = "Benzina"
        fuel_lower = details_text.lower()
        if any(w in fuel_lower for w in ['diesel', 'tdi', 'cdi', 'hdi', 'dci', 'jtd']):
            fuel_type = "Diesel"
        elif any(w in fuel_lower for w in ['electric', 'elektro', 'ev', 'bev']):
            fuel_type = "Electric"
        elif any(w in fuel_lower for w in ['hybrid', 'phev']):
            fuel_type = "Hybrid"
        elif any(w in fuel_lower for w in ['gpl', 'lpg', 'gas']):
            fuel_type = "GPL"

        # Putere (kW/CP)
        engine_size = None
        kw_match = re.search(r'(\d+)\s*kW', details_text)
        if kw_match:
            kw = int(kw_match.group(1))
            engine_size = round(kw * 0.0136, 1)  # conversie aproximativă kW → L

        # Locație
        location = ""
        loc_el = card.select_one('[data-testid="seller-info"]') or card.select_one('.SellerInfo_address__txoNV')
        if loc_el:
            location = loc_el.get_text(strip=True)

        # Seller type
        seller_type = "Dealer"
        seller_el = card.select_one('[data-testid="seller-info-type"]')
        if seller_el:
            st = seller_el.get_text(strip=True).lower()
            if 'privat' in st or 'private' in st:
                seller_type = "Particular"

        # Generare car_id unic
        car_id_raw = url if url else f"{title}_{price}_{mileage}"
        car_id = hashlib.md5(car_id_raw.encode()).hexdigest()[:16]

        return {
            "car_id": car_id,
            "title": title,
            "price": price,
            "currency": "EUR",
            "mileage_km": mileage,
            "year": year,
            "fuel_type": fuel_type,
            "engine_size": engine_size,
            "seller": seller_type,
            "seller_type": seller_type,
            "location": location or "Germania",
            "url": url,
            "description": details_text[:500]
        }

    except Exception as e:
        logger.debug(f"[AutoScout24] Eroare parsare card: {e}")
        return None


class AutoScout24Scraper(BaseScraper):
    """Scraper dedicat pentru AutoScout24.com — piața europeană de automobile."""

    def __init__(self, db_path=None):
        from db_helper import DB_PATH
        super().__init__(source_name="autoscout24", db_path=db_path or DB_PATH)
        try:
            import cloudscraper
            self.cloud_session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
        except ImportError:
            self.cloud_session = None

    def _get_search_url(self, page: int, country: str = "D") -> str:
        """Construiește URL-ul de căutare AutoScout24."""
        # Căutare generală pe piața germană, sortare după cele mai recente
        return (
            f"{BASE_URL}/lst?atype=C&cy={country}&damaged_listing=exclude"
            f"&desc=1&page={page}&search_id=1&sort=standard&source=listpage_pagination"
            f"&ustate=N%2CU"
        )

    def scrape_listings(
        self,
        max_pages: int = 5,
        daily_mode: bool = True,
        countries: List[str] = None
    ) -> pd.DataFrame:
        """
        Scrapează listările AutoScout24.
        countries: listă de coduri țară (D=Germania, A=Austria, NL=Olanda, B=Belgia)
        """
        if countries is None:
            countries = ["D"]  # implicit doar Germania

        all_cars = []
        total_pages_scraped = 0

        for country in countries:
            logger.info(f"[AutoScout24] Începem scraping pentru țara: {country}, max {max_pages} pagini...")

            consecutive_empty = 0
            for page_num in range(1, max_pages + 1):
                url = self._get_search_url(page_num, country)

                # Delay politicos (mai mare pentru AutoScout24 care are protecție activă)
                self.random_sleep(1.5, 3.0)

                resp = self.fetch_with_retry(url, max_retries=3, timeout=20)
                if not resp:
                    # Fallback la cloudscraper
                    if self.cloud_session:
                        try:
                            self.random_sleep(1.0, 2.0)
                            resp = self.cloud_session.get(url, timeout=25)
                            if resp.status_code != 200:
                                resp = None
                        except Exception:
                            resp = None

                if not resp:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        logger.warning(f"[AutoScout24] 3 pagini consecutive fără răspuns. Oprim pentru {country}.")
                        break
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')

                # AutoScout24 folosește diferite selectori (se schimbă periodic)
                cards = soup.select('article') or soup.select('[data-testid="listing"]') or soup.select('.ListItem_wrapper__TxHWu')

                if not cards:
                    # Fallback: caută orice container cu link către oferte
                    cards = [a.parent for a in soup.find_all('a', href=re.compile(r'/offers/|/cls/'))]

                if not cards:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        logger.warning(f"[AutoScout24] 3 pagini consecutive fără card-uri. Oprim.")
                        break
                    continue

                consecutive_empty = 0
                page_cars = 0

                for card in cards:
                    parsed = parse_autoscout_card(card)
                    if parsed:
                        parsed['source'] = 'autoscout24'
                        parsed['location'] = parsed.get('location', '') or country
                        all_cars.append(parsed)
                        page_cars += 1

                total_pages_scraped += 1
                logger.info(f"[AutoScout24] Pagina {page_num}/{max_pages} ({country}): {page_cars} anunțuri extrase")

                # Early stopping dacă suntem în mod zilnic
                if daily_mode and page_cars == 0:
                    break

        df = pd.DataFrame(all_cars)
        if not df.empty:
            df = df.drop_duplicates(subset=['car_id'])
            stats = self.save_to_db(df)
            logger.info(
                f"[AutoScout24] TOTAL: {len(df)} anunțuri din {total_pages_scraped} pagini "
                f"({stats.get('new', 0)} noi, {stats.get('updated', 0)} actualizate)"
            )
        else:
            logger.warning("[AutoScout24] Nu s-au extras anunțuri.")

        return df


def scrape_autoscout24(max_pages: int = 5, daily_mode: bool = True, countries: List[str] = None) -> pd.DataFrame:
    """Funcție helper pentru apelul simplu din pipeline."""
    scraper = AutoScout24Scraper()
    return scraper.scrape_listings(max_pages=max_pages, daily_mode=daily_mode, countries=countries)


if __name__ == "__main__":
    print("=== TEST SCRAPER AUTOSCOUT24 ===")
    df = scrape_autoscout24(max_pages=2, daily_mode=True)
    print(f"Total anunțuri: {len(df)}")
    if not df.empty:
        print(df[['title', 'price', 'mileage_km', 'year', 'fuel_type']].head(10))
