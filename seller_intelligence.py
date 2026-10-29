# FILE: seller_intelligence.py
"""
Modul de analiză și profilare a vânzătorilor (Seller Intelligence).
Analizează comportamentul vânzătorilor din SQLite:
1. Detectează comercianții / samsarii deghizați în „persoane particulare"
   (indicatori: >= 3 mașini active simultan, formule tipizate în descriere)
2. Calculează flexibilitatea la negociere (cât de des a scăzut prețurile în trecut)
3. Scor de negociere (Negotiation Flexibility Score: 0 - 100)
"""

import sys
import re
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from db_helper import get_connection, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def get_seller_profile(seller_name: str, db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Extrage istoricul complet al unui vânzător din baza de date SQLite.
    """
    if not seller_name or not str(seller_name).strip():
        return {
            "seller_name": "Necunoscut",
            "detected_type": "Necunoscut",
            "active_listings_count": 0,
            "total_listings_history": 0,
            "total_price_drops": 0,
            "avg_discount_given": 0.0,
            "negotiation_flexibility_score": 50,
            "is_disguised_dealer": False,
            "details": "Informații indisponibile."
        }

    clean_seller = str(seller_name).strip()

    query = """
        SELECT
            car_id, title, price_eur, seller_type, first_seen, last_seen,
            is_active, price_drop_count
        FROM listings
        WHERE LOWER(seller) = LOWER(?)
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=(clean_seller,))

    if df.empty:
        return {
            "seller_name": clean_seller,
            "detected_type": "Particular (1 singură mașină)",
            "active_listings_count": 1,
            "total_listings_history": 1,
            "total_price_drops": 0,
            "avg_discount_given": 0.0,
            "negotiation_flexibility_score": 75,
            "is_disguised_dealer": False,
            "details": "Vânzător ocazional (proprietar privat)."
        }

    total_listings = len(df)
    active_listings = int((df['is_active'] == 1).sum())
    total_drops = int(df['price_drop_count'].sum())

    # Detectare dealer deghizat în particular
    # Dacă în anunț scrie seller_type = "particular" dar are 3 sau mai multe mașini
    claimed_private = any(
        'part' in str(st).lower() or 'priv' in str(st).lower()
        for st in df['seller_type'].dropna()
    )
    is_disguised = (claimed_private and total_listings >= 3) or (active_listings >= 3 and claimed_private)

    if is_disguised:
        detected_type = "Comerciant / Samsar deghizat în particular"
    elif total_listings >= 5 or any('deal' in str(st).lower() or 'parc' in str(st).lower() for st in df['seller_type'].dropna()):
        detected_type = "Dealer / Parc Auto Oficial"
    else:
        detected_type = "Proprietar Particular Autentic"

    # Calcul Negotiation Flexibility Score (0-100)
    # Particularii sunt mai flexibili (bază 70)
    # Dealerii sunt mai rigizi (bază 40)
    # Scăderile anterioare de preț indică dorința de lichidare rapidă
    if "Particular" in detected_type:
        base_flex = 75.0
    elif is_disguised:
        base_flex = 60.0  # Caută rulaj rapid, acceptă oferte cash ferme
    else:
        base_flex = 40.0  # Dealer - marje fixe

    drop_bonus = min(20.0, total_drops * 4.0)
    flex_score = int(min(99, max(15, base_flex + drop_bonus)))

    return {
        "seller_name": clean_seller,
        "detected_type": detected_type,
        "active_listings_count": active_listings,
        "total_listings_history": total_listings,
        "total_price_drops": total_drops,
        "negotiation_flexibility_score": flex_score,
        "is_disguised_dealer": is_disguised,
        "details": f"{total_listings} anunțuri în istoric ({active_listings} active, {total_drops} reduceri aplicate)."
    }


def get_top_active_dealers(limit: int = 10, db_path: str = DB_PATH) -> pd.DataFrame:
    """Returnează cei mai activi comercianți din baza de date."""
    query = """
        SELECT
            seller,
            COUNT(*) as total_listings,
            SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_listings,
            ROUND(AVG(price_eur), 0) as avg_price_eur,
            SUM(price_drop_count) as total_price_drops
        FROM listings
        WHERE seller IS NOT NULL AND seller != ''
        GROUP BY seller
        HAVING total_listings >= 3
        ORDER BY active_listings DESC, total_listings DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=(limit,))
    return df


if __name__ == "__main__":
    print("=== TEST SELLER INTELLIGENCE ===")
    top_dealers = get_top_active_dealers(5)
    print("Top comercianți activi:")
    print(top_dealers.to_string(index=False))

    if not top_dealers.empty:
        sample_seller = top_dealers.iloc[0]['seller']
        profile = get_seller_profile(sample_seller)
        print(f"\nProfil detaliat pentru [{sample_seller}]:")
        for k, v in profile.items():
            print(f"  * {k}: {v}")
