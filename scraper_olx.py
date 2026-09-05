import os
import time
import random
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
MAX_WORKERS = 3  # Numarul de browsere deschise simultan (Atenție la OLX, maxim 3!)
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
    # Eliminăm puncte, virgule, spații și caractere invizibile
    digits = ''.join(filter(str.isdigit, text.replace('.', '').replace(',', '').replace(' ', '').replace('\xa0', '')))
    return int(digits) if digits else None


# --- Parsing Card HTML ---
def parse_olx_card(element) -> Dict[str, Any]:
    # Preluam HTML-ul elementului din Playwright
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    try:
        # Cautam direct div-ul principal al cardului
        div = soup.select_one('div[data-cy="l-card"]') or soup

        # URL și car_id
        link_el = div.select_one('a[href*="/d/oferta/"]')
        url = link_el.get('href') if link_el else None
        if url and not url.startswith('http'):
            url = "https://www.olx.ro" + url
        data['url'] = url

        # Extragem ID-ul din URL
        data['car_id'] = None
        if url:
            match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
            if match:
                data['car_id'] = match.group(1)

        # Title
        title_el = div.select_one('h6')  # OLX a schimbat recent H4 în H6 pe unele teme
        if not title_el:
            title_el = div.select_one('h4')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        # Price
        price_el = div.select_one('p[data-testid="ad-price"]')
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data[
            'currency'] = 'EUR' if price_text and '€' in price_text else 'RON' if price_text and 'lei' in price_text.lower() else None

        # Location
        loc_el = div.select_one('p[data-testid="location-date"]')
        data['location'] = loc_el.get_text(strip=True).split('-')[0].strip() if loc_el else None

        # Year & Mileage (Pe OLX apar ca un sir de genul "2019 - 170 000 km")
        data['year'] = None
        data['mileage_km'] = None

        info_tags = div.select('span[class*="css-"]')  # Căutăm span-urile cu detalii
        for tag in info_tags:
            text = tag.get_text(strip=True).lower()
            if 'km' in text:
                # Daca e un text compus gen "2019 - 150000 km"
                parts = text.replace('-', ' ').split()
                try:
                    # Prima parte e de obicei anul
                    if len(parts[0]) == 4 and parts[0].isdigit():
                        data['year'] = int(parts[0])
                    # Extragem numerele pt KM
                    km_text = "".join(filter(str.isdigit, text[4:]))
                    data['mileage_km'] = int(km_text) if km_text else None
                except Exception:
                    pass
            elif len(text) == 4 and text.isdigit() and not data['year']:
                # Dacă e doar anul izolat
                data['year'] = int(text)

        # Setam coloanele lipsa
        data['seller'] = None
        data['seller_type'] = None
        data['description'] = None
        data['fuel_type'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card OLX: {e}")
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

        # Blocăm descărcarea imaginilor și reclamelor (VITAL pentru OLX)
        page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ["image", "stylesheet", "media", "font"]
        else route.continue_()
                   )

        for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
            # Parametrizați URL-ul pentru anul extras
            url = f"https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/bucuresti/?currency=EUR&search%5Border%5D=filter_float_price:asc&search%5Bfilter_float_price:to%5D=20000&search%5Bfilter_float_year:from%5D={year}&search%5Bfilter_float_year:to%5D={year}&search%5Bfilter_float_rulaj_pana:to%5D=250000&page={page_num}"

            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False

            # --- SISTEM DE RETRY ---
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)

                    # Așteptăm elementul de card OLX (data-cy="l-card")
                    page.wait_for_selector('div[data-cy="l-card"]', timeout=15000)
                    page_success = True
                    break  # A mers perfect

                except Exception as e:
                    page_title = page.title()
                    print(f"[An {year}] (Încercarea {attempt + 1}/{max_retries}) Timeout la pag {page_num}. Titlu: '{page_title}'")

                    # OLX aruncă adesea "Interzis" sau "ERROR" dacă detectează boți sau e încărcat
                    if "interzis" in page_title.lower() or "forbidden" in page_title.lower() or "error" in page_title.lower():
                        print(f"  -> OLX ne-a oprit temporar pe acest thread. Așteptăm o gură de aer...")
                        random_sleep(15.0, 20.0)  # Pauză mai mare la block OLX
                    else:
                        random_sleep(4.0, 7.0)

            if not page_success:
                print(f"[An {year}] 0 anunțuri pe pagina {page_num} după {max_retries} încercări. Oprim anul.")
                break

            # --- EXTRAGERE EFECTIVĂ ---
            try:
                cards = page.query_selector_all('div[data-cy="l-card"]')

                if len(cards) == 0:
                    break

                for card in cards:
                    listing = parse_olx_card(card)
                    if listing.get('car_id') and listing['car_id'] not in visited_ids:
                        results.append(listing)
                        visited_ids.add(listing['car_id'])

                # Pauză obligatorie mai mare pe OLX
                random_sleep(3.0, 5.0)

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

    print(f"[*] Incepem scraping concurent pentru OLX folosind {MAX_WORKERS} workers...")

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
        print("[!] Nu s-au extras date de pe OLX.")

    end_time = time.time()
    print(f"\n[*] Execuție terminată în {(end_time - start_time) / 60:.2f} minute.")


if __name__ == "__main__":
    main()