# FILE: tests/test_cross_border_import.py
"""
Teste unitare complete pentru modulul de import și arbitraj cross-border:
1. import_cost_calculator.py (calcul exact cheltuieli și cost de oportunitate)
2. scraper_willhaben.py (extracție anunțuri Austria din structura JSON)
3. cross_border_arbitrage.py (analiză RO vs Vest și scanare oportunități reale)
4. db_helper.py (persistență country și engine_size)
"""

import os
import pytest
import pandas as pd
from import_cost_calculator import calculate_import_costs, load_import_config, get_country_region_key
from scraper_willhaben import parse_willhaben_item
from cross_border_arbitrage import analyze_cross_border_deal, estimate_german_market_price, find_top_import_arbitrage_deals
from db_helper import get_connection, DB_PATH


class TestImportCostCalculator:
    def test_config_loaded_successfully(self):
        cfg = load_import_config()
        assert "fuel" in cfg
        assert "vignettes_and_tolls" in cfg
        assert "platform_rates" in cfg
        assert cfg["fuel"]["fuel_price_eur_per_liter"] > 1.0

    def test_region_key_detection(self):
        assert get_country_region_key("DE", "München") == "DE_SOUTH"
        assert get_country_region_key("DE", "Berlin") == "DE_NORTH"
        assert get_country_region_key("AT") == "AT"
        assert get_country_region_key("NL") == "NL"

    def test_calculate_import_costs_germany(self):
        res = calculate_import_costs(
            country_code="DE",
            city_or_zip="München",
            car_purchase_price_eur=10000.0,
            expected_romanian_selling_price_eur=13500.0
        )
        assert res["distance_km"] == 1450
        personal = res["scenarios"]["personal_trip"]
        platform = res["scenarios"]["platform_transport"]

        # Verificări defalcare cheltuieli
        assert personal["total_cost_eur"] > 800
        assert personal["breakdown"]["fuel_eur"] > 100
        assert personal["breakdown"]["vignettes_and_tolls_eur"] > 30
        assert personal["breakdown"]["transit_plates_eur"] > 100
        assert personal["breakdown"]["romania_rar_and_registration_eur"] == 215.0

        assert platform["total_cost_eur"] > 600
        assert platform["breakdown"]["platform_transport_fee_eur"] == 650.0

        # Verificare rentabilitate
        assert res["financials"] is not None
        assert res["financials"]["scenario_platform"]["net_profit_eur"] > 1000.0
        assert res["financials"]["scenario_platform"]["roi_pct"] > 10.0

    def test_calculate_import_costs_austria_cheaper(self):
        res_at = calculate_import_costs(country_code="AT", car_purchase_price_eur=10000.0)
        res_de_north = calculate_import_costs(country_code="DE", city_or_zip="Hamburg", car_purchase_price_eur=10000.0)

        # Austria este mai aproape de România => cost mai mic decât Nordul Germaniei
        cost_at = res_at["scenarios"]["platform_transport"]["total_cost_eur"]
        cost_de_north = res_de_north["scenarios"]["platform_transport"]["total_cost_eur"]
        assert cost_at < cost_de_north


class TestWillhabenScraper:
    def test_parse_willhaben_item_valid(self):
        fake_item = {
            "id": "123456789",
            "description": "BMW 320d Touring xDrive M Sport Aut.",
            "attributes": {
                "attribute": [
                    {"name": "HEADING", "values": ["BMW 320d Touring xDrive M Sport Aut."]},
                    {"name": "PRICE", "values": ["18900"]},
                    {"name": "MILEAGE", "values": ["145000"]},
                    {"name": "YEAR_MODEL", "values": ["2019"]},
                    {"name": "ENGINE/FUEL_RESOLVED", "values": ["Diesel"]},
                    {"name": "ENGINEVOLUME", "values": ["1995"]},
                    {"name": "LOCATION", "values": ["Wien"]},
                    {"name": "STATE", "values": ["Wien"]},
                    {"name": "POSTCODE", "values": ["1010"]},
                    {"name": "ISPRIVATE", "values": ["0"]},
                    {"name": "ORGNAME", "values": ["Autohaus Wien"]},
                    {"name": "SEO_URL", "values": ["gebrauchtwagen/d/auto/bmw-320d-123456789/"]}
                ]
            }
        }
        car = parse_willhaben_item(fake_item)
        assert car is not None
        assert car["car_id"] == "willhaben_123456789"
        assert car["price"] == 18900.0
        assert car["mileage_km"] == 145000
        assert car["year"] == 2019
        assert car["fuel_type"] == "Diesel"
        assert car["engine_size"] == 2.0
        assert car["country"] == "AT"
        assert "willhaben.at" in car["url"]


class TestCrossBorderArbitrage:
    def test_estimate_german_price(self):
        price = estimate_german_market_price("Volkswagen", "Passat", 2018, 160000)
        assert price > 3000

    def test_analyze_cross_border_deal_with_breakdown(self):
        res = analyze_cross_border_deal(
            romanian_price_eur=15000,
            brand="Volkswagen",
            model="Passat",
            year=2018,
            mileage_km=160000,
            origin_country="AT"
        )
        assert "import_details" in res
        assert "platform_total_eur" in res["import_details"]
        assert "delta_eur" in res
        assert res["origin_country"] == "AT"

    def test_find_top_import_deals(self):
        df_deals = find_top_import_arbitrage_deals(db_path=DB_PATH, min_profit_eur=500, min_roi_pct=5.0, limit=5)
        # Baza de date conține anunțuri din Austria culese la pasul anterior
        assert isinstance(df_deals, pd.DataFrame)
        if not df_deals.empty:
            assert "net_profit_eur" in df_deals.columns
            assert "roi_pct" in df_deals.columns
            assert "origin_country" in df_deals.columns


class TestDatabaseCountrySupport:
    def test_db_has_country_and_engine_size(self):
        with get_connection(DB_PATH) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()]
            assert "country" in cols
            assert "engine_size" in cols
