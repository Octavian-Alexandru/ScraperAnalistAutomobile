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
    text = text.replace('.', '').replace(',', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


# --- Parsing Card HTML ---
def parse_bestauto_listing(element) -> Dict[str, Any]:
    # Preluam HTML-ul din Playwright
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    try:
        # Cautam direct div-ul principal in bucata noastra de HTML
        div = soup.select_one('div.article-item') or soup

        data['car_id'] = div.get('data-articleid')

        # URL
        a = div.select_one('a[href]')
        url = a.get('href') if a else None
        data['url'] = f"https://www.bestauto.ro{url}" if url and not url.startswith('http') else url

        # Title
        title_el = div.select_one('h2.article-title a')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        # Description
        desc_el = div.select_one('p.article-description')
        data['description'] = desc_el.get_text(strip=True) if desc_el else None

        # Location
        loc_el = div.select_one('p.article-location span')
        data['location'] = loc_el.get_text(strip=True) if loc_el else None

        # Price
        price_text = None
        price_el = div.select_one('span.new-price')
        if price_el:
            price_text = price_el.get_text(strip=True)
        elif div.select_one('span[itemprop="price"]') is not None:
            price_el = div.select_one('span[itemprop="price"]')
            price_text = price_el.get('content') or price_el.get_text(strip=True)
        elif div.select_one('span.article-price') is not None:
            price_el = div.select_one('span.article-price')
            price_text = price_el.get_text(strip=True)

        data['price'] = normalize_number(price_text) if price_text else None
        data['currency'] = 'EUR' if price_text else None

        # Year & Mileage
        short_info = div.select_one('p.article-short-info span.article-lbl-txt')
        if short_info:
            parts = short_info.get_text(strip=True).split('|')
            try:
                data['year'] = normalize_number(parts[0])
                data['mileage_km'] = normalize_number(parts[2])
            except IndexError:
                data['year'] = None
                data['mileage_km'] = None

        # Adaugam coloanele lipsa pentru consistenta cu celelalte site-uri
        data['seller'] = None
        data['seller_type'] = None
        data['fuel_type'] = None

        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card: {e}")
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

        # Blocăm descărcarea imaginilor pentru viteză
        page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ["image", "stylesheet", "media", "font"]
        else route.continue_()
                   )

        for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
            url = f"https://www.bestauto.ro/auto/bucuresti/?currency=eur&km=-250000&carregistrationdate={year}&damagedcar=neavariata&maxprice=20000&page={page_num}"

            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False

            # --- SISTEM DE RETRY ---
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_selector('div.article-item', timeout=15000)

                    # Logica de scroll integrata Playwright
                    prev_count = 0
                    for _ in range(15):  # Limita de 15 scroll-uri ca sa nu intram in bucla infinita
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                        page.wait_for_timeout(1000)
                        count = page.locator('div.article-item').count()
                        if count == prev_count:
                            break
                        prev_count = count

                    page_success = True
                    break  # A mers perfect, iesim din retry

                except Exception as e:
                    print(f"[An {year}] (Încercarea {attempt + 1}/{max_retries}) Timeout/Eroare la pagina {page_num}...")
                    random_sleep(2.0, 4.0)

            if not page_success:
                print(f"[An {year}] 0 anunțuri pe pagina {page_num} după {max_retries} încercări. Ne oprim pentru acest an.")
                break

            # --- EXTRAGERE EFECTIVĂ ȘI OPRIRE INTELIGENTĂ ---
            try:
                divs = page.query_selector_all('div.article-item')

                if len(divs) == 0:
                    break

                masini_noi_pe_pagina = 0

                for div in divs:
                    listing = parse_bestauto_listing(div)
                    if listing.get('car_id') and listing['car_id'] not in visited_ids:
                        results.append(listing)
                        visited_ids.add(listing['car_id'])
                        masini_noi_pe_pagina += 1

                # DACA SITE-UL NE DA PAGINA IN BUCLA INFINITA
                if masini_noi_pe_pagina == 0:
                    print(f"[An {year}] Nicio mașină nouă pe pagina {page_num}. Probabil am ajuns la capăt! Ne oprim.")
                    break # Iesim din bucla de pagini pentru anul acesta

                random_sleep(1.0, 2.5)

            except Exception as e:
                print(f"[An {year}] Eroare la extragerea datelor de pe pagina {page_num}: {e}")
                break

        browser.close()

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunțuri.")
    return pd.DataFrame(results)


# --- MAIN: Executia Concurenta ---
def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent pentru BestAuto folosind {MAX_WORKERS} workers...")

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

        # Aliniem coloanele cu baza de date existenta
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