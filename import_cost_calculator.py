# FILE: import_cost_calculator.py
"""
Modul de calcul detaliat pentru costul de oportunitate și cheltuielile reale de import auto
din Europa de Vest (Germania, Austria, Olanda, Belgia, Italia, Franța) în România.

Calculează "negru pe alb" două scenarii de achiziție:
1. SCENARIUL "PE ROȚI" (Deplasare personală):
   - Transport dus (avion low-cost / autocar / tren local)
   - Combustibil pe traseu (distanță km x consum mediu x preț carburant UE)
   - Taxe de drum și viniete (Austria, Ungaria, România, tuneluri)
   - Numere provizorii de export / tranzit (Kurzzeitkennzeichen 5 zile sau Ausfuhrkennzeichen 15/30 zile)
   - Cazare pe traseu (hotel 1-2 nopți) și hrană/diurnă
   - Costul de oportunitate al timpului (zile de concediu/muncă pierdute evaluate la o rată zilnică)
   - RAR România (CIV, ITP, Certificat de Autenticitate)
   - Traduceri autorizate ale actelor + taxe numere definitive DRPCIV

2. SCENARIUL "PLATFORMĂ" (TIR / Trailer autorizat):
   - Tarif transport pe platformă în regim de grupaj (pe regiuni/țări)
   - Raport tehnic/verificare la distanță (CarVertical / Dekra)
   - RAR România + Traduceri + Taxe înmatriculare
   - ZERO timp pierdut, ZERO uzură, ZERO risc de accident pe 1.800 km!

Toate variabilele sunt salvate în `data/import_config.json` și pot fi actualizate dinamic.
"""

import os
import sys
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
import datetime
from typing import Dict, Any, Optional

CONFIG_FILE_PATH = os.path.join("data", "import_config.json")

# Distanțe medii (km) de la centre auto majore până în România (București/Arad mediat)
DEFAULT_DISTANCES_KM = {
    "DE_SOUTH": 1450,  # München, Nürnberg, Stuttgart
    "DE_CENTRAL": 1750, # Frankfurt, Köln, Leipzig
    "DE_NORTH": 1950,  # Berlin, Hamburg, Hannover
    "AT": 1050,        # Viena, Linz, Graz
    "NL": 2050,        # Amsterdam, Utrecht, Rotterdam
    "BE": 1950,        # Bruxelles, Antwerpen, Gent
    "IT_NORTH": 1500,  # Milano, Verona, Bologna
    "FR_EAST": 1900,   # Strasbourg, Lyon, Metz
}

# Configurări implicite aduse la zi (2026)
DEFAULT_IMPORT_CONFIG: Dict[str, Any] = {
    "metadata": {
        "version": "1.0.0",
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d"),
        "description": "Parametri dinamici pentru calculul costului de import auto din Europa de Vest"
    },
    "fuel": {
        "fuel_price_eur_per_liter": 1.75,       # Preț mediu motorină/benzină pe autostrăzile UE (DE/AT/HU)
        "avg_consumption_l_100km": 6.8          # Consum mediu pe traseu de autostradă
    },
    "vignettes_and_tolls": {
        "austria_vignette_10days_eur": 11.50,   # Vinietă Austria 10 zile
        "austria_special_tolls_eur": 13.50,     # Pasul Phyrn / Tauern / tuneluri specifice
        "hungary_matrica_10days_eur": 18.00,    # Matrica Ungaria 10 zile (~7.000 HUF)
        "romania_rovinieta_eur": 3.50,          # Rovinietă România 7/30 zile
        "czech_slovakia_transit_eur": 14.00     # Opțional dacă ruta ocolește prin Cehia/Slovacia
    },
    "transit_plates_germany": {
        "yellow_short_term_5days_eur": 110.0,   # Kurzzeitkennzeichen (plăcuțe galbene, asigurare, taxe)
        "red_export_15days_eur": 230.0,         # Ausfuhrkennzeichen (plăcuțe roșii oficiale, carte verde, taxe)
        "austria_green_plates_eur": 210.0,      # Überstellungskennzeichen (Austria)
        "netherlands_export_eur": 160.0         # Plăcuțe export RDW Olanda
    },
    "travel_and_stay": {
        "flight_or_bus_ticket_eur": 110.0,      # Bilet avion low-cost (WizzAir/Ryanair/Lufthansa) spre Germania
        "local_transport_to_dealer_eur": 35.0,  # Tren local / taxi de la aeroport până la dealer
        "hotel_per_night_eur": 75.0,            # Cazare 1 noapte la motel/hotel pe traseu
        "nights_needed": 1,                     # Număr nopți de cazare
        "daily_food_allowance_eur": 25.0,       # Diurnă mâncare/băuturi pe zi
        "trip_duration_days": 2.5               # Durată totală deplasare (zile)
    },
    "opportunity_cost": {
        "time_cost_per_day_eur": 75.0,          # Valoarea timpului investit (ziua de lucru/concediu a persoanei)
        "risk_buffer_eur": 100.0                # Fond neprevăzut (pene, bec ars, abateri traseu, curs valutar)
    },
    "platform_rates": {
        # Tarife transport pe trailer / platformă autorizată în regim de grupaj (adus la scară)
        "DE_SOUTH": 650.0,
        "DE_CENTRAL": 750.0,
        "DE_NORTH": 850.0,
        "AT": 580.0,
        "NL": 850.0,
        "BE": 850.0,
        "IT_NORTH": 720.0,
        "FR_EAST": 880.0,
        "remote_inspection_report_eur": 50.0    # Raport verificare tehnică la distanță (CarVertical / Dekra)
    },
    "romania_registration": {
        "rar_inspection_and_civ_eur": 160.0,    # RAR: Carte de Identitate Vehicul, ITP și Certificat Autenticitate (~800 RON)
        "authorized_translations_eur": 30.0,    # Traducere autorizată acte (Brief mare/mic, factură/contract) (~150 RON)
        "police_drpciv_plates_eur": 25.0,       # Taxă certificat înmatriculare + plăcuțe de înmatriculare negre (~120 RON)
        "rca_estimate_eur": 180.0               # Poliță RCA 1 an România (estimare medie)
    }
}


def load_import_config() -> Dict[str, Any]:
    """Încarcă fișierul de configurare sau creează fișierul implicit dacă nu există."""
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    
    # Salvează configurarea inițială
    save_import_config(DEFAULT_IMPORT_CONFIG)
    return DEFAULT_IMPORT_CONFIG


def save_import_config(config: Dict[str, Any]) -> bool:
    """Actualizează fișierul de configurare JSON."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
        config["metadata"]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_country_region_key(country_code: str, city_or_zip: Optional[str] = None) -> str:
    """Identifică regiunea pentru stabilirea distanței și tarifului de transport."""
    cc = str(country_code).upper().strip()
    if cc in ["D", "DE", "GERMANIA", "GERMANY"]:
        if city_or_zip:
            c_low = str(city_or_zip).lower()
            if any(w in c_low for w in ["münchen", "munchen", "stuttgart", "nürnberg", "nurnberg", "augsburg", "regensburg"]):
                return "DE_SOUTH"
            elif any(w in c_low for w in ["berlin", "hamburg", "hannover", "bremen", "rostock", "kiel"]):
                return "DE_NORTH"
        return "DE_CENTRAL"
    elif cc in ["A", "AT", "AUSTRIA"]:
        return "AT"
    elif cc in ["NL", "OLANDA", "NETHERLANDS"]:
        return "NL"
    elif cc in ["B", "BE", "BELGIA", "BELGIUM"]:
        return "BE"
    elif cc in ["I", "IT", "ITALIA", "ITALY"]:
        return "IT_NORTH"
    elif cc in ["F", "FR", "FRANTA", "FRANCE"]:
        return "FR_EAST"
    return "DE_CENTRAL"


def calculate_import_costs(
    country_code: str = "DE",
    city_or_zip: Optional[str] = None,
    car_purchase_price_eur: float = 10000.0,
    expected_romanian_selling_price_eur: Optional[float] = None,
    fuel_consumption_override: Optional[float] = None,
    use_export_plates: bool = True,  # True = numere roșii (15/30 zile), False = galbene (5 zile)
    include_opportunity_cost: bool = True
) -> Dict[str, Any]:
    """
    Calculează negru pe alb costul exact de procurare și adus în România pentru ambele scenarii:
    1. Mers personal ("Pe roți")
    2. Aducere pe platformă specializată

    Returnează defalcarea completă pe categorii, diferența dintre cele două metode
    și analiza de rentabilitate economică (marjă netă și ROI).
    """
    cfg = load_import_config()
    region_key = get_country_region_key(country_code, city_or_zip)
    distance_km = DEFAULT_DISTANCES_KM.get(region_key, 1750)

    # 1. PARAMETRI COMUN (Birocrație România)
    rar_eur = cfg["romania_registration"]["rar_inspection_and_civ_eur"]
    translations_eur = cfg["romania_registration"]["authorized_translations_eur"]
    plates_drpciv_eur = cfg["romania_registration"]["police_drpciv_plates_eur"]
    common_ro_bureaucracy = rar_eur + translations_eur + plates_drpciv_eur

    # 2. SCENARIUL "PE ROȚI" (Deplasare personală)
    # A. Combustibil
    cons = fuel_consumption_override or cfg["fuel"]["avg_consumption_l_100km"]
    fuel_price = cfg["fuel"]["fuel_price_eur_per_liter"]
    fuel_cost = round((distance_km / 100.0) * cons * fuel_price, 2)

    # B. Viniete & Taxe de drum
    vignettes = (
        cfg["vignettes_and_tolls"]["austria_vignette_10days_eur"] +
        cfg["vignettes_and_tolls"]["austria_special_tolls_eur"] +
        cfg["vignettes_and_tolls"]["hungary_matrica_10days_eur"] +
        cfg["vignettes_and_tolls"]["romania_rovinieta_eur"]
    )

    # C. Numere de tranzit / export
    if region_key.startswith("DE"):
        transit_plates = (
            cfg["transit_plates_germany"]["red_export_15days_eur"] if use_export_plates
            else cfg["transit_plates_germany"]["yellow_short_term_5days_eur"]
        )
    elif region_key == "AT":
        transit_plates = cfg["transit_plates_germany"]["austria_green_plates_eur"]
    elif region_key in ["NL", "BE"]:
        transit_plates = cfg["transit_plates_germany"]["netherlands_export_eur"]
    else:
        transit_plates = 200.0

    # D. Deplasare & Cazare
    flight_or_bus = cfg["travel_and_stay"]["flight_or_bus_ticket_eur"]
    local_transport = cfg["travel_and_stay"]["local_transport_to_dealer_eur"]
    hotel = cfg["travel_and_stay"]["hotel_per_night_eur"] * cfg["travel_and_stay"]["nights_needed"]
    food = cfg["travel_and_stay"]["daily_food_allowance_eur"] * cfg["travel_and_stay"]["trip_duration_days"]
    travel_expenses = flight_or_bus + local_transport + hotel + food

    # E. Cost de Oportunitate al Timpului & Fond Risc
    opp_time = (
        cfg["opportunity_cost"]["time_cost_per_day_eur"] * cfg["travel_and_stay"]["trip_duration_days"]
        if include_opportunity_cost else 0.0
    )
    risk_buffer = cfg["opportunity_cost"]["risk_buffer_eur"]

    total_personal_trip = (
        fuel_cost +
        vignettes +
        transit_plates +
        travel_expenses +
        opp_time +
        risk_buffer +
        common_ro_bureaucracy
    )

    # 3. SCENARIUL "PLATFORMĂ" (TIR / Trailer specializat)
    platform_base_fee = cfg["platform_rates"].get(region_key, 750.0)
    remote_inspection = cfg["platform_rates"].get("remote_inspection_report_eur", 50.0)
    
    total_platform = platform_base_fee + remote_inspection + common_ro_bureaucracy

    # 4. RECOMANDARE ȘI COMPARATIE
    cheaper_option = "platform" if total_platform < total_personal_trip else "personal_trip"
    cost_difference = abs(round(total_personal_trip - total_platform, 2))

    # 5. RENTABILITATE ECONOMICĂ (DACĂ AVEM PREȚ ESTIMAT DE VÂNZARE ÎN RO)
    financials = None
    if expected_romanian_selling_price_eur and expected_romanian_selling_price_eur > 0:
        total_investment_personal = car_purchase_price_eur + total_personal_trip
        total_investment_platform = car_purchase_price_eur + total_platform
        
        net_profit_personal = round(expected_romanian_selling_price_eur - total_investment_personal, 2)
        net_profit_platform = round(expected_romanian_selling_price_eur - total_investment_platform, 2)
        
        roi_personal_pct = round((net_profit_personal / total_investment_personal) * 100.0, 1)
        roi_platform_pct = round((net_profit_platform / total_investment_platform) * 100.0, 1)

        financials = {
            "expected_ro_sale_price_eur": expected_romanian_selling_price_eur,
            "scenario_personal": {
                "total_invested_eur": round(total_investment_personal, 2),
                "net_profit_eur": net_profit_personal,
                "roi_pct": roi_personal_pct,
                "is_profitable": net_profit_personal > 1000.0
            },
            "scenario_platform": {
                "total_invested_eur": round(total_investment_platform, 2),
                "net_profit_eur": net_profit_platform,
                "roi_pct": roi_platform_pct,
                "is_profitable": net_profit_platform > 1000.0
            }
        }

    return {
        "origin_country": country_code.upper(),
        "region_key": region_key,
        "distance_km": distance_km,
        "car_purchase_price_eur": car_purchase_price_eur,
        "scenarios": {
            "personal_trip": {
                "name": "Deplasare Personală (Pe roți)",
                "total_cost_eur": round(total_personal_trip, 2),
                "breakdown": {
                    "fuel_eur": round(fuel_cost, 2),
                    "vignettes_and_tolls_eur": round(vignettes, 2),
                    "transit_plates_eur": round(transit_plates, 2),
                    "transport_dus_eur": round(flight_or_bus + local_transport, 2),
                    "hotel_and_food_eur": round(hotel + food, 2),
                    "time_opportunity_cost_eur": round(opp_time, 2),
                    "risk_buffer_eur": round(risk_buffer, 2),
                    "romania_rar_and_registration_eur": round(common_ro_bureaucracy, 2)
                },
                "days_spent": cfg["travel_and_stay"]["trip_duration_days"],
                "km_added_to_car": distance_km
            },
            "platform_transport": {
                "name": "Transport Trailer / Platformă (Fără deplasare)",
                "total_cost_eur": round(total_platform, 2),
                "breakdown": {
                    "platform_transport_fee_eur": round(platform_base_fee, 2),
                    "remote_history_check_eur": round(remote_inspection, 2),
                    "romania_rar_and_registration_eur": round(common_ro_bureaucracy, 2)
                },
                "days_spent": 0.0,
                "km_added_to_car": 0
            }
        },
        "comparison": {
            "recommended_method": cheaper_option,
            "savings_with_recommended_eur": cost_difference,
            "summary_ro": (
                f"Platforma este cu {cost_difference:,.0f} € mai ieftină și elimină {distance_km} km de uzură și 2.5 zile pierdute pe drum."
                if cheaper_option == "platform" else
                f"Deplasarea personală este cu {cost_difference:,.0f} € mai ieftină dacă timpul tău nu este calculat strict ca venit pierdut."
            )
        },
        "financials": financials
    }


if __name__ == "__main__":
    print("=== TEST CALCULATOR COSTURI IMPORT (NEGRU PE ALB) ===")
    res = calculate_import_costs(
        country_code="DE",
        city_or_zip="München",
        car_purchase_price_eur=12000.0,
        expected_romanian_selling_price_eur=15500.0
    )
    print(f"Origine: {res['origin_country']} ({res['region_key']}) | Distanță: {res['distance_km']} km")
    print("\n--- 1. Deplasare Personală (Pe roți) ---")
    p = res["scenarios"]["personal_trip"]
    print(f"Total: {p['total_cost_eur']} € | Timp: {p['days_spent']} zile | Km parcurși: {p['km_added_to_car']} km")
    for k, v in p["breakdown"].items():
        print(f"  * {k}: {v} €")

    print("\n--- 2. Transport pe Platformă (TIR) ---")
    t = res["scenarios"]["platform_transport"]
    print(f"Total: {t['total_cost_eur']} € | Timp pierdut: 0 zile | Km adăugați: 0")
    for k, v in t["breakdown"].items():
        print(f"  * {k}: {v} €")

    print(f"\nRecomandare: {res['comparison']['summary_ro']}")
    if res["financials"]:
        f_plat = res["financials"]["scenario_platform"]
        print(f"\nProfit NET estimat prin Platformă: +{f_plat['net_profit_eur']} € (ROI {f_plat['roi_pct']}%)")
