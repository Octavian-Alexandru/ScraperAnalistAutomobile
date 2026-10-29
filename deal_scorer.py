# FILE: deal_scorer.py
"""
Sistem de Scoring Compozit al Oportunității (Deal Score 0-100).
Transformă o listă brută de anunțuri într-un clasament inteligent de oportunități
financiare pe piața auto din România.

Ponderi Deal Score:
- 30% Marjă Profit Net (după recondiționare și cheltuieli)
- 20% Lichiditate Model (Days-to-Sell & Rotație Capital)
- 15% Zile pe Piață (pârghie de negociere cu vânzătorul)
- 15% Discount Procentual față de Piață
- 10% Profil Vânzător (Privat vs Dealer)
- 10% Calitate Anunț & Risc Vizual (VIN prezent, poze clare, descriere detaliată)

Badge-uri:
- 🟢 80 - 100: "CUMPĂRĂ ACUM (Super Chilipir)"
- 🟡 60 - 79:  "Merită investigat"
- 🔴 sub 60:   "Risc ridicat / Marjă slabă"
"""

import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from typing import Dict, Any, Optional
from maintenance_estimator import calculate_net_profit
from liquidity_tracker import get_model_liquidity


def compute_deal_score(
    predicted_market_price: Optional[float],
    asked_price: float,
    brand: str,
    model: str,
    year: int,
    mileage_km: int,
    fuel_type: Optional[str] = None,
    seller_type: Optional[str] = None,
    days_on_market: Optional[int] = None,
    visual_risk_score: Optional[float] = None,
    has_vin: bool = False,
    safety_margin_eur: float = 300.0
) -> Dict[str, Any]:
    """
    Calculează Deal Score-ul complet (0-100) și planul optim de negociere.
    Dacă predicted_market_price nu este furnizat sau este nul,
    folosește automat motorul multi-tier de evaluare (valuation_engine).
    """
    valuation_tier = "precomputed"
    if not predicted_market_price or predicted_market_price <= 0:
        try:
            from valuation_engine import valuation_engine
            v_res = valuation_engine.estimate_price(brand, model, year, mileage_km, fuel_type)
            predicted_market_price = v_res["predicted_price_eur"]
            valuation_tier = v_res["valuation_tier"]
        except Exception:
            predicted_market_price = max(1000.0, asked_price)
            valuation_tier = "fallback_asked"

    # 1. Calcul financiar net (Profit net după recondiționare)
    fin_eval = calculate_net_profit(
        predicted_market_price=predicted_market_price,
        asked_price=asked_price,
        brand=brand,
        model=model,
        year=year,
        mileage_km=mileage_km,
        fuel_type=fuel_type,
        safety_margin_eur=safety_margin_eur
    )

    net_profit = fin_eval["net_profit_margin"]
    gross_profit = fin_eval["gross_profit_margin"]
    discount_pct = fin_eval["discount_pct"]
    roi_pct = fin_eval["net_roi_pct"]
    maint_cost = fin_eval["maintenance_cost"]

    # --- PONDERE 1: MARJĂ PROFIT NET (30 puncte max) ---
    # 0 puncte dacă net_profit <= 0
    # 30 puncte dacă net_profit >= 2.500 EUR sau ROI >= 25%
    if net_profit <= 0:
        score_net_profit = 0.0
    else:
        score_net_profit = min(30.0, (net_profit / 2500.0) * 30.0)
        # Bonus ROI
        if roi_pct >= 20.0:
            score_net_profit = min(30.0, score_net_profit + 5.0)

    # --- PONDERE 2: LICHIDITATE MODEL (20 puncte max) ---
    liq_data = get_model_liquidity(brand, model, year)
    raw_liq_score = liq_data.get("liquidity_score", 65)  # 0 - 100
    score_liquidity = (raw_liq_score / 100.0) * 20.0

    # --- PONDERE 3: ZILE PE PIAȚĂ (15 puncte max) ---
    # Dacă o mașină e pe piață de 30-60 zile, vânzătorul este mult mai deschis la o ofertă cash rapidă
    # Dacă e nouă (1-3 zile), e competiție mare de la alți cumpărători
    # Dacă e de >90 zile, mașina ar putea avea defecte ascunse
    dom = int(days_on_market) if days_on_market is not None and days_on_market >= 0 else 7
    if dom <= 3:
        # Nou listat - oportunitate rapidă dar negociere mai dură
        score_dom = 10.0
    elif 4 <= dom <= 25:
        score_dom = 14.0
    elif 26 <= dom <= 60:
        score_dom = 15.0  # Sweet spot negociere!
    elif 61 <= dom <= 90:
        score_dom = 11.0
    else:
        score_dom = 6.0   # Stă de prea mult timp, posibil defectă

    # --- PONDERE 4: DISCOUNT PROCENTUAL (15 puncte max) ---
    # Discount optim: 15% - 35% sub piață
    # Dacă e > 50% discount, este adesea țeapă sau daună totală deghizată
    if discount_pct < 5.0:
        score_discount = 0.0
    elif discount_pct <= 35.0:
        score_discount = (discount_pct / 35.0) * 15.0
    elif discount_pct <= 50.0:
        score_discount = 12.0  # Risc ușor crescut de scam
    else:
        score_discount = 3.0   # Discount ireal (>50%), probabil daună gravă

    # --- PONDERE 5: PROFIL VÂNZĂTOR (10 puncte max) ---
    st_clean = str(seller_type).lower() if seller_type else ""
    if any(w in st_clean for w in ['particular', 'privat', 'proprietar', 'persoana fizica']):
        score_seller = 10.0  # Cel mai ușor de negociat
    elif any(w in st_clean for w in ['dealer', 'parc', 'autohaus', 'profesionist', 'firma']):
        score_seller = 6.0   # Prețuri mai rigide, TVA inclus/deductibil
    else:
        score_seller = 7.5

    # --- PONDERE 6: CALITATE ANUNȚ & FACTORI DE RISC (10 puncte max) ---
    score_quality = 5.0
    if has_vin:
        score_quality += 3.0
    if visual_risk_score is not None:
        # visual_risk_score 0 = excelent, 100 = risc maxim
        v_points = max(0.0, 2.0 * (1.0 - (visual_risk_score / 100.0)))
        score_quality += v_points
    else:
        score_quality += 1.5

    # SCOR TOTAL FINAL
    total_deal_score = int(round(
        score_net_profit + score_liquidity + score_dom + score_discount + score_seller + score_quality
    ))
    total_deal_score = max(5, min(99, total_deal_score))

    # ATRIBUIRE BADGE ȘI RECOMANDARE
    if total_deal_score >= 80:
        badge = "🟢 CUMPĂRĂ ACUM (Super Chilipir)"
        tier_class = "super_deal"
        recommendation = (
            f"Oportunitate excelentă! Profit net estimat: +{net_profit:,.0f} € (ROI: {roi_pct}%). "
            f"Modelul {model} are lichiditate ridicată. Contactează vânzătorul imediat!"
        )
    elif total_deal_score >= 60:
        badge = "🟡 Merită investigat"
        tier_class = "good_deal"
        recommendation = (
            f"Ofertă interesantă cu marjă brută +{gross_profit:,.0f} €, dar verifică recondiționările. "
            f"Poți obține profit net bun dacă negociezi cu cel puțin 300-600 €."
        )
    else:
        badge = "🔴 Risc ridicat / Marjă slabă"
        tier_class = "poor_deal"
        recommendation = (
            f"Marjă insuficientă după scăderea costurilor de recondiționare ({maint_cost:,.0f} €). "
            f"Capital blocat fără garanția unui profit rentabil."
        )

    # Preț recomandat de ofertă agresivă / negociere
    target_buy_offer = round(asked_price * 0.90, -1)  # 10% sub prețul cerut

    return {
        "deal_score": total_deal_score,
        "badge": badge,
        "tier_class": tier_class,
        "valuation_tier": valuation_tier,
        "recommendation": recommendation,
        "target_buy_offer_eur": target_buy_offer,
        "financials": fin_eval,
        "liquidity": liq_data,
        "score_breakdown": {
            "net_profit_points": round(score_net_profit, 1),
            "liquidity_points": round(score_liquidity, 1),
            "days_on_market_points": round(score_dom, 1),
            "discount_points": round(score_discount, 1),
            "seller_type_points": round(score_seller, 1),
            "quality_risk_points": round(score_quality, 1)
        }
    }


if __name__ == "__main__":
    print("=== TEST COMPOSITE DEAL SCORER ===")
    test_deal = compute_deal_score(
        predicted_market_price=16500,
        asked_price=13200,
        brand="BMW",
        model="Seria 3",
        year=2019,
        mileage_km=140000,
        fuel_type="Diesel",
        seller_type="Particular",
        days_on_market=18,
        has_vin=True
    )
    print(f"Deal Score:            {test_deal['deal_score']} / 100")
    print(f"Badge:                 {test_deal['badge']}")
    print(f"Recomandare:           {test_deal['recommendation']}")
    print(f"Preț țintă negociere:  {test_deal['target_buy_offer_eur']:,.0f} €")
    print(f"Profit Net:            +{test_deal['financials']['net_profit_margin']:,.0f} € (ROI: {test_deal['financials']['net_roi_pct']}%)")
    print("\nPunctaj detaliat:")
    for k, v in test_deal['score_breakdown'].items():
        print(f"  * {k:<25}: {v} pct")
