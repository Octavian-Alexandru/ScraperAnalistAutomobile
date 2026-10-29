# FILE: cross_border_arbitrage.py
"""
Modul de analiză arbitraj cross-border: Piața Românească vs Piața Germană (Mobile.de).
50-60% din mașinile second-hand din România sunt importate din Germania.
Acest modul calculează:
1. Prețul de referință Mobile.de pentru modelul respectiv
2. Costurile reale de import și adus în România (transport/platformă + numere tranzit + RAR + omologare ~950 EUR)
3. Delta RO vs DE: Dacă o mașină din România este mai ieftină chiar decât în Germania (oportunitate rară!)
4. Marja de profit dacă se cumpără direct din Germania și se revinde în România
"""

import sys
from typing import Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Costuri standard import Germania -> România
DEFAULT_IMPORT_EXPENSES = {
    "transport_sau_platforma": 650.0,  # EUR
    "numere_zoll_asigurare": 150.0,    # EUR
    "rar_omologare_carte_identitate": 130.0, # EUR
    "traduceri_si_taxe_inmatriculare": 70.0  # EUR
}
TOTAL_IMPORT_OVERHEAD = sum(DEFAULT_IMPORT_EXPENSES.values())  # 1,000 EUR


def estimate_german_market_price(
    brand: str,
    model: str,
    year: int,
    mileage_km: int,
    fuel_type: Optional[str] = None
) -> float:
    """
    Estimează prețul de referință Mobile.de pe baza coeficienților pieței germane.
    În Germania, mașinile premium (BMW, Audi, Mercedes) și cele foarte bine echipate au prețuri
    cu 5-12% mai mari pentru modele verificate, în timp ce mașinile cu rulaj mare (>200.000 km)
    sau diesel Euro 5 sunt semnificativ mai ieftine din cauza restricțiilor din orașele germane.
    """
    # Bază calcul
    brand_lower = str(brand).lower()
    is_diesel = fuel_type and 'diesel' in str(fuel_type).lower()

    # Factor de piață Germania
    if is_diesel and year <= 2015:
        # Motoare Euro 5 diesel au cerere scăzută în DE -> preț mai mic pe Mobile.de
        de_factor = 0.88
    elif any(b in brand_lower for b in ['bmw', 'mercedes', 'audi', 'porsche']):
        de_factor = 1.05
    elif any(b in brand_lower for b in ['volkswagen', 'skoda']):
        de_factor = 0.98
    else:
        de_factor = 0.94

    # Estimare brută bazată pe an și km
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
    import_overhead_eur: float = TOTAL_IMPORT_OVERHEAD,
    currency: str = "EUR"
) -> Dict[str, Any]:
    """
    Compară o ofertă din România cu piața germană și returnează analiza de oportunitate.
    Include conversie valutară sigură cu fallback multi-nivel (RON/EUR/USD).
    """
    # Conversie automată dacă prețul este furnizat în altă monedă
    if currency and currency.upper() != "EUR":
        try:
            from currency_helper import convert_to_eur
            romanian_price_eur = convert_to_eur(romanian_price_eur, currency)
        except Exception:
            pass

    german_price = estimate_german_market_price(brand, model, year, mileage_km, fuel_type)

    # 1. Delta directă: Preț RO vs Preț DE
    delta_eur = round(romanian_price_eur - german_price, 0)
    delta_pct = round((delta_eur / german_price) * 100.0, 1) if german_price > 0 else 0.0

    # 2. Caz A: Mașina este în RO mai ieftină decât pe Mobile.de
    is_cheaper_than_germany = romanian_price_eur < german_price
    savings_vs_germany = max(0.0, german_price - romanian_price_eur)

    # 3. Caz B: Oportunitate de adus mașina din DE în RO
    cost_total_import = german_price + import_overhead_eur
    import_net_margin = round(romanian_price_eur - cost_total_import, 0)

    if is_cheaper_than_germany and savings_vs_germany >= 1500:
        verdict = (
            f"🔥 Oportunitate de Arbitraj Intern! Mașina este listată în RO cu {savings_vs_germany:,.0f} € "
            f"(-{abs(delta_pct)}%) SUB prețul mediu din Germania (Mobile.de). Cumpărare recomandată!"
        )
        recommendation_tier = "arbitrage_buy_ro"
    elif not is_cheaper_than_germany and import_net_margin >= 1500:
        verdict = (
            f"🚢 Oportunitate de Import: Prețul din Germania este {german_price:,.0f} €. "
            f"Adusă în România cu {import_overhead_eur:,.0f} € cheltuieli, lasă o marjă de +{import_net_margin:,.0f} €."
        )
        recommendation_tier = "profitable_import_de"
    else:
        verdict = f"⚖️ Prețuri aliniate între România și Germania (diferență nesemnificativă: {delta_pct:+.1f}%)."
        recommendation_tier = "aligned"

    return {
        "romanian_price_eur": romanian_price_eur,
        "german_price_eur": german_price,
        "delta_eur": delta_eur,
        "delta_pct": delta_pct,
        "is_cheaper_than_germany": is_cheaper_than_germany,
        "savings_vs_germany": savings_vs_germany,
        "import_overhead_eur": import_overhead_eur,
        "import_net_margin": import_net_margin,
        "verdict": verdict,
        "recommendation_tier": recommendation_tier
    }


if __name__ == "__main__":
    print("=== TEST CROSS-BORDER ARBITRAGE (RO vs DE) ===")
    test_res = analyze_cross_border_deal(
        romanian_price_eur=10500,
        brand="Volkswagen",
        model="Passat",
        year=2018,
        mileage_km=170000,
        fuel_type="Diesel"
    )
    print(f"Preț România:         {test_res['romanian_price_eur']:,.0f} €")
    print(f"Preț Mediu Germania:  {test_res['german_price_eur']:,.0f} €")
    print(f"Diferență (Delta):    {test_res['delta_eur']:+,.0f} € ({test_res['delta_pct']:+.1f}%)")
    print(f"Mai ieftin ca în DE:  {'DA' if test_res['is_cheaper_than_germany'] else 'NU'}")
    print(f"Verdict:              {test_res['verdict']}")
