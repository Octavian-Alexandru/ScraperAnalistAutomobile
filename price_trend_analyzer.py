# FILE: price_trend_analyzer.py
"""
Analizator de trenduri temporale de preț (Price Trends & Time-Series Forecasting).
Analizează tabela `price_history` din SQLite pentru a detecta dacă prețurile
unui model sunt în creștere, în scădere sau stabile pe o perioadă de 30/60/90 zile.
Permite dealerilor să anticipeze momentul optim de vânzare sau cumpărare.
"""

import sys
import datetime
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from db_helper import get_connection, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def analyze_model_price_trend(
    brand: str,
    model: str,
    days_back: int = 60,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Extrage evoluția prețurilor din SQLite pentru un model și calculează panta trendului.
    """
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")

    query = """
        SELECT
            h.recorded_at,
            h.price_eur,
            l.year,
            l.mileage_km
        FROM price_history h
        JOIN listings l ON h.car_id = l.car_id
        WHERE LOWER(l.title) LIKE LOWER(?) AND LOWER(l.title) LIKE LOWER(?)
          AND h.recorded_at >= ?
          AND h.price_eur BETWEEN 1000 AND 120000
        ORDER BY h.recorded_at ASC
    """

    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=(f"%{brand}%", f"%{model}%", cutoff))

    if len(df) < 5:
        # Nu sunt suficiente puncte istorice specifice, încercăm fără filtru de dată
        with get_connection(db_path) as conn:
            df = pd.read_sql_query("""
                SELECT h.recorded_at, h.price_eur, l.year, l.mileage_km
                FROM price_history h
                JOIN listings l ON h.car_id = l.car_id
                WHERE LOWER(l.title) LIKE LOWER(?) AND LOWER(l.title) LIKE LOWER(?)
                  AND h.price_eur BETWEEN 1000 AND 120000
                ORDER BY h.recorded_at ASC
            """, conn, params=(f"%{brand}%", f"%{model}%"))

    if len(df) < 5:
        return {
            "brand": brand,
            "model": model,
            "trend_direction": "Stabil",
            "monthly_change_pct": 0.0,
            "status_text": "Date istorice insuficiente pentru model specific",
            "avg_current_price": None,
            "forecast_30d": None,
            "forecast_60d": None,
            "history_points": len(df)
        }

    df['dt'] = pd.to_datetime(df['recorded_at'], errors='coerce')
    df = df.dropna(subset=['dt', 'price_eur']).sort_values('dt')

    # Agregare zilnică (medie preț pe zi)
    df['date'] = df['dt'].dt.date
    daily = df.groupby('date')['price_eur'].median().reset_index()

    if len(daily) < 2:
        current_p = float(daily['price_eur'].iloc[0])
        return {
            "brand": brand,
            "model": model,
            "trend_direction": "Stabil",
            "monthly_change_pct": 0.0,
            "status_text": "Preț stabil pe piață",
            "avg_current_price": round(current_p, 0),
            "forecast_30d": round(current_p, 0),
            "forecast_60d": round(current_p, 0),
            "history_points": len(df)
        }

    daily['day_num'] = (pd.to_datetime(daily['date']) - pd.to_datetime(daily['date'].min())).dt.days

    # Regresie liniară pe prețuri zilnice
    x = daily['day_num'].values
    y = daily['price_eur'].values

    # Fit linie dreaptă: y = slope * x + intercept
    slope, intercept = np.polyfit(x, y, 1)

    current_avg = float(np.mean(y[-min(5, len(y)):]))
    # Variație lunară estimată (30 zile * slope)
    monthly_change_eur = float(slope * 30.0)
    monthly_change_pct = float((monthly_change_eur / current_avg) * 100.0) if current_avg > 0 else 0.0

    forecast_30d = max(500.0, current_avg + monthly_change_eur)
    forecast_60d = max(500.0, current_avg + (2 * monthly_change_eur))

    if monthly_change_pct <= -1.5:
        direction = "În scădere"
        status_text = f"📉 Preț în scădere cu ~{abs(monthly_change_pct):.1f}% / lună. Negociază ferm sau vinde rapid!"
    elif monthly_change_pct >= 1.5:
        direction = "În creștere"
        status_text = f"📈 Preț în creștere cu ~{monthly_change_pct:.1f}% / lună. Cerere ridicată în piață!"
    else:
        direction = "Stabil"
        status_text = "⚖️ Preț stabil pe piață (fluctuații sub 1.5% pe lună)."

    return {
        "brand": brand,
        "model": model,
        "trend_direction": direction,
        "monthly_change_pct": round(monthly_change_pct, 1),
        "monthly_change_eur": round(monthly_change_eur, 0),
        "status_text": status_text,
        "avg_current_price": round(current_avg, 0),
        "forecast_30d": round(forecast_30d, 0),
        "forecast_60d": round(forecast_60d, 0),
        "history_points": len(df),
        "daily_data": daily[['date', 'price_eur']].to_dict(orient='records')
    }


def get_market_wide_trends(db_path: str = DB_PATH) -> pd.DataFrame:
    """Returnează sinteza trendurilor pentru primele 10 cele mai populare modele din România."""
    popular_models = [
        ("Volkswagen", "Golf"),
        ("Volkswagen", "Passat"),
        ("Skoda", "Octavia"),
        ("BMW", "Seria 3"),
        ("BMW", "Seria 5"),
        ("Audi", "A4"),
        ("Dacia", "Logan"),
        ("Dacia", "Duster"),
        ("Ford", "Focus"),
        ("Renault", "Megane")
    ]
    rows = []
    for b, m in popular_models:
        t = analyze_model_price_trend(b, m, db_path=db_path)
        rows.append({
            "Brand": b,
            "Model": m,
            "Preț Mediu": f"{t['avg_current_price']:,.0f} €" if t['avg_current_price'] else "N/A",
            "Direcție": t['trend_direction'],
            "Variație Lunară %": f"{t['monthly_change_pct']:+.1f}%",
            "Prognoză 30 zile": f"{t['forecast_30d']:,.0f} €" if t['forecast_30d'] else "N/A"
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("=== TEST PRICE TREND ANALYZER ===")
    trend_golf = analyze_model_price_trend("Volkswagen", "Golf")
    print(f"Model:           {trend_golf['brand']} {trend_golf['model']}")
    print(f"Preț Actual:     {trend_golf['avg_current_price']} €")
    print(f"Direcție Trend:  {trend_golf['trend_direction']} ({trend_golf['monthly_change_pct']:+.1f}%/lună)")
    print(f"Prognoză 30z:    {trend_golf['forecast_30d']} €")
    print(f"Mesaj:           {trend_golf['status_text']}")
    print("\nSinteză Piață Top 10 Modele:")
    print(get_market_wide_trends().to_string(index=False))
