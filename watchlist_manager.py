# FILE: watchlist_manager.py
"""
Sistem de Watchlist și Alerte Personalizate per Utilizator / Dealer.
Permite configurarea de filtre avansate de achiziție:
- „Alertează-mă când apare un BMW X3 2018-2022, sub 18.000 EUR, sub 160.000 km, Deal Score >= 75"
- „Alertează-mă când apare un Golf 7 sau Passat sub 10.000 EUR cu profit net > 1.500 EUR"

Baza de date SQLite stochează alertele în tabela `watchlists`.
La fiecare rulare a pipeline-ului, verifică anunțurile noi și expediază notificări direcționate.
"""

import sys
import datetime
import pandas as pd
from typing import List, Dict, Any, Optional
from db_helper import get_connection, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def init_watchlist_table(db_path: str = DB_PATH):
    """Creează tabela watchlists dacă nu există."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                contact_channel TEXT, -- email, discord, telegram
                contact_target TEXT,  -- adresa email sau chat_id
                brand TEXT,
                model TEXT,
                min_year INTEGER,
                max_year INTEGER,
                max_price_eur REAL,
                max_mileage_km INTEGER,
                fuel_type TEXT,
                min_deal_score INTEGER DEFAULT 70,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlists(is_active);")
        conn.commit()


def add_watchlist_rule(
    user_name: str,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    max_price_eur: Optional[float] = None,
    max_mileage_km: Optional[int] = None,
    fuel_type: Optional[str] = None,
    min_deal_score: int = 70,
    contact_channel: str = "telegram",
    contact_target: Optional[str] = None,
    db_path: str = DB_PATH
) -> int:
    """Adaugă o nouă regulă de watchlist în baza de date."""
    init_watchlist_table(db_path)
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO watchlists (
                user_name, contact_channel, contact_target, brand, model,
                min_year, max_year, max_price_eur, max_mileage_km, fuel_type,
                min_deal_score, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            user_name, contact_channel, contact_target,
            brand, model, min_year, max_year, max_price_eur, max_mileage_km,
            fuel_type, min_deal_score, now_ts
        ))
        conn.commit()
        return cursor.lastrowid


def get_all_watchlists(active_only: bool = True, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returnează toate regulile de watchlist."""
    init_watchlist_table(db_path)
    where_clause = "WHERE is_active = 1" if active_only else ""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM watchlists {where_clause} ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]


def check_listings_against_watchlists(
    listings_df: pd.DataFrame,
    db_path: str = DB_PATH
) -> List[Dict[str, Any]]:
    """
    Verifică o listă de mașini (ex: anunțurile noi de astăzi) împotriva tuturor regulilor
    active de watchlist și returnează potrivirile găsite.
    """
    if listings_df.empty:
        return []

    rules = get_all_watchlists(active_only=True, db_path=db_path)
    if not rules:
        return []

    matches = []
    for rule in rules:
        subset = listings_df.copy()

        # Filtru Brand
        if rule.get('brand') and str(rule['brand']).strip() and rule['brand'].lower() != 'toate':
            b = str(rule['brand']).lower()
            subset = subset[subset['title'].fillna('').str.lower().str.contains(b)]

        # Filtru Model
        if rule.get('model') and str(rule['model']).strip() and rule['model'].lower() != 'toate':
            m = str(rule['model']).lower()
            subset = subset[subset['title'].fillna('').str.lower().str.contains(m)]

        # Filtru An
        if rule.get('min_year'):
            subset = subset[subset['year'] >= rule['min_year']]
        if rule.get('max_year'):
            subset = subset[subset['year'] <= rule['max_year']]

        # Filtru Preț
        if rule.get('max_price_eur'):
            subset = subset[subset['price_eur'] <= rule['max_price_eur']]

        # Filtru Kilometraj
        if rule.get('max_mileage_km'):
            subset = subset[subset['mileage_km'] <= rule['max_mileage_km']]

        # Filtru Combustibil
        if rule.get('fuel_type') and rule['fuel_type'].lower() != 'toate':
            f = str(rule['fuel_type']).lower()
            subset = subset[subset['fuel_type'].fillna('').str.lower().str.contains(f)]

        if not subset.empty:
            for _, car in subset.iterrows():
                matches.append({
                    "rule_id": rule['id'],
                    "user_name": rule['user_name'],
                    "contact_channel": rule['contact_channel'],
                    "contact_target": rule['contact_target'],
                    "car_title": car.get('title'),
                    "price_eur": car.get('price_eur'),
                    "year": car.get('year'),
                    "mileage_km": car.get('mileage_km'),
                    "url": car.get('url')
                })

    return matches


if __name__ == "__main__":
    print("=== TEST WATCHLIST MANAGER ===")
    rule_id = add_watchlist_rule(
        user_name="Alexandru (Dealer)",
        brand="BMW",
        model="Seria 3",
        min_year=2015,
        max_price_eur=15000,
        max_mileage_km=180000,
        min_deal_score=75,
        contact_channel="telegram",
        contact_target="@dealeralex"
    )
    print(f"Regulă creată cu ID: {rule_id}")
    active_rules = get_all_watchlists()
    print(f"Total reguli active: {len(active_rules)}")
    for r in active_rules:
        print(f"  * [{r['user_name']}] Caută: {r['brand']} {r['model']} (Buget max: {r['max_price_eur']} €)")
