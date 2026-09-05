import os
import time
import random
import pandas as pd
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configurare ---
YEARS_TO_SCRAPE = range(2014, 2027)  # 2014 - 2026
MAX_PAGES_PER_YEAR = 100  # Seteaza o limita ca sa nu mearga la infinit
MAX_WORKERS = 3  # Cate ferestre sa deschida simultan
OUTPUT_DIR = "data"
RAW_XLSX = os.path.join(OUTPUT_DIR, "raw_listings_old.xlsx")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
]

os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- Functii Utilitare ---
def random_sleep(min_delay=2.0, max_delay=4.0):
    time.sleep(random.uniform(min_delay, max_delay))


def normalize_number(text: Optional[str]) -> Optional[int]:
    if not text: return None
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


# --- Parsare Card HTML ---
def parse_cautimasina_listing(element) -> Dict[str, Any]:
    # Preluam HTML-ul elementului din Playwright
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, 'html.parser')
    data = {}

    try:
        a_tag = soup.find('a') if soup.name != 'a' else soup
        url = a_tag.get('href') if a_tag else None
        data['url'] = f"https://cautimasina.ro{url}" if url and not url.startswith('http') else url
        data['car_id'] = url.split('-')[-1].split('?')[0] if url else None

        title_el = soup.find('h3')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        data['year'] = None
        if data['title']:
            year_match = re.search(r'\b(19|20)\d{2}\b', data['title'])
            if year_match: data['year'] = int(year_match.group(0))

        price_el = soup.find('p', class_=lambda c: c and 'text-2xl' in c)
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data[
            'currency'] = 'EUR' if price_text and 'EUR' in price_text.upper() else 'RON' if price_text and 'RON' in price_text.upper() else None

        data['mileage_km'] = None
        data['fuel_type'] = None
        spans = soup.find_all('span')
        for span in spans:
            text = span.get_text(strip=True).lower()
            if 'km' in text:
                data['mileage_km'] = normalize_number(text)
            elif text in ['diesel', 'benzina', 'benzină', 'hibrid', 'electric']:
                data['fuel_type'] = text.capitalize()

        data['location'] = None
        data['seller'] = None
        data['seller_type'] = None
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card CautiMasina: {e}")
        return {}

    return data


# --- Functia de Scraping per AN (Asta ruleaza in Thread) ---
def scrape_year(year: int) -> pd.DataFrame:
    delay_start = random.uniform(1.0, 6.0)
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
            url = f"https://cautimasina.ro/anunturi?adCountry=ro&maxKm=250000&maxPrice=20000&maxYear={year}&minYear={year}&sort=3&page={page_num}"
            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False

            # --- SISTEM DE RETRY ---
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)

                    # CautiMasina are o clasă specifică pentru anunțuri: 'a.group'
                    # Așteptăm să apară cel puțin unul pe pagină
                    page.wait_for_selector('a.group', timeout=15000)
                    page_success = True
                    break  # A mers, iesim din bucla de retry
                except Exception as e:
                    page_title = page.title()
                    print(
                        f"[An {year}] (Încercarea {attempt + 1}/{max_retries}) Timeout la pag {page_num}. Titlu: '{page_title}'")

                    if "moment" in page_title.lower() or "cloudflare" in page_title.lower():
                        print(f"  -> Posibil blocaj Cloudflare detectat!")

                    random_sleep(3.0, 6.0)  # Pauză mai lungă la CautiMasina înainte de retry

            # Dacă nu s-a încărcat după 3 încercări, ne oprim pentru anul acesta
            if not page_success:
                print(
                    f"[An {year}] Nu s-au gasit anunțuri pe pag {page_num} după {max_retries} încercări (posibil block sau final lista). Oprim anul.")
                break

            # --- EXTRAGERE EFECTIVĂ ---
            try:
                article_tags = page.query_selector_all('a.group')

                if len(article_tags) == 0:
                    break

                for art in article_tags:
                    listing = parse_cautimasina_listing(art)
                    if listing.get('car_id') and listing['car_id'] not in visited_ids:
                        results.append(listing)
                        visited_ids.add(listing['car_id'])

                random_sleep(2.0, 4.5)

            except Exception as e:
                print(f"[An {year}] Eroare la extragerea paginii {page_num}: {e}")
                break

        browser.close()

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunturi.")
    return pd.DataFrame(results)


# --- MAIN: Executia Concurenta ---
def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent pentru CautiMasina folosind {MAX_WORKERS} workers...")

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

    # --- SALVARE SI CURATARE DUPLICATE ---
    if all_dfs:
        print("\n[*] Combinam rezultatele...")
        final_df = pd.concat(all_dfs, ignore_index=True)

        initial_len = len(final_df)
        final_df.drop_duplicates(subset=['title', 'price', 'mileage_km', 'year'], inplace=True)
        print(f"\n[!] Am eliminat {initial_len - len(final_df)} duplicate extrase in aceasta sesiune.")

        cols = ['car_id', 'title', 'seller', 'location', 'price', 'currency', 'description',
                'mileage_km', 'year', 'fuel_type', 'seller_type', 'url', 'scrape_date']

        cols_to_keep = [c for c in cols if c in final_df.columns]
        final_df = final_df[cols_to_keep]

        if os.path.exists(RAW_XLSX):
            old_df = pd.read_excel(RAW_XLSX)
            combined_df = pd.concat([old_df, final_df], ignore_index=True)
            combined_df.drop_duplicates(subset=['title', 'price', 'mileage_km', 'year'], inplace=True)
            combined_df.to_excel(RAW_XLSX, index=False)
            print(f"[+] Salvat in {RAW_XLSX}. Total anunturi in DB: {len(combined_df)}")
        else:
            final_df.to_excel(RAW_XLSX, index=False)
            print(f"[+] Fisier creat: {RAW_XLSX}. Total: {len(final_df)}")
    else:
        print("Nu s-au extras date.")

    end_time = time.time()
    print(f"\n[*] Executie terminata in {(end_time - start_time) / 60:.2f} minute.")


if __name__ == "__main__":
    main()