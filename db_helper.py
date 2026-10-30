# FILE: db_helper.py
"""
Sistem de stocare si urmarire a preturilor auto in SQLite.
- Gestioneaza tabelele `listings` (date masina) si `price_history` (evolutie pret in timp).
- Suporta modul WAL pentru acces concurent rapid (fara file locks).
- Detecteaza automat scaderile si cresterile de pret la fiecare rulare de scraper.
- Ofera functii de interogare rapida pentru Streamlit (Price drops, Days on market, Istoric).
"""

import os
import sqlite3
import datetime
import pandas as pd
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join("data", "cars.db")
CURS_EUR = 5.09  # Curs RON -> EUR


def get_connection(db_path: str = DB_PATH, max_retries: int = 4, busy_timeout_ms: int = 30000) -> sqlite3.Connection:
    """Creeaza si configureaza o conexiune optimizata SQLite cu WAL mode si retry la locking."""
    import time
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    delay = 0.5
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, timeout=busy_timeout_ms / 1000.0)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2.0
            else:
                raise
    # Fallback ultima sansa
    return sqlite3.connect(db_path, timeout=10.0)


def init_db(db_path: str = DB_PATH):
    """Initializeaza tabelele si indecsii daca nu exista."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. Tabelul principal: Anunturi active & istorice
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                car_id TEXT PRIMARY KEY,
                source TEXT,
                url TEXT,
                title TEXT,
                seller TEXT,
                location TEXT,
                price_eur REAL,
                original_price REAL,
                currency TEXT,
                fuel_type TEXT,
                description TEXT,
                mileage_km INTEGER,
                year INTEGER,
                seller_type TEXT,
                first_seen TEXT,
                last_seen TEXT,
                is_active INTEGER DEFAULT 1,
                initial_price_eur REAL,
                price_drop_count INTEGER DEFAULT 0
            );
        """)

        # 2. Tabelul temporal: Istoric complet preturi
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id TEXT NOT NULL,
                price_eur REAL NOT NULL,
                original_price REAL,
                currency TEXT,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (car_id) REFERENCES listings (car_id) ON DELETE CASCADE
            );
        """)

        # 2b. Migrare automata coloane aditionale (country, engine_size, vin, vin_check_status)
        cursor.execute("PRAGMA table_info(listings);")
        existing_cols = [r["name"] for r in cursor.fetchall()]
        if "country" not in existing_cols:
            cursor.execute("ALTER TABLE listings ADD COLUMN country TEXT DEFAULT 'RO';")
            cursor.execute("UPDATE listings SET country = 'DE' WHERE source IN ('mobile_de');")
            cursor.execute("UPDATE listings SET country = 'RO' WHERE country IS NULL OR country = '';")
        if "engine_size" not in existing_cols:
            cursor.execute("ALTER TABLE listings ADD COLUMN engine_size REAL;")
        if "vin" not in existing_cols:
            cursor.execute("ALTER TABLE listings ADD COLUMN vin TEXT;")
        if "vin_check_status" not in existing_cols:
            cursor.execute("ALTER TABLE listings ADD COLUMN vin_check_status TEXT DEFAULT 'NOT_SPECIFIED';")

        # 3. Indecsi de performanta pentru cautare ultra-rapida
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_url ON listings(url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_country ON listings(country);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_vin ON listings(vin);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_year_price ON listings(year, price_eur);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_car ON price_history(car_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(recorded_at);")

        conn.commit()


def normalize_price_eur(price: Any, currency: Any) -> Optional[float]:
    """Converteste orice pret in EUR numeric curat cu mecanism de fallback curs valutar."""
    if pd.isna(price) or price is None:
        return None
    try:
        p = float(str(price).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None

    if p <= 0:
        return None

    curr_str = str(currency).upper().strip() if pd.notna(currency) else "EUR"
    try:
        from currency_helper import convert_to_eur
        return convert_to_eur(p, curr_str)
    except Exception:
        if curr_str in ["RON", "LEI"]:
            return round(p / CURS_EUR, 2)
        return round(p, 2)


_is_draining_recovery = False


def drain_recovery_buffer_if_needed(db_path: str = DB_PATH):
    """Verifica si re-insereaza datele din buffer-ul de urgenta daca exista."""
    global _is_draining_recovery
    if _is_draining_recovery:
        return
    try:
        from fallback_engine import recovery_buffer
        _is_draining_recovery = True
        recovery_buffer.drain_buffer_to_sqlite(lambda df, src: save_scraped_data(df, src, db_path))
    except Exception:
        pass
    finally:
        _is_draining_recovery = False


def save_scraped_data(new_df: pd.DataFrame, source_name: str, db_path: str = DB_PATH) -> Dict[str, int]:
    """
    Salveaza anunturile extrase de scraper in baza de date SQLite cu fallback de rezilienta.
    Daca SQLite esueaza sau este blocat, datele sunt salvate in buffer-ul de urgenta (recovery_buffer.jsonl)
    si re-inserate automat cand conexiunea este restabilita.
    """
    if new_df is None or new_df.empty:
        print(f"[!] [{source_name}] Nu s-au extras date noi.")
        return {"new": 0, "updated": 0, "price_drops": 0, "price_increases": 0}

    drain_recovery_buffer_if_needed(db_path)
    init_db(db_path)
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_date = datetime.datetime.now().strftime("%Y-%m-%d")

    df = new_df.copy()

    # Prefixare car_id cu source_name daca nu este deja prefixat
    if 'car_id' not in df.columns or df['car_id'].isna().all():
        if 'url' in df.columns:
            import hashlib
            df['car_id'] = df['url'].apply(
                lambda u: f"{source_name}_{hashlib.md5(str(u).encode()).hexdigest()[:12]}"
            )
        else:
            print(f"[!] [{source_name}] Datele nu au car_id si nici url valid!")
            return {"new": 0, "updated": 0, "price_drops": 0, "price_increases": 0}
    else:
        df['car_id'] = df['car_id'].astype(str).apply(
            lambda x: f"{source_name}_{x}" if not str(x).startswith(f"{source_name}_") else str(x)
        )

    # Coloane standard
    cols_expected = [
        'car_id', 'title', 'seller', 'location', 'price', 'currency',
        'fuel_type', 'description', 'mileage_km', 'year', 'seller_type', 'url'
    ]
    for c in cols_expected:
        if c not in df.columns:
            df[c] = None

    stats = {
        "new": 0,
        "updated": 0,
        "price_drops": 0,
        "price_increases": 0,
        "total_processed": len(df)
    }

    price_history_inserts = []
    listings_inserts = []
    listings_updates = []

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()

            # Incarcam informatiile despre masinile deja existente in DB pentru aceste car_id-uri
            car_ids = df['car_id'].dropna().unique().tolist()
            existing_map = {}

            # Chunked fetch daca sunt multe car_id-uri
            chunk_size = 900
            for i in range(0, len(car_ids), chunk_size):
                chunk = car_ids[i:i + chunk_size]
                placeholders = ",".join(["?"] * len(chunk))
                cursor.execute(f"""
                    SELECT car_id, price_eur, initial_price_eur, price_drop_count
                    FROM listings
                    WHERE car_id IN ({placeholders})
                """, chunk)
                for row in cursor.fetchall():
                    existing_map[row['car_id']] = {
                        'price_eur': row['price_eur'],
                        'initial_price_eur': row['initial_price_eur'],
                        'price_drop_count': row['price_drop_count'] or 0
                    }

            # Procesam fiecare rand din noul DataFrame
            seen_in_batch = set()
            for _, row in df.iterrows():
                cid = str(row['car_id'])
                if cid in seen_in_batch or pd.isna(cid):
                    continue
                seen_in_batch.add(cid)

                orig_price = row.get('price')
                curr = row.get('currency', 'EUR')
                price_eur = normalize_price_eur(orig_price, curr)
                scrape_dt = str(row.get('scrape_date', '')).strip()
                item_ts = f"{scrape_dt} 12:00:00" if len(scrape_dt) == 10 else now_ts

                title = str(row.get('title', '')).strip() if pd.notna(row.get('title')) else None
                seller = str(row.get('seller', '')).strip() if pd.notna(row.get('seller')) else None
                location = str(row.get('location', '')).strip() if pd.notna(row.get('location')) else None
                fuel_type = str(row.get('fuel_type', '')).strip() if pd.notna(row.get('fuel_type')) else None
                description = str(row.get('description', '')).strip() if pd.notna(row.get('description')) else None
                seller_type = str(row.get('seller_type', '')).strip() if pd.notna(row.get('seller_type')) else None
                url = str(row.get('url', '')).strip() if pd.notna(row.get('url')) else None

                try:
                    mileage_km = int(row.get('mileage_km')) if pd.notna(row.get('mileage_km')) else None
                except (ValueError, TypeError):
                    mileage_km = None

                try:
                    year = int(row.get('year')) if pd.notna(row.get('year')) else None
                except (ValueError, TypeError):
                    year = None

                # Țară de proveniență
                country = str(row.get('country', '')).strip().upper() if pd.notna(row.get('country')) and str(row.get('country')).strip() else None
                if not country:
                    if source_name in ['mobile_de']:
                        country = 'DE'
                    elif source_name in ['autoscout24']:
                        loc_u = str(location or '').upper()
                        if any(k in loc_u for k in ['AUSTRIA', 'WIEN', 'SALZBURG', 'GRAZ', ', AT']) or loc_u.startswith('A-'):
                            country = 'AT'
                        elif any(k in loc_u for k in ['NEDERLAND', 'NETHERLANDS', 'AMSTERDAM', ', NL']):
                            country = 'NL'
                        elif any(k in loc_u for k in ['BELGIUM', 'BELGIQUE', 'BRUXELLES', ', BE']):
                            country = 'BE'
                        elif any(k in loc_u for k in ['ITALIA', 'ITALY', 'MILANO', ', IT']):
                            country = 'IT'
                        elif any(k in loc_u for k in ['FRANCE', 'PARIS', ', FR']):
                            country = 'FR'
                        else:
                            country = 'DE'
                    elif source_name in ['willhaben']:
                        country = 'AT'
                    elif source_name in ['otomoto']:
                        country = 'PL'
                    else:
                        country = 'RO'

                # Capacitate cilindrică
                try:
                    engine_size = float(row.get('engine_size')) if pd.notna(row.get('engine_size')) else None
                except (ValueError, TypeError):
                    engine_size = None

                # Serie de șasiu (VIN) & status validare
                vin = str(row.get('vin', '')).strip().upper() if pd.notna(row.get('vin')) and str(row.get('vin')).strip() else None
                if not vin and (title or description):
                    try:
                        from vin_checker import extract_vin_from_text
                        vin = extract_vin_from_text(f"{title or ''} {description or ''}")
                    except Exception:
                        vin = None

                vin_check_status = "NOT_SPECIFIED"
                if vin:
                    try:
                        from vin_checker import decode_vin
                        res_vin = decode_vin(vin)
                        vin_check_status = res_vin.get("status", "VALID")
                    except Exception:
                        vin_check_status = "DETECTED"

                if cid not in existing_map:
                    # ANUNT NOU
                    stats['new'] += 1
                    init_p = price_eur if price_eur else 0.0
                    listings_inserts.append((
                        cid, source_name, url, title, seller, location,
                        price_eur, orig_price, curr, fuel_type, description,
                        mileage_km, year, seller_type, item_ts, item_ts, 1,
                        init_p, 0, country, engine_size, vin, vin_check_status
                    ))
                    if price_eur:
                        price_history_inserts.append((cid, price_eur, orig_price, curr, item_ts))
                else:
                    # ANUNT EXISTENT
                    stats['updated'] += 1
                    curr_info = existing_map[cid]
                    old_price = curr_info['price_eur']
                    price_drop_count = curr_info['price_drop_count']

                    # Verificam schimbarea de pret (prag de minim 10 EUR pentru evitarea fluctuatiilor de rotunjire)
                    if price_eur and old_price and abs(price_eur - old_price) >= 10:
                        price_history_inserts.append((cid, price_eur, orig_price, curr, item_ts))

                        safe_title = str(title).encode('ascii', 'ignore').decode()[:35]
                        if price_eur < old_price:
                            stats['price_drops'] += 1
                            price_drop_count += 1
                            diff = old_price - price_eur
                            print(f"  [v SCADERE PRET] {safe_title} | {old_price:,.0f} EUR -> {price_eur:,.0f} EUR (-{diff:,.0f} EUR)")
                        else:
                            stats['price_increases'] += 1
                            diff = price_eur - old_price
                            print(f"  [^ CRESTERE PRET] {safe_title} | {old_price:,.0f} EUR -> {price_eur:,.0f} EUR (+{diff:,.0f} EUR)")

                    listings_updates.append((
                        price_eur, orig_price, curr, mileage_km, item_ts, 1,
                        price_drop_count, country, engine_size, vin, vin_check_status, cid
                    ))

            # Executie in batch (tranzactie atomica rapida)
            if listings_inserts:
                cursor.executemany("""
                    INSERT OR REPLACE INTO listings (
                        car_id, source, url, title, seller, location,
                        price_eur, original_price, currency, fuel_type, description,
                        mileage_km, year, seller_type, first_seen, last_seen, is_active,
                        initial_price_eur, price_drop_count, country, engine_size,
                        vin, vin_check_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, listings_inserts)

            if listings_updates:
                cursor.executemany("""
                    UPDATE listings SET
                        price_eur = COALESCE(?, price_eur),
                        original_price = COALESCE(?, original_price),
                        currency = COALESCE(?, currency),
                        mileage_km = COALESCE(?, mileage_km),
                        last_seen = ?,
                        is_active = ?,
                        price_drop_count = ?,
                        country = COALESCE(?, country),
                        engine_size = COALESCE(?, engine_size),
                        vin = COALESCE(?, vin),
                        vin_check_status = COALESCE(?, vin_check_status)
                    WHERE car_id = ?
                """, listings_updates)

            if price_history_inserts:
                cursor.executemany("""
                    INSERT INTO price_history (car_id, price_eur, original_price, currency, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                """, price_history_inserts)

            conn.commit()

    except Exception as e:
        print(f"[!] [{source_name}] Eroare SQLite la salvare ({e}). Activam Buffer-ul de Urgenta...")
        try:
            from fallback_engine import recovery_buffer
            records_to_buffer = df.to_dict(orient="records")
            recovery_buffer.append_failed_records(source_name, records_to_buffer)
            return {"new": 0, "updated": 0, "price_drops": 0, "price_increases": 0, "buffered_emergency": len(records_to_buffer)}
        except Exception as buf_err:
            print(f"[!] Eroare grava la scrierea in buffer-ul de urgenta: {buf_err}")
            return {"new": 0, "updated": 0, "price_drops": 0, "price_increases": 0, "error": str(e)}

    print(f"[+] [{source_name}] Salvare finalizata:")
    print(f"    - Noi inserate:        {stats['new']}")
    print(f"    - Actualizate (vazute): {stats['updated']}")
    print(f"    - Scaderi de pret:     {stats['price_drops']}")
    print(f"    - Cresteri de pret:    {stats['price_increases']}")
    return stats


def get_price_history(car_id: str, db_path: str = DB_PATH) -> pd.DataFrame:
    """Returneaza istoricul complet cronologic de pret pentru o masina data."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        df = pd.read_sql_query("""
            SELECT recorded_at, price_eur, original_price, currency
            FROM price_history
            WHERE car_id = ?
            ORDER BY recorded_at ASC
        """, conn, params=(car_id,))
    if not df.empty:
        df['price_change'] = df['price_eur'].diff()
        df['pct_change'] = (df['price_change'] / df['price_eur'].shift(1)) * 100
    return df


def get_price_drops(days: int = 7, min_drop_eur: float = 100, db_path: str = DB_PATH) -> pd.DataFrame:
    """
    Gaseste masinile al caror pret a scazut in ultimele `days` zile.
    Calculeaza pretul vechi, pretul nou, valoarea reducerii si procentul.
    """
    init_db(db_path)
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    query = """
        WITH latest_two AS (
            SELECT
                h.car_id,
                h.price_eur,
                h.recorded_at,
                ROW_NUMBER() OVER (PARTITION BY h.car_id ORDER BY h.recorded_at DESC) as rn
            FROM price_history h
        ),
        drops AS (
            SELECT
                curr.car_id,
                prev.price_eur AS old_price,
                curr.price_eur AS new_price,
                (prev.price_eur - curr.price_eur) AS drop_eur,
                ROUND(((prev.price_eur - curr.price_eur) / prev.price_eur) * 100, 1) AS drop_pct,
                curr.recorded_at AS drop_date
            FROM latest_two curr
            JOIN latest_two prev ON curr.car_id = prev.car_id AND prev.rn = 2
            WHERE curr.rn = 1
              AND (prev.price_eur - curr.price_eur) >= ?
              AND curr.recorded_at >= ?
        )
        SELECT
            d.car_id,
            l.title,
            l.source,
            l.year,
            l.mileage_km,
            l.fuel_type,
            l.location,
            l.url,
            d.old_price,
            d.new_price,
            d.drop_eur,
            d.drop_pct,
            d.drop_date,
            l.first_seen,
            l.last_seen
        FROM drops d
        JOIN listings l ON d.car_id = l.car_id
        WHERE l.is_active = 1
        ORDER BY d.drop_eur DESC;
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=(min_drop_eur, cutoff))
    return df


def get_all_listings_df(active_only: bool = False, db_path: str = DB_PATH) -> pd.DataFrame:
    """Incarca anunturile din SQLite in Pandas (sub 0.5s). Poate incarca doar active sau toate."""
    init_db(db_path)
    where_clause = "WHERE is_active = 1" if active_only else ""
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(f"""
            SELECT
                car_id, source, url, title, seller, location,
                price_eur, currency, fuel_type, description,
                mileage_km, year, seller_type, first_seen, last_seen,
                is_active, initial_price_eur, price_drop_count
            FROM listings
            {where_clause}
        """, conn)
    return df


def get_active_listings_df(db_path: str = DB_PATH) -> pd.DataFrame:
    """Alias pentru compatibilitate cu functiile existente."""
    return get_all_listings_df(active_only=True, db_path=db_path)


def mark_inactive_listings(days_threshold: int = 7, db_path: str = DB_PATH) -> int:
    """
    Marcheaza ca inactive (vandute / sterse) masinile care nu au mai aparut la scraping
    de mai mult de `days_threshold` zile.
    """
    init_db(db_path)
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days_threshold)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE listings
            SET is_active = 0
            WHERE is_active = 1 AND last_seen < ?
        """, (cutoff,))
        affected = cursor.rowcount
        conn.commit()
    print(f"[+] [{affected}] anunturi marcate ca inactive (lipsa in ultimele {days_threshold} zile).")
    return affected


def get_db_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Returneaza statistici globale despre baza de date cu fallback la erori."""
    try:
        init_db(db_path)
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM listings;")
            total_listings = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1;")
            active_listings = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM price_history;")
            total_price_records = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM listings WHERE price_drop_count > 0;")
            cars_with_drops = cursor.fetchone()[0]

            cursor.execute("SELECT source, COUNT(*) as cnt FROM listings GROUP BY source ORDER BY cnt DESC;")
            sources_breakdown = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "total_listings": total_listings,
            "active_listings": active_listings,
            "inactive_listings": total_listings - active_listings,
            "total_price_records": total_price_records,
            "cars_with_price_drops": cars_with_drops,
            "sources": sources_breakdown
        }
    except Exception as e:
        print(f"[!] [db_helper] Eroare interogare get_db_stats: {e}. Returnam statistici de rezerva.")
        return {
            "total_listings": 0,
            "active_listings": 0,
            "inactive_listings": 0,
            "total_price_records": 0,
            "cars_with_price_drops": 0,
            "sources": {},
            "fallback_warning": str(e)
        }


def get_known_car_ids_and_prices(source: Optional[str] = None, db_path: str = DB_PATH) -> Dict[str, Optional[float]]:
    """
    Returneaza un dictionar in memorie {car_id: price_eur} pentru cautare O(1) ultra-rapida.
    Permite verificare atat cu prefixul sursei (ex: 'autouncle_123'), cat si fara ('123').
    """
    if not os.path.exists(db_path):
        return {}
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            if source:
                cursor.execute("SELECT car_id, price_eur FROM listings WHERE source = ?", (source,))
            else:
                cursor.execute("SELECT car_id, price_eur FROM listings")
            mapping = {}
            for row in cursor.fetchall():
                cid, p = row[0], row[1]
                mapping[cid] = p
                if source and cid.startswith(f"{source}_"):
                    mapping[cid[len(source) + 1:]] = p
                elif "_" in cid:
                    parts = cid.split("_", 1)
                    mapping[parts[1]] = p
            return mapping
    except Exception:
        return {}


def export_to_parquet(parquet_path: str = "data/ml_ready_listings.parquet", db_path: str = DB_PATH) -> str:
    """
    Exporta anunturile active direct din SQLite in format Parquet.
    Viteza de citire in Streamlit creste de 50-100x fata de Excel.
    """
    df = get_active_listings_df(db_path)
    os.makedirs(os.path.dirname(parquet_path), exist_ok=True)
    df.to_parquet(parquet_path, index=False, engine="pyarrow")
    print(f"[+] Export Parquet reusit: {parquet_path} ({len(df):,} masini)")
    return parquet_path


def get_new_listings_today(since_timestamp: Optional[str] = None, db_path: str = DB_PATH) -> pd.DataFrame:
    """
    Extrage anunturile active nou inserate astazi (sau dupa since_timestamp) din SQLite.
    Permite identificarea oportunitatilor proaspete de arbitraj.
    """
    init_db(db_path)
    today_prefix = datetime.datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        if since_timestamp:
            query = """
                SELECT
                    car_id, source, url, title, seller, location,
                    price_eur, currency, fuel_type, description,
                    mileage_km, year, seller_type, first_seen, last_seen,
                    is_active, initial_price_eur
                FROM listings
                WHERE is_active = 1
                  AND first_seen >= ?
                  AND price_eur IS NOT NULL
                  AND price_eur >= 500
                ORDER BY first_seen DESC
            """
            df = pd.read_sql_query(query, conn, params=(since_timestamp,))
        else:
            query = """
                SELECT
                    car_id, source, url, title, seller, location,
                    price_eur, currency, fuel_type, description,
                    mileage_km, year, seller_type, first_seen, last_seen,
                    is_active, initial_price_eur
                FROM listings
                WHERE is_active = 1
                  AND first_seen LIKE ?
                  AND price_eur IS NOT NULL
                  AND price_eur >= 500
                ORDER BY first_seen DESC
            """
            df = pd.read_sql_query(query, conn, params=(f"{today_prefix}%",))
    return df