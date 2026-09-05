import os
import time
import random
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configurare ---
YEARS_TO_SCRAPE = range(2014, 2027)  # De la 2014 la 2026
MAX_PAGES_PER_YEAR = 100  # Limita de pagini per an
MAX_WORKERS = 3  # Numarul de browsere deschise simultan
OUTPUT_DIR = "data"
RAW_XLSX = os.path.join(OUTPUT_DIR, "raw_listings_old.xlsx")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
]

os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- Utils ---
def random_sleep(min_delay=1.0, max_delay=3.0):
    time.sleep(random.uniform(min_delay, max_delay))


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text = text.replace('.', '').replace(',', '').replace(' ', '').replace('€', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


def generate_hash(listing: Dict[str, Any]) -> str:
    key = "_".join(str(listing.get(k, "")) for k in ['car_id', 'title', 'price', 'year', 'mileage_km'])
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


# --- Parsing Card HTML ---
def parse_plusauto_listing(element) -> Dict[str, Any]:
    # Extragem HTML-ul curat prin Playwright
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, 'html.parser')
    data = {}

    try:
        # Căutăm div-ul principal (poate fi chiar 'soup' dacă am selectat bine din Playwright)
        div = soup.select_one('div.card-car-content') or soup

        # car_id
        id_el = div.select_one('div.card-content-misc-right')
        data['car_id'] = id_el.get_text(strip=True).replace('ID anunț:', '').strip() if id_el else None

        # URL & Title
        title_el = div.select_one('div.card-car-content-title a')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        url = title_el.get('href') if title_el else None
        data['url'] = f"https://plus-auto.ro{url}" if url and not url.startswith('http') else url

        # Price
        price_el = div.select_one('div.card-car-content-action-price-normal')
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data['currency'] = 'EUR' if price_text and '€' in price_text else 'RON' if price_text else None

        # Year & Mileage (Din lista de caracteristici)
        data['mileage_km'] = None
        data['year'] = None
        features = div.select('ul.card-car-content-features li.card-car-content-features-item')

        for f in features:
            text = f.get_text(strip=True).lower()
            if 'km' in text:
                data['mileage_km'] = normalize_number(text)
            # Formatul anului la Plus-Auto e de obicei "LL.AAAA" (ex: 05.2019)
            elif bool(re.search(r'\d{2}\.\d{4}', text)):
                parts = text.split('.')
                if len(parts) == 2:
                    data['year'] = normalize_number(parts[1])
            # Sau doar 4 cifre izolate
            elif len(text) == 4 and text.isdigit() and not data['year']:
                data['year'] = int(text)

        # Dealer / Seller
        dealer_el = div.select_one('div.card-car-content-seller a')
        data['seller'] = dealer_el.get_text(strip=True) if dealer_el else "Privat"
        data['seller_type'] = "Dealer" if data['seller'] != "Privat" else "Privat"

        # Location
        loc_el = div.select_one('div.card-content-dealer-location')
        data['location'] = loc_el.get_text(strip=True) if loc_el else None

        # Completăm câmpurile lipsă pentru consistența bazei de date globale
        data['description'] = None
        data['fuel_type'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card Plus-Auto: {e}")
        return {}

    return data


# --- Functia de Scraping per AN (Ruleaza in Thread) ---
def scrape_year(year: int) -> pd.DataFrame:
    delay_start = random.uniform(1.0, 5.0)
    time.sleep(delay_start)

    results = []
    visited_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            ignore_https_errors=True,
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()

        # Blocăm descărcarea imaginilor pentru a mări viteza
        page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ["image", "stylesheet", "media", "font"]
        else route.continue_()
                   )

        for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
            # Formăm URL-ul folosind min și max year pentru a izola căutarea
            url = f"https://plus-auto.ro/autoturisme/?region_id=42,25&firstregistrationyearmin={year}&firstregistrationyearmax={year}&rollingkmmax=250000&salespricemax=20000&page={page_num}"

            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False

            # --- SISTEM DE RETRY ---
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_selector('div.card-car-content', timeout=15000)

                    # Scroll inteligent pentru lazy-loading (dacă site-ul folosește)
                    prev_count = 0
                    for _ in range(10):  # Max 10 scroll-uri
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                        page.wait_for_timeout(800)
                        count = page.locator('div.card-car-content').count()
                        if count == prev_count:
                            break
                        prev_count = count

                    page_success = True
                    break  # A mers perfect

                except Exception as e:
                    print(f"[An {year}] (Încercarea {attempt + 1}/{max_retries}) Timeout la pag {page_num}...")
                    random_sleep(2.0, 4.0)

            if not page_success:
                print(
                    f"[An {year}] 0 anunțuri pe pagina {page_num} după {max_retries} încercări. Ne oprim pentru acest an.")
                break

            # --- EXTRAGERE EFECTIVĂ ---
            try:
                divs = page.query_selector_all('div.card-car-content')

                if len(divs) == 0:
                    break

                for div in divs:
                    listing = parse_plusauto_listing(div)
                    if listing.get('car_id') and listing['car_id'] not in visited_ids:
                        results.append(listing)
                        visited_ids.add(listing['car_id'])

                random_sleep(1.0, 2.5)

            except Exception as e:
                print(f"[An {year}] Eroare la extragerea paginii {page_num}: {e}")
                break

        browser.close()

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunțuri.")
    return pd.DataFrame(results)


# --- MAIN: Executia Concurenta ---
def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent pentru Plus-Auto folosind {MAX_WORKERS} workers...")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(scrape_year, year): year for year in YEARS_TO_SCRAPE}

            for future in as_completed(futures):
                try:
                    df_year = future.result()
                    if not df_year.empty:
                        all_dfs.append(df_year)
                except Exception as exc:
                    print(f"[!] Thread-ul a generat o exceptie: {exc}")

    except KeyboardInterrupt:
        print("\n[!] Ai apăsat Ctrl+C! Oprim firele de execuție și salvăm ce am găsit până acum...")

    # --- SALVARE SI CURATARE ---
    if all_dfs:
        print("\n[*] Combinam rezultatele...")
        final_df = pd.concat(all_dfs, ignore_index=True)

        initial_len = len(final_df)
        final_df.drop_duplicates(subset=['title', 'price', 'mileage_km', 'year'], inplace=True)
        print(f"[!] Am eliminat {initial_len - len(final_df)} duplicate extrase in aceasta sesiune.")

        cols = ['car_id', 'title', 'seller', 'location', 'price', 'currency', 'fuel_type', 'description',
                'mileage_km', 'year', 'seller_type', 'url', 'scrape_date']

        cols_to_keep = [c for c in cols if c in final_df.columns]
        final_df = final_df[cols_to_keep]

        if os.path.exists(RAW_XLSX):
            old_df = pd.read_excel(RAW_XLSX)
            combined_df = pd.concat([old_df, final_df], ignore_index=True)
            combined_df.drop_duplicates(subset=['title', 'price', 'mileage_km', 'year'], inplace=True)
            combined_df.to_excel(RAW_XLSX, index=False)
            print(f"[+] Salvat in {RAW_XLSX}. Total anunțuri în DB: {len(combined_df)}")
        else:
            final_df.to_excel(RAW_XLSX, index=False)
            print(f"[+] Fișier creat: {RAW_XLSX}. Total: {len(final_df)}")
    else:
        print("[!] Nu s-au extras date.")

    end_time = time.time()
    print(f"\n[*] Execuție terminată în {(end_time - start_time) / 60:.2f} minute.")


if __name__ == "__main__":
    main()