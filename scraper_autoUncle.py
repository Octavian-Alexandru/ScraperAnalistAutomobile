import os
import time
import random
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import pandas as pd
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configurare ---
YEARS_TO_SCRAPE = range(2014, 2027)
MAX_PAGES_PER_YEAR = 500
MAX_WORKERS = 6  # Setat pe 3 pentru a distribui cererile optim
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
    if not text:
        return None
    text = text.replace('.', '').replace(',', '').replace(' ', '')
    digits = ''.join(filter(str.isdigit, text))
    return int(digits) if digits else None


# --- Parsare Card HTML ---
def parse_autouncle_listing(soup) -> Dict[str, Any]:
    # Acum primeste direct un obiect BeautifulSoup (fara evaluarile Playwright)
    data = {}

    try:
        link_el = soup.select_one('a._p9jqN')
        url = link_el.get('href') if link_el else None
        if url and not url.startswith('http'):
            data['url'] = f"https://www.autouncle.ro{url}"
        else:
            data['url'] = url

        data['car_id'] = None
        if data['url']:
            match = re.search(r'/d/(\d+)-', data['url'])
            data['car_id'] = match.group(1) if match else None

        title_el = soup.select_one('h3._GXVfV._D9pIb')
        data['title'] = title_el.get_text(strip=True) if title_el else None

        desc_el = soup.select_one('p._GXVfV._XQXLf')
        data['description'] = desc_el.get_text(strip=True) if desc_el else None

        price_el = soup.select_one('div._i2QOc')
        price_text = price_el.get_text(strip=True) if price_el else None
        data['price'] = normalize_number(price_text)
        data['currency'] = 'EUR' if 'EUR' in (price_text or '') else None

        data['year'] = None
        data['mileage_km'] = None
        info_tags = soup.select('ul._PuGQy li._ZTpYr')
        for tag in info_tags:
            text = tag.get_text(strip=True)
            if 'km' in text:
                data['mileage_km'] = normalize_number(text)
            elif text.isdigit() and len(text) == 4:
                data['year'] = int(text)

        seller_el = soup.select_one('div[data-testid="dealer-label"]')
        data['seller'] = seller_el.get_text(strip=True) if seller_el else "Privat"

        location_el = soup.select_one('div._jFepo > div._GXVfV')
        data['location'] = location_el.get_text(strip=True) if location_el else None

        data['seller_type'] = 'Dealer' if data.get('seller') != "Privat" else 'Privat'
        data['scrape_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    except Exception as e:
        print(f"  [!] Eroare parsare card: {e}")
        return {}

    return data


# --- Functia de Scraping per AN ---
def scrape_year(year: int) -> pd.DataFrame:
    delay_start = random.uniform(0.5, 2.0)
    time.sleep(delay_start)

    results = []
    visited_ids = set()

    # Cream o sesiune HTTP simpla in loc de Browser Playwright
    session = requests.Session()

    for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
        url = f"https://www.autouncle.ro/ro/masini-second-hand?s%5Bmax_km%5D=250000&s%5Bmax_price%5D=20000&s%5Bmax_year%5D={year}&s%5Bmin_year%5D={year}&page={page_num}"
        print(f"[An {year}] Loading page {page_num}...")

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # --- SISTEM INTELIGENT DE RETRY ---
        max_retries = 3
        page_success = False
        response = None

        for attempt in range(max_retries):
            try:
                response = session.get(url, headers=headers, timeout=(10, 20))

                # Tratăm blocajul de trafic (Rate Limit)
                if response.status_code == 429:
                    wait_time = 60 * (attempt + 1)  # Așteptăm 60s, apoi 120s, apoi 180s
                    print(f"[An {year}] Blocat (Rate Limit 429). Așteptăm {wait_time} secunde...")
                    time.sleep(wait_time)
                    continue  # Încearcă din nou aceeași pagină

                # Dacă nu mai sunt pagini sau e altă eroare server (ex: 404 Not Found)
                if response.status_code != 200:
                    print(f"[An {year}] Pagina {page_num} a returnat status {response.status_code}. Oprim anul.")
                    break  # Ieșim din retry

                # Dacă ajungem aici, request-ul a avut succes (200 OK)
                page_success = True
                break

            except requests.exceptions.RequestException as e:
                print(f"[An {year}] Eroare conexiune (încercarea {attempt + 1}): {e}")
                time.sleep(5)

        # Dacă a eșuat de 3 ori sau a luat break la un cod iremediabil (ex: 404), oprim anul curent
        if not page_success:
            break

        # --- PARSARE HTML ---
        try:
            page_soup = BeautifulSoup(response.text, 'html.parser')
            article_tags = page_soup.select('article._qzVn4')

            if len(article_tags) == 0:
                # Nu mai sunt masini pe pagina, am terminat anul
                break

            for art in article_tags:
                listing = parse_autouncle_listing(art)
                if listing.get('car_id') and listing['car_id'] not in visited_ids:
                    results.append(listing)
                    visited_ids.add(listing['car_id'])

            # Folosim delay-ul generos cerut de tine ca sa limitam cererile pe secunda
            random_sleep()

        except Exception as e:
            print(f"[An {year}] Eroare la extragerea paginii {page_num}: {e}")
            break

    print(f"[+] Finalizat anul {year}. Extrase: {len(results)} anunțuri.")
    return pd.DataFrame(results)


def main():
    start_time = time.time()
    all_dfs = []

    print(f"[*] Incepem scraping concurent FAST pentru AutoUncle (fara browser) folosind {MAX_WORKERS} workers...")

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
        print("\n[!] Ai apăsat Ctrl+C! Salvăm ce am găsit până acum...")

    if all_dfs:
        print("\n[*] Combinam rezultatele...")
        final_df = pd.concat(all_dfs, ignore_index=True)

        initial_len = len(final_df)
        final_df.drop_duplicates(subset=['car_id'], inplace=True)
        print(f"[!] Am eliminat {initial_len - len(final_df)} duplicate extrase in aceasta sesiune.")

        cols = ['car_id', 'title', 'seller', 'location', 'price', 'currency', 'description',
                'mileage_km', 'year', 'seller_type', 'url', 'scrape_date']

        cols_to_keep = [c for c in cols if c in final_df.columns]
        final_df = final_df[cols_to_keep]

        if os.path.exists(RAW_XLSX):
            old_df = pd.read_excel(RAW_XLSX)
            combined_df = pd.concat([old_df, final_df], ignore_index=True)
            combined_df.drop_duplicates(subset=['car_id'], inplace=True)
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
