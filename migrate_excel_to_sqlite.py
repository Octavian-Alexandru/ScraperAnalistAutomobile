# FILE: migrate_excel_to_sqlite.py
"""
Script de migrare rapida din 'data/raw_listings_old.xlsx' in baza de date SQLite 'data/cars.db'.
- Proceseaza cele 90.000+ anunturi existente.
- Detecteaza automat sursa din URL (Autovit, OLX, AutoUncle, etc.).
- Populeaza tabelele `listings` si `price_history` cu timestamps corecte.
- Foloseste tranzactii masive in SQLite (se finalizeaza in cateva secunde).
"""

import os
import time
import urllib.parse
import pandas as pd
import sqlite3
from db_helper import init_db, get_connection, normalize_price_eur, DB_PATH

EXCEL_FILE = os.path.join("data", "raw_listings_old.xlsx")


def infer_source_from_url(url: str) -> str:
    if not url or pd.isna(url):
        return "necunoscut"
    url_str = str(url).lower()
    if "autouncle" in url_str:
        return "autouncle"
    if "autovit" in url_str:
        return "autovit"
    if "cautimasina" in url_str:
        return "cautimasina"
    if "olx" in url_str:
        return "olx"
    if "bestauto" in url_str:
        return "bestauto"
    if "plus-auto" in url_str:
        return "plusauto"
    if "carzz" in url_str:
        return "carzz"
    return "general"


def migrate():
    if not os.path.exists(EXCEL_FILE):
        print(f"[!] Fisierul Excel {EXCEL_FILE} nu a fost gasit.")
        return

    print("=" * 60)
    print(f"[*] Incepem migrarea din {EXCEL_FILE} in {DB_PATH}...")
    print("=" * 60)

    start_time = time.time()

    # 1. Citim datele din Excel
    print("[1/4] Incarcam fisierul Excel (poate dura cateva secunde din cauza marimii)...")
    df = pd.read_excel(EXCEL_FILE)
    total_rows = len(df)
    print(f"[+] S-au incarcat {total_rows:,} randuri din Excel.")

    # 2. Curatare si pregatire
    print("[2/4] Normalizam coloanele si detectam sursele din URL...")

    if 'source' not in df.columns or df['source'].isna().all():
        df['source'] = df['url'].apply(infer_source_from_url)

    # Prefixare car_id cu sursa
    def format_car_id(row):
        cid = str(row['car_id']) if pd.notna(row.get('car_id')) else ""
        src = str(row['source'])
        if not cid or cid.lower() == 'nan':
            import hashlib
            url = str(row.get('url', ''))
            return f"{src}_{hashlib.md5(url.encode()).hexdigest()[:12]}"
        if not cid.startswith(f"{src}_"):
            return f"{src}_{cid}"
        return cid

    df['car_id'] = df.apply(format_car_id, axis=1)

    # Eliminam eventualele duplicate din fisierul brut dupa car_id
    df = df.drop_duplicates(subset=['car_id'], keep='last').copy()
    print(f"[+] Anunturi unice dupa car_id: {len(df):,}")

    # Initializam baza de date
    init_db(DB_PATH)

    # 3. Pregatim tuplurile pentru executie rapida
    print("[3/4] Pregatim inregistrarile pentru inserare in SQLite...")
    listings_rows = []
    price_history_rows = []

    for _, row in df.iterrows():
        cid = str(row['car_id'])
        src = str(row.get('source', 'general'))
        url = str(row.get('url', '')) if pd.notna(row.get('url')) else None
        title = str(row.get('title', '')) if pd.notna(row.get('title')) else None
        seller = str(row.get('seller', '')) if pd.notna(row.get('seller')) else None
        location = str(row.get('location', '')) if pd.notna(row.get('location')) else None

        orig_price = row.get('price')
        curr = row.get('currency', 'EUR')
        price_eur = normalize_price_eur(orig_price, curr)

        fuel_type = str(row.get('fuel_type', '')) if pd.notna(row.get('fuel_type')) else None
        description = str(row.get('description', '')) if pd.notna(row.get('description')) else None
        seller_type = str(row.get('seller_type', '')) if pd.notna(row.get('seller_type')) else None

        try:
            mileage_km = int(row.get('mileage_km')) if pd.notna(row.get('mileage_km')) else None
        except (ValueError, TypeError):
            mileage_km = None

        try:
            year = int(row.get('year')) if pd.notna(row.get('year')) else None
        except (ValueError, TypeError):
            year = None

        # Data din scrape
        scrape_dt = str(row.get('scrape_date', '')).strip()
        if len(scrape_dt) == 10:
            timestamp = f"{scrape_dt} 12:00:00"
        else:
            timestamp = "2026-03-22 12:00:00"

        init_p = price_eur if price_eur else 0.0

        listings_rows.append((
            cid, src, url, title, seller, location,
            price_eur, orig_price, curr, fuel_type, description,
            mileage_km, year, seller_type, timestamp, timestamp, 1,
            init_p, 0
        ))

        if price_eur:
            price_history_rows.append((cid, price_eur, orig_price, curr, timestamp))

    # 4. Inserare in SQLite
    print(f"[4/4] Inseram {len(listings_rows):,} anunturi si {len(price_history_rows):,} preturi in {DB_PATH}...")
    with get_connection(DB_PATH) as conn:
        cursor = conn.cursor()

        # Inserare batch listings
        cursor.executemany("""
            INSERT OR REPLACE INTO listings (
                car_id, source, url, title, seller, location,
                price_eur, original_price, currency, fuel_type, description,
                mileage_km, year, seller_type, first_seen, last_seen, is_active,
                initial_price_eur, price_drop_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, listings_rows)

        # Inserare batch price history
        cursor.executemany("""
            INSERT INTO price_history (car_id, price_eur, original_price, currency, recorded_at)
            VALUES (?, ?, ?, ?, ?)
        """, price_history_rows)

        conn.commit()

    total_time = time.time() - start_time

    # Verificare statistici
    from db_helper import get_db_stats
    stats = get_db_stats(DB_PATH)

    print("\n" + "=" * 60)
    print("[SUCCESS] MIGRARE FINALIZATA CU SUCCES!")
    print(f"[TIME] Timp total: {total_time:.2f} secunde")
    print(f"[STATS] Total anunturi in SQLite:        {stats['total_listings']:,}")
    print(f"[STATS] Total inregistrari preturi:       {stats['total_price_records']:,}")
    print("\nDistributie pe surse:")
    for src, cnt in stats['sources'].items():
        print(f"  - {src:<15}: {cnt:,} anunturi")
    print("=" * 60)


if __name__ == "__main__":
    migrate()
