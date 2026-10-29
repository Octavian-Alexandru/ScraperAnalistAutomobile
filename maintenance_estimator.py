# FILE: maintenance_estimator.py
"""
Estimator industrializat de costuri de recondiționare și reparație auto per model.
Calculează costul realist (piese + manoperă) necesar pentru a aduce o mașină
achiziționată la starea optimă de revânzare (flipping profitabil).

Defalcare costuri:
- Revizie completă (ulei, filtru ulei, aer, habitaclu, combustibil)
- Kit distribuție (curea + pompă apă sau verificare lanț)
- Ambreiaj / Cutie automată (ambreiaj + volantă sau schimb ulei cutie automată)
- Sistem frânare (discuri și plăcuțe față/spate)
- Articulații & Suspensie (brațe, bucșe, amortizoare, bielete)
- Cosmetică & Detailing (polish caroserie, curățare interioară profesională)
- Rezervă pentru neprevăzute (10% buffer de siguranță)
"""

import datetime
from typing import Dict, Any, Optional

# Niveluri de costuri pe categorii de branduri (bazate pe prețurile reale din România: piese OEM/Aftermarket + manoperă service autorizat)
BRAND_TIERS = {
    "luxury": [
        "Porsche", "Maserati", "Bentley", "Aston Martin", "Rolls-Royce", "Ferrari"
    ],
    "premium": [
        "BMW", "Mercedes-Benz", "Audi", "Land Rover", "Jaguar", "Volvo", "Lexus"
    ],
    "upper_mid": [
        "Volkswagen", "Alfa Romeo", "Subaru", "Mini", "Cupra", "Jeep"
    ],
    "standard": [
        "Ford", "Toyota", "Skoda", "Škoda", "Peugeot", "Renault", "Hyundai",
        "Kia", "Mazda", "Nissan", "Seat", "Opel", "Honda", "Mitsubishi", "Citroën", "Citroen", "Fiat", "Suzuki"
    ],
    "budget": [
        "Dacia", "Chevrolet", "Smart", "Ssangyong", "MG"
    ]
}

# Costuri de bază piese (EUR) per clasă
BASE_PARTS_COSTS = {
    "luxury": {
        "revizie": 380,
        "distributie": 950,
        "ambreiaj_transmisie": 1400,
        "frane": 750,
        "suspensie": 1100,
        "cosmetica_detailing": 250
    },
    "premium": {
        "revizie": 240,
        "distributie": 650,
        "ambreiaj_transmisie": 950,
        "frane": 480,
        "suspensie": 680,
        "cosmetica_detailing": 180
    },
    "upper_mid": {
        "revizie": 170,
        "distributie": 450,
        "ambreiaj_transmisie": 680,
        "frane": 330,
        "suspensie": 450,
        "cosmetica_detailing": 140
    },
    "standard": {
        "revizie": 130,
        "distributie": 350,
        "ambreiaj_transmisie": 520,
        "frane": 250,
        "suspensie": 340,
        "cosmetica_detailing": 120
    },
    "budget": {
        "revizie": 90,
        "distributie": 220,
        "ambreiaj_transmisie": 340,
        "frane": 160,
        "suspensie": 220,
        "cosmetica_detailing": 90
    }
}

# Raport manoperă / piese (manopera este în general 30-45% din valoarea pieselor în RO)
LABOR_MULTIPLIER = {
    "luxury": 0.50,
    "premium": 0.40,
    "upper_mid": 0.35,
    "standard": 0.30,
    "budget": 0.28
}


def get_brand_tier(brand: Optional[str]) -> str:
    """Identifică clasa de cost a mărcii."""
    if not brand:
        return "standard"
    brand_clean = str(brand).strip()
    for tier, brands in BRAND_TIERS.items():
        for b in brands:
            if b.lower() == brand_clean.lower():
                return tier
    return "standard"


def estimate_maintenance_cost(
    brand: Optional[str],
    model: Optional[str] = None,
    year: Optional[int] = None,
    mileage_km: Optional[int] = None,
    fuel_type: Optional[str] = None,
    transmission: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculează estimarea realistă a costurilor de recondiționare necesare înainte de revânzare.
    Ia în calcul vechimea mașinii și rulajul (ex: la >180.000 km crește probabilitatea distribuției și a ambreiajului).
    """
    tier = get_brand_tier(brand)
    parts_db = BASE_PARTS_COSTS.get(tier, BASE_PARTS_COSTS["standard"])
    labor_rate = LABOR_MULTIPLIER.get(tier, 0.30)

    current_year = datetime.datetime.now().year
    car_age = max(1, current_year - int(year)) if year and 1990 <= int(year) <= current_year else 7
    km = int(mileage_km) if mileage_km and mileage_km > 0 else 160000

    # Probabilități / coeficienți de necesitate în funcție de rulaj și vârstă
    # 1. Revizie completă (ulei + filtre) este OBLIGATORIE la flipping pentru garanție morală
    factor_revizie = 1.0

    # 2. Distribuție: necesară la intervale de 80.000 - 120.000 km sau 5-6 ani
    if km > 160000 or car_age >= 6:
        factor_distributie = 0.85
    elif km > 90000 or car_age >= 4:
        factor_distributie = 0.50
    else:
        factor_distributie = 0.20

    # 3. Ambreiaj / Cutie automată:
    # La cutie manuală: disc/volantă cedează între 150k - 250k km
    # La automată: schimb ulei mecatronică la fiecare 60k km
    is_auto = False
    if transmission and any(w in str(transmission).lower() for w in ['aut', 'dsg', 'edc', 's-tronic', 'steptronic']):
        is_auto = True

    if km > 200000:
        factor_ambreiaj = 0.75
    elif km > 140000:
        factor_ambreiaj = 0.50
    else:
        factor_ambreiaj = 0.25

    # 4. Sistem frânare (discuri + plăcuțe)
    if km > 120000 or car_age >= 5:
        factor_frane = 0.80
    else:
        factor_frane = 0.50

    # 5. Suspensie (drumurile din România solicită bucșele și brațele)
    if km > 150000 or car_age >= 6:
        factor_suspensie = 0.80
    elif km > 90000:
        factor_suspensie = 0.50
    else:
        factor_suspensie = 0.30

    # 6. Cosmetică & Detailing (polish faruri, polish zgârieturi, detailing interior)
    factor_cosmetica = 1.0

    # Ajustare pentru tip combustibil (motoarele diesel au piese de distribuție/ambreiaj/filtre mai scumpe)
    fuel_multiplier = 1.15 if fuel_type and 'diesel' in str(fuel_type).lower() else 1.0

    breakdown = {}
    total_parts = 0.0
    total_labor = 0.0

    components = [
        ("revizie", factor_revizie),
        ("distributie", factor_distributie),
        ("ambreiaj_transmisie", factor_ambreiaj),
        ("frane", factor_frane),
        ("suspensie", factor_suspensie),
        ("cosmetica_detailing", factor_cosmetica),
    ]

    for comp_name, factor in components:
        base_p = parts_db.get(comp_name, 200)
        # Aplicăm ajustare diesel pentru revizie, distribuție și ambreiaj
        if comp_name in ["revizie", "distributie", "ambreiaj_transmisie"]:
            base_p *= fuel_multiplier

        # Cost ponderat
        cost_piese = round(base_p * factor, 2)
        cost_manopera = round(cost_piese * labor_rate, 2)

        breakdown[comp_name] = {
            "piese": cost_piese,
            "manopera": cost_manopera,
            "total": round(cost_piese + cost_manopera, 2)
        }
        total_parts += cost_piese
        total_labor += cost_manopera

    subtotal = total_parts + total_labor
    buffer_neprevazute = round(subtotal * 0.10, 2)  # 10% rezervă neprevăzute
    total_maintenance = round(subtotal + buffer_neprevazute, 2)

    return {
        "brand_tier": tier,
        "total_maintenance_cost": total_maintenance,
        "total_parts": round(total_parts, 2),
        "total_labor": round(total_labor, 2),
        "contingency_buffer": buffer_neprevazute,
        "breakdown": breakdown,
        "car_age": car_age,
        "mileage_km": km
    }


def calculate_net_profit(
    predicted_market_price: float,
    asked_price: float,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    mileage_km: Optional[int] = None,
    fuel_type: Optional[str] = None,
    transmission: Optional[str] = None,
    safety_margin_eur: float = 300.0
) -> Dict[str, Any]:
    """
    Calculează marja de profit reală (economică) pentru un vehicul:
    Profit Net = Preț Estimat Vânzare - Preț Achiziție - Cost Recondiționare - Marjă Siguranță / Cheltuieli Acte
    """
    maint_info = estimate_maintenance_cost(
        brand=brand,
        model=model,
        year=year,
        mileage_km=mileage_km,
        fuel_type=fuel_type,
        transmission=transmission
    )
    maint_cost = maint_info["total_maintenance_cost"]

    gross_profit = round(predicted_market_price - asked_price, 2)
    net_profit = round(gross_profit - maint_cost - safety_margin_eur, 2)

    total_invested = asked_price + maint_cost + safety_margin_eur
    roi_pct = round((net_profit / total_invested) * 100, 1) if total_invested > 0 else 0.0
    discount_pct = round((gross_profit / predicted_market_price) * 100, 1) if predicted_market_price > 0 else 0.0

    is_profitable = net_profit > 0 and roi_pct >= 8.0

    return {
        "asked_price": asked_price,
        "predicted_market_price": predicted_market_price,
        "gross_profit_margin": gross_profit,
        "discount_pct": discount_pct,
        "maintenance_cost": maint_cost,
        "safety_margin_eur": safety_margin_eur,
        "total_investment": round(total_invested, 2),
        "net_profit_margin": net_profit,
        "net_roi_pct": roi_pct,
        "is_profitable": is_profitable,
        "maintenance_details": maint_info
    }


if __name__ == "__main__":
    test_eval = calculate_net_profit(
        predicted_market_price=12500,
        asked_price=9800,
        brand="Volkswagen",
        model="Golf",
        year=2018,
        mileage_km=145000,
        fuel_type="Diesel"
    )
    print("=== TEST MAINTENANCE & NET PROFIT ESTIMATOR ===")
    print(f"Pret vanzator:        {test_eval['asked_price']:,.0f} €")
    print(f"Valoare estimata ML:  {test_eval['predicted_market_price']:,.0f} €")
    print(f"Profit Brut:          +{test_eval['gross_profit_margin']:,.0f} € (-{test_eval['discount_pct']}%)")
    print(f"Cost Reconditionare:  {test_eval['maintenance_cost']:,.0f} € (Tier: {test_eval['maintenance_details']['brand_tier']})")
    print(f"Profit NET Real:      +{test_eval['net_profit_margin']:,.0f} € (ROI: {test_eval['net_roi_pct']}%)")
    print(f"Este rentabila?       {'DA' if test_eval['is_profitable'] else 'NU'}")
    print("\nDefalcare piese + manopera:")
    for k, v in test_eval['maintenance_details']['breakdown'].items():
        print(f"  * {k:<20}: {v['piese']} € (piese) + {v['manopera']} € (manopera) = {v['total']} €")
