# FILE: tests/test_fallbacks.py
"""
Teste Automate de Unitate pentru Mecanismele de Fallback pe Toate Sistemele.
Verifică funcționarea corectă și reziliența în condiții de eroare/lipsă resurse:
1. Lanț de descărcare rețea (Fallback Engine)
2. Parsare Schema.org JSON-LD și fallback Regex pe text
3. Buffer de urgență bază de date (Recovery Buffer)
4. Coadă persistentă de alerte (Alert Outbox)
5. Motor de evaluare multi-tier (Valuation Engine)
6. Curs valutar cu fallback multi-nivel (Currency Helper)
7. Decodor VIN cu suport format european (VIN Checker)
8. Parsare carduri Autovit și OLX din taguri statice fără Playwright
"""

import os
import json
import pytest
import pandas as pd
from bs4 import BeautifulSoup


class TestNetworkAndParsingFallbacks:
    def test_json_ld_car_extraction(self):
        from fallback_engine import extract_json_ld_car_data

        sample_html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Car",
                "name": "BMW Seria 3 320d xDrive",
                "brand": {"@type": "Brand", "name": "BMW"},
                "model": "Seria 3",
                "productionDate": "2019",
                "mileageFromOdometer": {"@type": "QuantitativeValue", "value": "135000"},
                "fuelType": "Diesel",
                "offers": {
                    "@type": "Offer",
                    "price": "17500",
                    "priceCurrency": "EUR",
                    "url": "https://example.com/bmw-320d-ID1234.html"
                }
            }
            </script>
        </head>
        <body><div>Card normal</div></body>
        </html>
        """
        extracted = extract_json_ld_car_data(sample_html)
        assert len(extracted) == 1
        car = extracted[0]
        assert car["brand"] == "BMW"
        assert car["model"] == "Seria 3"
        assert car["year"] == 2019
        assert car["mileage_km"] == 135000
        assert car["price"] == 17500.0
        assert car["currency"] == "EUR"

    def test_regex_card_fallback(self):
        from fallback_engine import extract_regex_card_fallback

        text = "Vand Volkswagen Golf 7, an 2018, 142.500 km, motor 2.0 diesel, pret 11.800 EUR negociabil"
        data = extract_regex_card_fallback(text)
        assert data.get("year") == 2018
        assert data.get("mileage_km") == 142500
        assert data.get("price") == 11800.0
        assert data.get("currency") == "EUR"
        assert data.get("fuel_type") == "Diesel"


class TestDatabaseRecoveryBuffer:
    def test_recovery_buffer_append_and_drain(self, tmp_path):
        import fallback_engine
        from fallback_engine import DatabaseRecoveryBuffer

        test_buf = str(tmp_path / "test_recovery_buffer.jsonl")
        orig_buf = fallback_engine.RECOVERY_BUFFER_PATH
        fallback_engine.RECOVERY_BUFFER_PATH = test_buf

        try:
            records = [
                {"title": "Audi A4 2019", "price": 16500, "car_id": "test_1"},
                {"title": "BMW X3 2020", "price": 24500, "car_id": "test_2"}
            ]

            buf = DatabaseRecoveryBuffer()
            buf.append_failed_records("test_source", records)

            assert os.path.exists(test_buf)

            # Testăm drenarea în SQLite mock
            drained_calls = []

            def mock_save(df, src):
                drained_calls.append((src, len(df)))
                return {"new": len(df), "updated": 0}

            reingested = buf.drain_buffer_to_sqlite(mock_save)
            assert reingested == 2
            assert len(drained_calls) == 1
            assert drained_calls[0][0] == "test_source"
            # Bufferul ar trebui să fie șters după drenare reușită
            assert not os.path.exists(test_buf)
        finally:
            fallback_engine.RECOVERY_BUFFER_PATH = orig_buf


class TestAlertOutbox:
    def test_alert_outbox_queue_and_clear(self, tmp_path):
        import fallback_engine
        from fallback_engine import AlertOutboxManager

        test_outbox = str(tmp_path / "test_alerts_outbox.jsonl")
        orig_outbox = fallback_engine.OUTBOX_PATH
        fallback_engine.OUTBOX_PATH = test_outbox

        try:
            mgr = AlertOutboxManager()
            mgr.enqueue_alert("telegram", "Chilipir nou BMW", {"price": 12000})
            mgr.enqueue_alert("discord", "Scadere pret VW Golf", {"drop": 800})

            pending = mgr.get_pending_alerts()
            assert len(pending) == 2
            assert pending[0]["channel"] == "telegram"
            assert pending[1]["channel"] == "discord"

            mgr.clear_outbox()
            assert len(mgr.get_pending_alerts()) == 0
        finally:
            fallback_engine.OUTBOX_PATH = orig_outbox


class TestValuationMultiTierEngine:
    def test_valuation_engine_tiers(self):
        from valuation_engine import valuation_engine

        # Evaluare pentru un model comun
        res = valuation_engine.estimate_price(
            brand="Volkswagen",
            model="Golf",
            year=2019,
            mileage_km=130000,
            fuel_type="Diesel"
        )

        assert "predicted_price_eur" in res
        assert res["predicted_price_eur"] > 3000
        assert "valuation_tier" in res
        assert res["valuation_tier"] in ["ml_xgboost", "ml_rf", "db_statistical", "depreciation_curve", "segment_baseline"]
        assert "confidence_score" in res
        assert 0.0 < res["confidence_score"] <= 1.0
        assert "price_low_eur" in res
        assert "price_high_eur" in res
        assert res["price_low_eur"] <= res["predicted_price_eur"] <= res["price_high_eur"]

    def test_valuation_heuristic_fallback(self):
        from valuation_engine import valuation_engine

        # Testăm algoritmul euristic direct
        res = valuation_engine._estimate_heuristic_depreciation(
            brand="BMW",
            model="Seria 3",
            year=2018,
            mileage_km=140000,
            fuel_type="Diesel"
        )
        assert res["predicted_price_eur"] > 5000
        assert res["valuation_tier"] == "depreciation_curve"
        assert res["confidence_score"] >= 0.65


class TestCurrencyHelper:
    def test_currency_conversion_and_fallback(self):
        from currency_helper import convert_to_eur, get_exchange_rate

        # EUR -> EUR
        assert convert_to_eur(15000.0, "EUR") == 15000.0

        # RON -> EUR (ar trebui să fie în jur de 5.09)
        val_eur = convert_to_eur(50900.0, "RON")
        assert 9000.0 <= val_eur <= 11000.0

        # Verificare curs
        rate_info = get_exchange_rate("EUR")
        assert rate_info["rate"] >= 4.0
        assert rate_info["source"] in ["live_api", "disk_cache", "hardcoded_fallback"]


class TestVinEuropeanFallback:
    def test_european_vin_handling(self):
        from vin_checker import decode_vin

        # VIN european VW (Golf) - are 'Z' pe poziția 9 (nu are checksum FMVSS american)
        vw_eu_vin = "WVWZZZAUZEP012345"
        res = decode_vin(vw_eu_vin)
        assert res["is_valid"] is True
        assert res["status"] in ["VALID", "VALID_EU_FORMAT"]
        assert res["manufacturer"] == "Volkswagen"
        assert res["country"] == "Germania"

    def test_vin_online_with_fallback(self):
        from vin_checker import check_vin_online_with_fallback

        res = check_vin_online_with_fallback("WBA12345678901234")
        assert "is_valid" in res
        assert "BMW" in res["manufacturer"]


class TestScrapersDirectCardParsing:
    def test_autovit_card_parsing_from_html(self):
        from scraper_autovit import parse_autovit_card

        sample_card_html = """
        <article data-id="12345">
            <h2><a href="https://www.autovit.ro/anunt/bmw-seria-3-ID12345.html">BMW Seria 3 320d</a></h2>
            <h3>14 500</h3>
            <p>EUR</p>
            <ul class="ooa-1o0axny"><li><p>Bucuresti</p></li><li><p>Dealer</p></li></ul>
            <dd data-parameter="year">2019</dd>
            <dd data-parameter="mileage">145 000 km</dd>
            <dd data-parameter="fuel_type">Diesel</dd>
        </article>
        """
        data = parse_autovit_card(sample_card_html)
        assert data.get("title") == "BMW Seria 3 320d"
        assert data.get("price") == 14500
        assert data.get("year") == 2019
        assert data.get("mileage_km") == 145000

    def test_olx_card_parsing_from_html(self):
        from scraper_olx import parse_olx_card

        sample_olx_html = """
        <div data-cy="l-card">
            <a href="https://www.olx.ro/d/oferta/vw-golf-7-IDabc123.html">
                <h6>Volkswagen Golf 7 1.6 TDI</h6>
            </a>
            <p data-testid="ad-price">9 800 €</p>
            <p data-testid="location-date">Cluj-Napoca - 28 octombrie</p>
            <span class="css-1">2017</span>
            <span class="css-2">165 000 km</span>
        </div>
        """
        data = parse_olx_card(sample_olx_html)
        assert data.get("title") == "Volkswagen Golf 7 1.6 TDI"
        assert data.get("price") == 9800
        assert data.get("currency") == "EUR"
        assert data.get("car_id") == "abc123"
