# FILE: cross_border_arbitrage.py
"""
Modul de analiză arbitraj cross-border: Piața Românească vs Piețele din Europa de Vest (Germania, Austria, Olanda, Belgia).
50-60% din mașinile second-hand din România sunt importate din Germania și Austria.

Acest modul realizează:
1. Compararea în timp real a prețurilor reale din baza de date SQLite (RO vs DE/AT/NL)
2. Calculul detaliat al costurilor reale de import și oportunitate prin `import_cost_calculator.py`
   (scenariul "pe roți" vs "platformă autorizată")
3. Detectarea anomaliilor de piață:
   - Cazul A: Mașini din România listate sub prețul mediu din Vest (arbitraj intern/revânzare)
   - Cazul B: Mașini din Vest (Germania, Austria) care, aduse în România cu toate cheltuielile plătite,
     lasă o marjă netă de profit semnificativă (>= 1.500 EUR și ROI >= 15%)
4. Scanner automat de oportunități de import cross-border pentru pipeline-ul zilnic
"""

import os
import sys
import sqlite3
from typing import Dict, Any, List, Optional
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import DB_PATH, get_connection
from import_cost_calculator import calculate_import_costs, load_import_config
from logger_config import logger

# Costuri standard implicite pentru compatibilitate
DEFAULT_IMPORT_EXPENSES = {
    "transport_sau_platforma": 650.0,
    "numere_zoll_asigurare": 150.0,
    "rar_omologare_carte_identitate": 160.0,
    "traduceri_si_taxe_inmatriculare": 55.0
}
TOTAL_IMPORT_OVERHEAD = sum(DEFAULT_IMPORT_EXPENSES.values())  # 1,015 EUR


def get_real_market_median_price(
    brand: str,
    model: str,
    year: int,
    country: str = "RO",
    db_path: str = DB_PATH,
    min_samples: int = 3
) -> Optional[Dict[str, Any]]:
    """
    Interoghează baza de date SQLite pentru a extrage prețul median REAL al pieței
    pentru o marcă, model și an (+/- 1 an) într-o anumită țară.
    """
    if not os.path.exists(db_path):
        return None

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            # Căutare flexibilă pe titlu și an (+/- 1 an)
            b_pat = f"%{brand.strip()}%"
            m_pat = f"%{model.strip()}%"
            c_code = country.strip().upper()

            query = """
                SELECT price_eur, mileage_km, year
                FROM listings
                WHERE title LIKE ? AND title LIKE ?
                  AND year BETWEEN ? AND ?
                  AND price_eur BETWEEN 1000 AND 180000
                  AND is_active = 1
            """
            params: List[Any] = [b_pat, m_pat, year - 1, year + 1]

            if c_code == "RO":
                query += " AND (country = 'RO' OR country IS NULL)"
            else:
                query += " AND country = ?"
                params.append(c_code)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            if len(rows) < min_samples:
                # Daca filtrat pe tara nu gasim suficiente, dar cautam preturi din Vest
                if c_code != "RO":
                    cursor.execute("""
                        SELECT price_eur, mileage_km, year
                        FROM listings
                        WHERE title LIKE ? AND title LIKE ?
                          AND year BETWEEN ? AND ?
                          AND price_eur BETWEEN 1000 AND 180000
                          AND (country != 'RO' OR source IN ('mobile_de', 'autoscout24', 'willhaben'))
                    """, [b_pat, m_pat, year - 1, year + 1])
                    rows = cursor.fetchall()

            if len(rows) >= min_samples:
                prices = [r["price_eur"] for r in rows if r["price_eur"] and r["price_eur"] > 0]
                if prices:
                    prices.sort()
                    median_price = prices[len(prices) // 2]
                    avg_price = sum(prices) / len(prices)
                    min_price = min(prices)
                    return {
                        "median_price_eur": round(float(median_price), 0),
                        "mean_price_eur": round(float(avg_price), 0),
                        "min_price_eur": round(float(min_price), 0),
                        "sample_size": len(prices),
                        "data_source": "sqlite_real_listings"
                    }
    except Exception as e:
        logger.debug(f"[CrossBorder] Eroare interogare date reale DB: {e}")

    return None


def estimate_german_market_price(
    brand: str,
    model: str,
    year: int,
    mileage_km: int,
    fuel_type: Optional[str] = None,
    db_path: str = DB_PATH
) -> float:
    """
    Estimează prețul de referință pe piața germană/vestică.
    Prioritizează datele reale din SQLite (dacă există anunțuri extrase din DE/AT).
    Dacă datele locale sunt insuficiente, aplică modelul probabilistic calibrat pe piața germană.
    """
    # 1. Încercare pe date reale din SQLite
    real_de = get_real_market_median_price(brand, model, year, country="DE", db_path=db_path)
    if real_de and real_de["sample_size"] >= 3:
        return real_de["median_price_eur"]

    # 2. Fallback la motorul probabilistic
    brand_lower = str(brand).lower()
    is_diesel = fuel_type and 'diesel' in str(fuel_type).lower()

    if is_diesel and year <= 2015:
        # Motoare Euro 5 diesel au cerere scăzută în DE -> preț mai mic pe Mobile.de
        de_factor = 0.88
    elif any(b in brand_lower for b in ['bmw', 'mercedes', 'audi', 'porsche']):
        de_factor = 1.05
    elif any(b in brand_lower for b in ['volkswagen', 'skoda']):
        de_factor = 0.98
    else:
        de_factor = 0.94

    current_year = 2026
    age = max(1, current_year - year)
    base_price = max(2500.0, 35000.0 * (0.85 ** age) * (1.0 - min(0.65, mileage_km / 500000.0)))

    return round(base_price * de_factor, 0)


def analyze_cross_border_deal(
    romanian_price_eur: float,
    brand: str,
    model: str,
    year: int,
    mileage_km: int,
    fuel_type: Optional[str] = None,
    origin_country: str = "DE",
    origin_location: Optional[str] = None,
    currency: str = "EUR",
    import_overhead_eur: Optional[float] = None,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Compară o ofertă cu piața vestică și returnează analiza completă de oportunitate:
    - Preț de referință Vest (din DB SQLite sau formulă calibrată)
    - Costul exact de import (negru pe alb) calculat prin `import_cost_calculator`
    - Comparație detaliată: Deplasare personală vs Transport pe platformă
    - Recomandare și marjă de profit
    """
    if currency and currency.upper() != "EUR":
        try:
            from currency_helper import convert_to_eur
            romanian_price_eur = convert_to_eur(romanian_price_eur, currency)
        except Exception:
            pass

    # Estimare preț piață externă
    western_price = estimate_german_market_price(brand, model, year, mileage_km, fuel_type, db_path=db_path)

    # Calcul dinamic al costului de import
    import_calc = calculate_import_costs(
        country_code=origin_country,
        city_or_zip=origin_location,
        car_purchase_price_eur=western_price,
        expected_romanian_selling_price_eur=romanian_price_eur
    )

    optimal_import_cost = import_calc["scenarios"]["platform_transport"]["total_cost_eur"]
    personal_trip_cost = import_calc["scenarios"]["personal_trip"]["total_cost_eur"]
    used_overhead = import_overhead_eur if import_overhead_eur is not None else optimal_import_cost

    # 1. Delta directă: Preț RO vs Preț Vest
    delta_eur = round(romanian_price_eur - western_price, 0)
    delta_pct = round((delta_eur / western_price) * 100.0, 1) if western_price > 0 else 0.0

    # 2. Cazul A: Mașina este în RO mai ieftină chiar decât în Vest (Oportunitate rară)
    is_cheaper_than_germany = romanian_price_eur < western_price
    savings_vs_germany = max(0.0, western_price - romanian_price_eur)

    # 3. Cazul B: Oportunitate de adus mașina din Vest în România
    cost_total_import = western_price + used_overhead
    import_net_margin = round(romanian_price_eur - cost_total_import, 0)
    roi_import_pct = round((import_net_margin / cost_total_import) * 100.0, 1) if cost_total_import > 0 else 0.0

    if is_cheaper_than_germany and savings_vs_germany >= 1500:
        verdict = (
            f"🔥 Oportunitate de Arbitraj Intern! Mașina este listată în RO cu {savings_vs_germany:,.0f} € "
            f"(-{abs(delta_pct)}%) SUB prețul mediu din Vest ({origin_country.upper()}). Cumpărare recomandată local!"
        )
        recommendation_tier = "arbitrage_buy_ro"
    elif not is_cheaper_than_germany and import_net_margin >= 1500:
        verdict = (
            f"🚢 Oportunitate de Import Rentabil: Prețul în {origin_country.upper()} este {western_price:,.0f} €. "
            f"Adusă pe platformă cu {used_overhead:,.0f} € cheltuieli, lasă o marjă de profit de +{import_net_margin:,.0f} € "
            f"(ROI: {roi_import_pct}%)."
        )
        recommendation_tier = "profitable_import_western"
    else:
        verdict = f"⚖️ Prețuri aliniate între România și piața vestică (diferență nesemnificativă: {delta_pct:+.1f}%)."
        recommendation_tier = "aligned"

    return {
        "romanian_price_eur": romanian_price_eur,
        "german_price_eur": western_price,
        "western_price_eur": western_price,
        "origin_country": origin_country.upper(),
        "delta_eur": delta_eur,
        "delta_pct": delta_pct,
        "is_cheaper_than_germany": is_cheaper_than_germany,
        "savings_vs_germany": savings_vs_germany,
        "import_overhead_eur": used_overhead,
        "import_details": {
            "platform_total_eur": optimal_import_cost,
            "personal_trip_total_eur": personal_trip_cost,
            "recommended_method": import_calc["comparison"]["recommended_method"],
            "distance_km": import_calc["distance_km"]
        },
        "import_net_margin": import_net_margin,
        "roi_import_pct": roi_import_pct,
        "verdict": verdict,
        "recommendation_tier": recommendation_tier
    }


def find_top_import_arbitrage_deals(
    db_path: str = DB_PATH,
    min_profit_eur: float = 1500.0,
    min_roi_pct: float = 12.0,
    limit: int = 15
) -> pd.DataFrame:
    """
    Scanează toate ofertele active culese din piețele vestice (Germania, Austria, Olanda, Belgia)
    și le compară cu prețul de revânzare estimat pe piața din România.
    Returnează o listă prioritizată a celor mai profitabile oportunități de import.
    """
    if not os.path.exists(db_path):
        return pd.DataFrame()

    try:
        from main import parse_car_title, infer_fuel_type
        from valuation_engine import valuation_engine
    except ImportError:
        return pd.DataFrame()

    try:
        with get_connection(db_path) as conn:
            # Extragem anunțurile externe active (DE, AT, NL, BE etc.)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT car_id, source, url, title, price_eur, mileage_km, year,
                       fuel_type, seller, seller_type, location, country
                FROM listings
                WHERE is_active = 1
                  AND price_eur BETWEEN 2000 AND 80000
                  AND year >= 2012
                  AND (country != 'RO' OR source IN ('mobile_de', 'autoscout24', 'willhaben'))
                ORDER BY first_seen DESC
                LIMIT 400
            """)
            rows = cursor.fetchall()

            if not rows:
                return pd.DataFrame()

            df_foreign = pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        logger.error(f"[CrossBorder] Eroare la citirea ofertelor externe: {e}")
        return pd.DataFrame()

    # Parsare Brand și Model
    df_foreign[['Brand', 'Model', 'Trim']] = df_foreign['title'].apply(parse_car_title)
    df_foreign['Trim'] = df_foreign['Trim'].fillna('Standard')
    df_foreign['fuel_type'] = df_foreign.apply(infer_fuel_type, axis=1)

    opportunities = []
    for _, r in df_foreign.iterrows():
        b = r['Brand']
        m = r['Model']
        yr = r['year']
        km = r['mileage_km']
        foreign_price = r['price_eur']
        country = str(r.get('country') or 'DE').upper()
        loc = r.get('location')

        if not b or not m or not yr or pd.isna(yr) or not km or pd.isna(km) or foreign_price <= 0:
            continue

        yr_int = int(yr)
        km_int = int(km)

        # 1. Estimare preț piață România
        # Încercăm mai întâi pe date reale din piața RO
        ro_real = get_real_market_median_price(b, m, yr_int, country="RO", db_path=db_path)
        if ro_real and ro_real["sample_size"] >= 4:
            ro_market_price = ro_real["median_price_eur"]
            est_source = "Piața Reală RO (SQLite)"
        else:
            val_est = valuation_engine.estimate_price(
                brand=b, model=m, year=yr_int, mileage_km=km_int, fuel_type=r.get('fuel_type')
            )
            ro_market_price = val_est["predicted_price_eur"]
            est_source = val_est.get("valuation_tier", "ML/Heuristic")

        # 2. Calcul cost import detaliat
        costs = calculate_import_costs(
            country_code=country,
            city_or_zip=loc,
            car_purchase_price_eur=foreign_price,
            expected_romanian_selling_price_eur=ro_market_price
        )

        opt_cost = costs["scenarios"]["platform_transport"]["total_cost_eur"]
        total_inv = foreign_price + opt_cost
        net_profit = round(ro_market_price - total_inv, 0)
        roi_pct = round((net_profit / total_inv) * 100.0, 1)

        if net_profit >= min_profit_eur and roi_pct >= min_roi_pct:
            opportunities.append({
                "car_id": r['car_id'],
                "title": r['title'],
                "brand": b,
                "model": m,
                "year": yr_int,
                "mileage_km": km_int,
                "fuel_type": r.get('fuel_type'),
                "origin_country": country,
                "foreign_price_eur": foreign_price,
                "estimated_ro_price_eur": round(ro_market_price, 0),
                "import_expenses_eur": opt_cost,
                "total_investment_eur": round(total_inv, 0),
                "net_profit_eur": net_profit,
                "roi_pct": roi_pct,
                "valuation_source": est_source,
                "url": r.get('url'),
                "source": r.get('source')
            })

    df_res = pd.DataFrame(opportunities)
    if not df_res.empty:
        df_res = df_res.sort_values(by="net_profit_eur", ascending=False).head(limit)

    return df_res


if __name__ == "__main__":
    print("=== TEST CROSS-BORDER ARBITRAGE ACTUALIZAT ===")
    test_res = analyze_cross_border_deal(
        romanian_price_eur=14500,
        brand="Volkswagen",
        model="Passat",
        year=2019,
        mileage_km=160000,
        fuel_type="Diesel",
        origin_country="DE"
    )
    print(f"Preț România:         {test_res['romanian_price_eur']:,.0f} €")
    print(f"Preț Mediu Vest:      {test_res['western_price_eur']:,.0f} € (Origine: {test_res['origin_country']})")
    print(f"Cost Import Optimizat:{test_res['import_overhead_eur']:,.0f} € ({test_res['import_details']['recommended_method']})")
    print(f"Marjă Netă Import:    {test_res['import_net_margin']:+,.0f} € (ROI: {test_res['roi_import_pct']}%)")
    print(f"Verdict:              {test_res['verdict']}")

    print("\n--- Căutare Oportunități Reale de Import din DB ---")
    df_opps = find_top_import_arbitrage_deals(min_profit_eur=1000, min_roi_pct=10.0, limit=5)
    print(f"Găsite {len(df_opps)} oportunități:")
    if not df_opps.empty:
        for _, row in df_opps.iterrows():
            print(f"  * [{row['origin_country']}] {row['title'][:32]} | Preț extern: {row['foreign_price_eur']:,.0f} € | Estimat RO: {row['estimated_ro_price_eur']:,.0f} € | Profit: +{row['net_profit_eur']:,.0f} € (ROI {row['roi_pct']}%)")
