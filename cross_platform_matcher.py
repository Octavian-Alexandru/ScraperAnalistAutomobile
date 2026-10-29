# FILE: cross_platform_matcher.py
"""
Sistem de Comparare Cross-Platform (Same Car, Different Price).
Detectează automat dacă aceeași mașină este listată simultan pe două sau mai multe platforme
(ex: OLX, Autovit, AutoUncle, CarZZ) la prețuri diferite.
Permite identificarea imediată a celei mai mici oferte fără căutare manuală!
"""

import sys
import pandas as pd
from typing import List, Dict, Any, Optional
from db_helper import get_connection, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def find_cross_platform_duplicates(
    min_price_diff_eur: float = 300.0,
    db_path: str = DB_PATH
) -> pd.DataFrame:
    """
    Găsește mașini identice listate pe platforme diferite la prețuri diferite.
    Folosește o cheie compozită de potrivire exactă: (year, mileage_km, location, fuel_type).
    """
    query = """
        SELECT
            car_id, source, url, title, price_eur, year, mileage_km,
            location, fuel_type, seller, first_seen, last_seen
        FROM listings
        WHERE is_active = 1
          AND price_eur >= 1000
          AND year >= 2010
          AND mileage_km IS NOT NULL
          AND mileage_km > 1000
          AND location IS NOT NULL
          AND location != ''
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty or len(df) < 2:
        return pd.DataFrame()

    # Normalizăm orașul și combustibilul
    df['fuel_norm'] = df['fuel_type'].fillna('').str.lower().str.strip()
    df['title_norm'] = df['title'].fillna('').str.lower().str.strip()

    # Extragem prima parte a titlului (marca + model)
    df['short_title'] = df['title_norm'].apply(lambda t: " ".join(t.split()[:2]))

    # Grupăm după (year, mileage_km, short_title)
    grouped = df.groupby(['year', 'mileage_km', 'short_title'])

    matches = []
    for (year, km, short_title), group in grouped:
        if len(group) >= 2 and group['source'].nunique() >= 2:
            group_sorted = group.sort_values(by='price_eur', ascending=False)
            highest = group_sorted.iloc[0]
            lowest = group_sorted.iloc[-1]

            diff_eur = highest['price_eur'] - lowest['price_eur']
            if diff_eur >= min_price_diff_eur and highest['source'] != lowest['source']:
                diff_pct = round((diff_eur / highest['price_eur']) * 100.0, 1)
                matches.append({
                    "title": lowest['title'],
                    "year": int(year),
                    "mileage_km": int(km),
                    "location": lowest.get('location', 'N/A'),
                    "cheapest_source": lowest['source'].upper(),
                    "cheapest_price_eur": lowest['price_eur'],
                    "cheapest_url": lowest['url'],
                    "expensive_source": highest['source'].upper(),
                    "expensive_price_eur": highest['price_eur'],
                    "expensive_url": highest['url'],
                    "price_diff_eur": diff_eur,
                    "savings_pct": diff_pct
                })

    df_matches = pd.DataFrame(matches)
    if not df_matches.empty:
        df_matches = df_matches.sort_values(by='price_diff_eur', ascending=False).reset_index(drop=True)
    return df_matches


if __name__ == "__main__":
    print("=== TEST CROSS-PLATFORM MATCHER ===")
    duplicates = find_cross_platform_duplicates(min_price_diff_eur=250.0)
    print(f"S-au găsit {len(duplicates)} mașini identice cu diferențe de preț între platforme.")
    if not duplicates.empty:
        print("\nTop 5 discrepanțe de preț:")
        cols = ['title', 'cheapest_source', 'cheapest_price_eur', 'expensive_source', 'expensive_price_eur', 'price_diff_eur', 'savings_pct']
        print(duplicates[cols].head(5).to_string(index=False))
