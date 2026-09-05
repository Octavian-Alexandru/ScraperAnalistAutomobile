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
    # Păstrăm doar partea întreagă (tot ce este înainte de virgulă)
    text_without_decimals = text.split(',')[0]
    # Extragem doar cifrele din partea rămasă
    digits = ''.join(filter(str.isdigit, text_without_decimals))
    return int(digits) if digits else None


# --- Parsing Card HTML ---
def parse_autovit_card(element) -> Dict[str, Any]:
    # Folosim evaluate pentru a extrage HTML-ul curat din obiectul Playwright
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    try:
        # 1. URL și car_id
        link_el = soup.select_one('h2 a')
        url = link_el.get('href') if link_el else None
        data['url'] = url
        data['car_id'] = url.split('-ID')[-1].replace('.html', '') if url else None

        # 2. Title
        data['title'] = link_el.get_text(strip=True) if link_el else None

        # 3. Price & currency
        price_el = soup.select_one('h3')
        currency_el = price_el.find_next_sibling('p') if price_el else None
        data['price'] = normalize_number(price_el.get_text(strip=True)) if price_el else None
        data['currency'] = currency_el.get_text(strip=True) if currency_el else None

        # 4. Locație și Tip Vânzător
        list_items = soup.select('ul.ooa-1o0axny li p')
        if len(list_items) >= 1:
            data['location'] = list_items[0].get_text(strip=True)
        else:
            data['location'] = None

        if len(list_items) >= 2:
            seller_info = list_items[1].get_text(strip=True)
            data['seller_type'] = seller_info.split('•')[0].strip() if '•' in seller_info else seller_info
        else:
            data['seller_type'] = None

        # 5. Year, Mileage, Fuel Type
        year_el = soup.select_one('dd[data-parameter="year"]')
        mileage_el = soup.select_one('dd[data-parameter="mileage"]')
        fuel_el = soup.select_one('dd[data-parameter="fuel_type"]')

        data['year'] = int(normalize_number(year_el.get_text(strip=True))) if year_el else None
        data['mileage_km'] = normalize_number(mileage_el.get_text(strip=True)) if mileage_el else None
        data['fuel_type'] = fuel_el.get_text(strip=True) if fuel_el else None

        # 6. Fields not always on card snippet
        data['seller'] = None
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card: {e}")
        return {}

    return data


# --- Functia de Scraping per AN (Ruleaza in Thread) ---
def scrape_year(year: int) -> pd.DataFrame:
    # Staggering: decalăm pornirea pentru a nu lovi serverul simultan
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

        # SUPER OPTIMIZARE: Blocăm descărcarea imaginilor și reclamelor
        page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ["image", "stylesheet", "media", "font"]
        else route.continue_()
                   )

        for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
            # Am integrat anul dinamizat in link-ul de Autovit
            url = f"https://www.autovit.ro/autoturisme?search%5Bfilter_float_mileage%3Ato%5D=250000&search%5Bfilter_float_price%3Ato%5D=20000&search%5Bfilter_float_year%3Afrom%5D={year}&search%5Bfilter_float_year%3Ato%5D={year}&search%5Border%5D=created_at%3Adesc&page={page_num}"

            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False

            # --- SISTEM DE RETRY ---
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)
                    # Așteptăm să apară articolele (Autovit folosește data-id pe carduri)
                    page.wait_for_selector('article[data-id]', timeout=15000)
                    page_success = True
                    break # A mers perfect, iesim din retry
                except Exception as e:
                    print(f"[An {year}] (Încercarea {attempt+1}/{max_retries}) Timeout la pagina {page_num}...")
                    random_sleep(2.0, 4.0)

            # Dacă după 3 încercări tot nu apar mașinile, ieșim din anul curent
            if not page_success:
                print(f"[An {year}] 0 anunțuri pe pagina {page_num} după {max_retries} încercări. Ne oprim pentru acest an.")
                break

            # --- EXTRAGERE EFECTIVĂ ---
            try:
                cards = page.query_selector_all('article[data-id]')

                if len(cards) == 0:
                    break

                for card in cards:
                    listing = parse_autovit_card(card)
                    if listing.get('car_id') and listing['car_id'] not in visited_ids:
                        results.append(listing)
                        visited_ids.add(listing['car_id'])

                random_sleep(1.0, 2.5)

            except Exception as e:
                print(f"[An {year}] Eroare la parsarea paginii {page_num}: {e}")
                break

        browser.close()

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunțuri.")
    return pd.DataFrame(results)


# --- MAIN: Executia Concurenta ---
def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent pentru Autovit folosind {MAX_WORKERS} workers...")

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

        # Stergem duplicatele spam din aceasta extragere
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
            # Deduplicare totala pe toata baza de date (daca rulezi pe un xlsx existent)
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