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
YEARS_TO_SCRAPE = range(2014, 2027)
MAX_PAGES_PER_YEAR = 100
MAX_WORKERS = 3
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
    if not text: return None
    text = text.replace('.', '').replace(',', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


# --- Parsing Card HTML (Actualizat pentru noul format CarZZ) ---
def parse_carzz_listing(element) -> Dict[str, Any]:
    html = element.evaluate("el => el.outerHTML")
    soup = BeautifulSoup(html, 'html.parser')
    data = {}

    try:
        # Cautăm titlul și extragem ID-ul din el (ex: title_ad_4009745_1)
        title_el = soup.select_one('span.title')
        data['car_id'] = None
        if title_el and title_el.get('id'):
            match = re.search(r'title_ad_(\d+)', title_el.get('id'))
            if match:
                data['car_id'] = match.group(1)

        data['title'] = title_el.get_text(strip=True) if title_el else None

        # Căutăm URL-ul pe elementul părinte (clasa a.main_items)
        a_tag = soup.find('a') if soup.name != 'a' else soup
        url = a_tag.get('href') if a_tag else None
        if url and not url.startswith('http'):
            url = "https://carzz.ro" + url
        data['url'] = url

        # Preț
        price_el = soup.select_one('span.price')
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data['currency'] = 'EUR' if price_text and 'EUR' in price_text.upper() else 'RON' if price_text else None

        # Info details (SUV | 2017 | 125.000 km | hibrid)
        info_el = soup.select_one('div.info_details')
        data['year'] = None
        data['mileage_km'] = None
        data['fuel_type'] = None

        if info_el:
            info_text = info_el.get_text(separator='|', strip=True)
            parts = [p.strip().lower() for p in info_text.split('|')]
            for part in parts:
                if 'km' in part:
                    data['mileage_km'] = normalize_number(part)
                elif len(part) == 4 and part.isdigit():
                    data['year'] = int(part)
                elif part in ['hibrid', 'benzina', 'diesel', 'electric', 'benzină']:
                    data['fuel_type'] = part.capitalize()

        # Location
        loc_el = soup.select_one('span.location')
        data['location'] = loc_el.get_text(strip=True) if loc_el else None

        data['seller'] = None
        data['seller_type'] = None
        data['description'] = None
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card CarZZ: {e}")
        return {}

    return data


# --- Functia de Scraping per AN ---
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

        # Blocăm doar imaginile și fonturile (Permitem CSS/JS pentru a nu rupe randarea linkurilor)
        page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ["image", "font", "media"]
        else route.continue_()
                   )

        for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
            url = f"https://carzz.ro/autoturisme_in-bucuresti-ilfov_pret-pana-la-20000.html?yf={year}&yt={year}&kt=250000&page={page_num}"
            print(f"[An {year}] Loading page {page_num}...")

            max_retries = 3
            page_success = False
            card_selector = 'a.main_items, li.item_list'

            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_selector(card_selector, timeout=15000)
                    page_success = True
                    break
                except Exception as e:
                    print(f"[An {year}] (Încercarea {attempt + 1}/{max_retries}) Timeout...")
                    random_sleep(2.0, 4.0)

            if not page_success:
                print(f"[An {year}] Ne oprim pentru acest an. Niciun element găsit după {max_retries} încercări.")
                break

            # Extragerea
            try:
                cards = page.query_selector_all(card_selector)

                if len(cards) == 0:
                    break

                for card in cards:
                    listing = parse_carzz_listing(card)

                    if listing.get('title') or listing.get(
                            'price'):  # Verificare robusta: daca are titlu sau pret, e ok
                        cid = listing.get('car_id')
                        # Fallback ID daca regex-ul pe title_ad_ a picat
                        if not cid and listing.get('url'):
                            match = re.search(r'-(\d+)\.html', listing['url'])
                            cid = match.group(1) if match else None

                        if cid and cid not in visited_ids:
                            listing['car_id'] = cid
                            results.append(listing)
                            visited_ids.add(cid)

                random_sleep(1.0, 2.5)

            except Exception as e:
                print(f"[An {year}] Eroare la extragerea datelor: {e}")
                break

        browser.close()

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunțuri.")
    return pd.DataFrame(results)


# --- MAIN ---
def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent pentru Carzz folosind {MAX_WORKERS} workers...")

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
        print("\n[!] Ai apăsat Ctrl+C! Oprim firele de execuție...")

    # --- SALVARE ---
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
        print("[!] Nu s-au extras date de pe CarZZ.")

    end_time = time.time()
    print(f"\n[*] Execuție terminată în {(end_time - start_time) / 60:.2f} minute.")


if __name__ == "__main__":
    main()