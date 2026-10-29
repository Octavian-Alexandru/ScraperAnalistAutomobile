# FILE: liquidity_tracker.py
"""
Tracker de lichiditate și viteză de rotație a stocului (Days-to-Sell) per model auto.
Analizează istoricul anunțurilor din SQLite (first_seen vs last_seen pentru mașini active și inactive)
pentru a calcula cât de repede se vinde un anumit model pe piața second-hand din România.

Niveluri de lichiditate (Rotație Capital):
- 🚀 Ultra-Lichid: < 18 zile (vânzare fulger: VW Golf, Dacia Logan, Duster, Skoda Octavia, BMW Seria 3)
- 🟢 Lichid: 18 - 35 zile (vânzare normală rapidă)
- 🟡 Moderat: 35 - 65 zile (rotație moderată)
- 🔴 Greu Vandabil: > 65 zile (risc ridicat de capital blocat)
"""

import os
import sqlite3
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from db_helper import get_connection, DB_PATH


def init_liquidity_table(db_path: str = DB_PATH):
    """Creează tabela model_liquidity dacă nu există."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_liquidity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                year_range TEXT,
                avg_days_to_sell REAL,
                median_days_to_sell REAL,
                active_listings_count INTEGER,
                sold_or_inactive_count INTEGER,
                avg_price_eur REAL,
                liquidity_tier TEXT,
                liquidity_score INTEGER,
                updated_at TEXT,
                UNIQUE(brand, model, year_range)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_liquidity_bm ON model_liquidity(brand, model);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_liquidity_score ON model_liquidity(liquidity_score);")
        conn.commit()


def compute_and_update_liquidity(db_path: str = DB_PATH) -> int:
    """
    Scanează toate listările din SQLite și recalculează indicatorii de lichiditate
    pentru fiecare pereche (Brand, Model, An).
    """
    init_liquidity_table(db_path)

    # 1. Extragem listările cu date temporale valide
    query = """
        SELECT
            car_id, title, price_eur, year, first_seen, last_seen, is_active
        FROM listings
        WHERE price_eur IS NOT NULL AND year IS NOT NULL AND first_seen IS NOT NULL
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        print("[!] Nu există listări pentru calculul lichidității.")
        return 0

    # Parsăm Brand și Model folosind regex rapid
    try:
        from main import parse_car_title
        parsed = df['title'].apply(parse_car_title)
        df['Brand'] = parsed[0]
        df['Model'] = parsed[1]
    except Exception:
        # Fallback simplu
        df['Brand'] = df['title'].str.split().str[0]
        df['Model'] = df['title'].str.split().str[1]

    df = df.dropna(subset=['Brand', 'Model'])
    df = df[df['Model'].str.len() >= 2]

    # Calculăm zilele pe piață (days_on_market)
    df['first_dt'] = pd.to_datetime(df['first_seen'], errors='coerce')
    df['last_dt'] = pd.to_datetime(df['last_seen'], errors='coerce')
    df['days_on_market'] = (df['last_dt'] - df['first_dt']).dt.total_seconds() / 86400.0
    df['days_on_market'] = df['days_on_market'].clip(lower=1.0)

    # Categorizare pe intervale de an (ex: 2010-2015, 2016-2020, 2021-2026)
    def get_year_range(yr):
        if yr < 2014: return "2010-2013"
        elif yr < 2018: return "2014-2017"
        elif yr < 2022: return "2018-2021"
        else: return "2022-2026"

    df['year_range'] = df['year'].apply(get_year_range)

    # Modele populare cu cel puțin 10 înregistrări
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []

    grouped = df.groupby(['Brand', 'Model', 'year_range'])
    for (brand, model, yr_range), group in grouped:
        if len(group) < 5:
            continue

        active_cnt = int((group['is_active'] == 1).sum())
        inactive_cnt = int((group['is_active'] == 0).sum())

        avg_days = float(group['days_on_market'].mean())
        median_days = float(group['days_on_market'].median())
        avg_price = float(group['price_eur'].mean())

        # Calcul Liquidity Score (0-100)
        # Cu cât timpul de vânzare e mai mic și numărul de tranzacții mai mare, cu atât scorul e mai mare
        # Referință: sub 15 zile = scor 90+, 15-30 zile = 75-89, 30-50 zile = 55-74, peste 60 zile = <50
        base_score = 100.0 - (median_days * 1.1)
        # Bonus de volum pentru modele cu cerere masivă
        volume_bonus = min(15.0, len(group) * 0.15)
        raw_score = base_score + volume_bonus
        final_score = int(max(10, min(99, raw_score)))

        if final_score >= 85:
            tier = "Ultra-Lichid"
        elif final_score >= 70:
            tier = "Lichid"
        elif final_score >= 50:
            tier = "Moderat"
        else:
            tier = "Greu Vandabil"

        records.append((
            brand, model, yr_range, round(avg_days, 1), round(median_days, 1),
            active_cnt, inactive_cnt, round(avg_price, 0), tier, final_score, now_ts
        ))

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO model_liquidity (
                brand, model, year_range, avg_days_to_sell, median_days_to_sell,
                active_listings_count, sold_or_inactive_count, avg_price_eur,
                liquidity_tier, liquidity_score, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()

    print(f"[+] Actualizat tracker-ul de lichiditate: {len(records)} segmente calculate.")
    return len(records)


def get_model_liquidity(
    brand: str,
    model: str,
    year: Optional[int] = None,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Returnează datele de lichiditate pentru o mașină dată.
    Dacă nu există date exacte, oferă o estimare bazată pe segmentul mărcii.
    """
    init_liquidity_table(db_path)

    query = """
        SELECT brand, model, year_range, avg_days_to_sell, median_days_to_sell,
               active_listings_count, sold_or_inactive_count, avg_price_eur,
               liquidity_tier, liquidity_score
        FROM model_liquidity
        WHERE LOWER(brand) = LOWER(?) AND LOWER(model) = LOWER(?)
    """

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (brand, model))
        rows = cursor.fetchall()

    if rows:
        # Căutăm cel mai apropiat interval de an dacă s-a furnizat anul
        if year and len(rows) > 1:
            for r in rows:
                yr_range = r['year_range']
                try:
                    start_y, end_y = map(int, yr_range.split('-'))
                    if start_y <= year <= end_y:
                        return dict(r)
                except Exception:
                    pass
        # Returnăm prima intrare
        return dict(rows[0])

    # Fallback euristic pe baza mărcii
    brand_lower = str(brand).lower()
    if any(b in brand_lower for b in ['dacia', 'volkswagen', 'skoda', 'toyota', 'bmw']):
        return {
            "brand": brand, "model": model, "year_range": "Estimare",
            "avg_days_to_sell": 22.0, "median_days_to_sell": 18.0,
            "active_listings_count": 50, "sold_or_inactive_count": 30,
            "avg_price_eur": 12000, "liquidity_tier": "Lichid", "liquidity_score": 78
        }
    else:
        return {
            "brand": brand, "model": model, "year_range": "Estimare",
            "avg_days_to_sell": 45.0, "median_days_to_sell": 40.0,
            "active_listings_count": 15, "sold_or_inactive_count": 8,
            "avg_price_eur": 11000, "liquidity_tier": "Moderat", "liquidity_score": 58
        }


def get_top_liquid_models(limit: int = 15, db_path: str = DB_PATH) -> pd.DataFrame:
    """Returnează cele mai lichide modele din baza de date (rotație maximă a capitalului)."""
    init_liquidity_table(db_path)
    with get_connection(db_path) as conn:
        df = pd.read_sql_query("""
            SELECT brand, model, year_range, median_days_to_sell,
                   active_listings_count, avg_price_eur, liquidity_tier, liquidity_score
            FROM model_liquidity
            WHERE active_listings_count >= 10
            ORDER BY liquidity_score DESC
            LIMIT ?
        """, conn, params=(limit,))
    return df


if __name__ == "__main__":
    print("=== TEST LIQUIDITY TRACKER ===")
    updated_count = compute_and_update_liquidity()
    top_models = get_top_liquid_models(10)
    print("\nTop 10 cele mai lichide modele din baza de date:")
    print(top_models.to_string(index=False))
