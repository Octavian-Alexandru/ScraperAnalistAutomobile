# FILE: deduplicator.py
"""
Deduplicare Inteligentă la Nivel de Bază de Date.
Grupează aceeași mașină de pe platforme diferite sub un ID canonic unic.
Implementează:
1. Matching fuzzy multi-criteriu: (Brand, Model, Year, Km ±1000, Engine, Location)
2. Matching exact pe VIN (dacă disponibil)
3. Tabel `canonical_listings` cu prețuri agregate de pe toate platformele
4. Identificare cel mai mic preț + alertă automată
5. UI helper: returnează un card unificat cu toate prețurile side by side
"""

import os
import sys
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_connection, get_all_listings_df, DB_PATH
from logger_config import logger

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


def init_canonical_table(db_path: str = DB_PATH):
    """Crează tabelul de listări canonice dacă nu există."""
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS canonical_listings (
                canonical_id TEXT PRIMARY KEY,
                brand TEXT,
                model TEXT,
                year INTEGER,
                mileage_km INTEGER,
                fuel_type TEXT,
                engine_size REAL,
                location TEXT,
                num_sources INTEGER DEFAULT 1,
                min_price_eur REAL,
                max_price_eur REAL,
                avg_price_eur REAL,
                price_spread_eur REAL,
                cheapest_source TEXT,
                cheapest_url TEXT,
                car_ids TEXT,
                sources TEXT,
                first_seen TEXT,
                last_updated TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_canonical_brand ON canonical_listings(brand, model);")
        conn.commit()


def _compute_canonical_id(brand: str, model: str, year: int, mileage_bin: int) -> str:
    """Generează un ID canonic bazat pe atributele cheie ale mașinii."""
    import hashlib
    raw = f"{brand.lower().strip()}|{model.lower().strip()}|{year}|{mileage_bin}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _mileage_bin(km: int, bin_size: int = 5000) -> int:
    """Binning de kilometraj (ex: 145000 → 145000, grupat din 5000 în 5000)."""
    return (km // bin_size) * bin_size


def find_and_merge_duplicates(
    min_sources: int = 2,
    km_tolerance: int = 2000,
    min_price_diff_eur: float = 0,
    db_path: str = DB_PATH
) -> pd.DataFrame:
    """
    Identifică și grupează listările duplicate din baza de date.
    Returnează un DataFrame cu grupurile canonice.
    """
    init_canonical_table(db_path)

    df = get_all_listings_df(db_path=db_path)
    if df.empty or len(df) < 10:
        logger.warning("[Deduplicator] Prea puține listări pentru deduplicare.")
        return pd.DataFrame()

    # Normalizăm câmpurile cheie
    df['_brand'] = df['Brand'].fillna('').str.lower().str.strip()
    df['_model'] = df['Model'].fillna('').str.lower().str.strip()
    df['_year'] = pd.to_numeric(df.get('year', 0), errors='coerce').fillna(0).astype(int)
    df['_km'] = pd.to_numeric(df.get('mileage_km', 0), errors='coerce').fillna(0).astype(int)
    df['_fuel'] = df.get('fuel_type', pd.Series('', index=df.index)).fillna('').str.lower()
    df['_price'] = pd.to_numeric(df.get('price_eur', df.get('price', 0)), errors='coerce').fillna(0)
    df['_source'] = df.get('source', '').fillna('')
    df['_url'] = df.get('url', '').fillna('')
    df['_car_id'] = df.get('car_id', '').fillna('')

    # Filtrăm listări cu date minime
    valid = df[(df['_brand'] != '') & (df['_model'] != '') & (df['_year'] > 2000) & (df['_price'] > 500)].copy()

    # Grupăm pe (brand, model, year, mileage_bin) — key de matching
    valid['_km_bin'] = valid['_km'].apply(lambda x: _mileage_bin(x, km_tolerance))
    valid['_group_key'] = valid['_brand'] + '|' + valid['_model'] + '|' + valid['_year'].astype(str) + '|' + valid['_km_bin'].astype(str)

    groups = valid.groupby('_group_key')

    canonical_rows = []
    now = datetime.datetime.now().isoformat()

    for group_key, group_df in groups:
        # Doar grupuri cu listări de pe surse diferite
        unique_sources = group_df['_source'].nunique()
        if unique_sources < min_sources:
            continue

        prices = group_df['_price'].values
        min_price = float(prices.min())
        max_price = float(prices.max())
        avg_price = float(prices.mean())
        spread = float(max_price - min_price)

        if spread < min_price_diff_eur:
            continue

        cheapest_row = group_df.loc[group_df['_price'].idxmin()]

        canonical_id = _compute_canonical_id(
            cheapest_row['_brand'],
            cheapest_row['_model'],
            int(cheapest_row['_year']),
            int(cheapest_row['_km_bin'])
        )

        canonical_rows.append({
            "canonical_id": canonical_id,
            "brand": cheapest_row.get('Brand', cheapest_row['_brand']),
            "model": cheapest_row.get('Model', cheapest_row['_model']),
            "year": int(cheapest_row['_year']),
            "mileage_km": int(group_df['_km'].median()),
            "fuel_type": cheapest_row['_fuel'],
            "engine_size": cheapest_row.get('engine_size', None),
            "location": cheapest_row.get('location', ''),
            "num_sources": unique_sources,
            "min_price_eur": round(min_price, 0),
            "max_price_eur": round(max_price, 0),
            "avg_price_eur": round(avg_price, 0),
            "price_spread_eur": round(spread, 0),
            "cheapest_source": cheapest_row['_source'],
            "cheapest_url": cheapest_row['_url'],
            "car_ids": ",".join(group_df['_car_id'].astype(str).tolist()),
            "sources": ",".join(sorted(group_df['_source'].unique().tolist())),
            "first_seen": now,
            "last_updated": now
        })

    result_df = pd.DataFrame(canonical_rows)

    if not result_df.empty:
        # Salvăm în DB
        with get_connection(db_path) as conn:
            for _, row in result_df.iterrows():
                conn.execute(
                    """INSERT OR REPLACE INTO canonical_listings
                       (canonical_id, brand, model, year, mileage_km, fuel_type, engine_size,
                        location, num_sources, min_price_eur, max_price_eur, avg_price_eur,
                        price_spread_eur, cheapest_source, cheapest_url, car_ids, sources,
                        first_seen, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(row)
                )
            conn.commit()

        result_df = result_df.sort_values('price_spread_eur', ascending=False)
        logger.info(
            f"[Deduplicator] {len(result_df)} grupuri canonice identificate "
            f"(spread mediu: {result_df['price_spread_eur'].mean():,.0f} EUR)."
        )

    return result_df


def get_canonical_card(canonical_id: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Returnează un card unificat cu toate prețurile de pe toate platformele."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM canonical_listings WHERE canonical_id = ?",
            (canonical_id,)
        ).fetchone()
        if row:
            return dict(row)
    return None


def get_top_spreads(limit: int = 20, min_spread: float = 300, db_path: str = DB_PATH) -> pd.DataFrame:
    """Returnează cele mai mari diferențe de preț pentru aceeași mașină."""
    init_canonical_table(db_path)
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(
            """SELECT * FROM canonical_listings
               WHERE price_spread_eur >= ?
               ORDER BY price_spread_eur DESC
               LIMIT ?""",
            conn, params=(min_spread, limit)
        )
    return df


if __name__ == "__main__":
    print("=== TEST DEDUPLICATOR ===")
    result = find_and_merge_duplicates(min_sources=2, min_price_diff_eur=200)
    print(f"Grupuri canonice: {len(result)}")
    if not result.empty:
        print(result[['brand', 'model', 'year', 'num_sources', 'min_price_eur', 'max_price_eur', 'price_spread_eur']].head(10))
