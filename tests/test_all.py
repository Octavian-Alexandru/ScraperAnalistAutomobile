# FILE: tests/test_all.py
"""
Test Suite Automatizat pentru ScraperAnalistAutomobile.
Rulează teste unitare și de integrare pentru toate componentele cheie.
"""

import os
import sys
import pytest

# Adăugăm directorul rădăcină în path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import parse_car_title, infer_fuel_type, infer_engine_size
from maintenance_estimator import estimate_maintenance_cost, calculate_net_profit, get_brand_tier
from deal_scorer import compute_deal_score
from liquidity_tracker import get_model_liquidity
from vin_checker import extract_vin_from_text, decode_vin, validate_vin_checksum
from cross_border_arbitrage import estimate_german_market_price, analyze_cross_border_deal
from visual_analyzer import analyze_listing_visuals


class TestPreprocessing:
    def test_parse_car_title_standard(self):
        brand, model, trim = parse_car_title("Volkswagen Golf 7 2.0 TDI Highline 2018")
        assert brand == "Volkswagen"
        assert model == "Golf"
        assert "HIGHLINE" in trim.upper()

    def test_parse_car_title_bmw(self):
        brand, model, trim = parse_car_title("BMW 320d M Sport xDrive 2019")
        assert brand == "BMW"
        assert model == "Seria 3"

    def test_infer_fuel_type(self):
        row_diesel = {"fuel_type": "motorina", "title": "Audi A4 2.0 TDI"}
        assert infer_fuel_type(row_diesel) == "Diesel"

        row_electric = {"fuel_type": "", "title": "Tesla Model 3 100% electric"}
        assert infer_fuel_type(row_electric) == "Electric"

        row_hybrid = {"fuel_type": "", "title": "Toyota Prius Hybrid Plug-in"}
        assert infer_fuel_type(row_hybrid) == "Hibrid"

    def test_infer_engine_size(self):
        row = {"title": "Volkswagen Passat 2.0 TDI", "description": "motor 1968 cmc"}
        size = infer_engine_size(row)
        assert size == 2.0


class TestMaintenanceEstimator:
    def test_brand_tiers(self):
        assert get_brand_tier("BMW") == "premium"
        assert get_brand_tier("Porsche") == "luxury"
        assert get_brand_tier("Volkswagen") == "upper_mid"
        assert get_brand_tier("Ford") == "standard"
        assert get_brand_tier("Dacia") == "budget"

    def test_estimate_maintenance_cost(self):
        maint = estimate_maintenance_cost("Volkswagen", "Golf", year=2018, mileage_km=150000, fuel_type="Diesel")
        assert maint["total_maintenance_cost"] > 1000
        assert "revizie" in maint["breakdown"]
        assert "distributie" in maint["breakdown"]
        assert maint["total_parts"] > 0
        assert maint["total_labor"] > 0

    def test_calculate_net_profit(self):
        res = calculate_net_profit(
            predicted_market_price=15000,
            asked_price=10000,
            brand="Volkswagen",
            model="Golf",
            year=2019,
            mileage_km=120000,
            fuel_type="Diesel"
        )
        assert res["gross_profit_margin"] == 5000
        assert res["net_profit_margin"] < res["gross_profit_margin"]
        assert res["discount_pct"] > 0


class TestDealScorer:
    def test_compute_deal_score_range(self):
        res = compute_deal_score(
            predicted_market_price=16000,
            asked_price=12000,
            brand="BMW",
            model="Seria 3",
            year=2019,
            mileage_km=130000,
            fuel_type="Diesel"
        )
        assert 0 <= res["deal_score"] <= 100
        assert res["badge"] is not None
        assert res["target_buy_offer_eur"] > 0
        assert "net_profit_points" in res["score_breakdown"]


class TestVinChecker:
    def test_extract_vin(self):
        text = "Vand autoturism BMW, serie sasiu WBA3N5C51FK123456 in stare buna."
        vin = extract_vin_from_text(text)
        assert vin == "WBA3N5C51FK123456"

    def test_decode_vin_bmw(self):
        res = decode_vin("WBA3N5C51FK123456")
        assert res["manufacturer"] == "BMW"
        assert res["country"] == "Germania"


class TestCrossBorder:
    def test_german_price_estimation(self):
        price = estimate_german_market_price("Volkswagen", "Golf", year=2019, mileage_km=140000)
        assert price > 2000

    def test_analyze_cross_border_deal(self):
        res = analyze_cross_border_deal(
            romanian_price_eur=11000,
            brand="Volkswagen",
            model="Golf",
            year=2019,
            mileage_km=140000
        )
        assert "delta_eur" in res
        assert "verdict" in res


class TestVisualAnalyzer:
    def test_analyze_visuals(self):
        res = analyze_listing_visuals(
            image_urls=["http://example.com/1.jpg", "http://example.com/2.jpg"],
            title="Dacia Logan 2020 numere rosii"
        )
        assert 0 <= res["visual_risk_score"] <= 100
        assert res["has_red_plates"] is True


class TestApiIntegration:
    def test_api_health(self):
        import pytest
        try:
            from fastapi.testclient import TestClient
            from api import app
            client = TestClient(app)
        except (RuntimeError, ImportError) as e:
            pytest.skip(f"TestClient requires httpx2/httpx: {e}")

        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_api_estimate(self):
        import pytest
        try:
            from fastapi.testclient import TestClient
            from api import app
            client = TestClient(app)
        except (RuntimeError, ImportError) as e:
            pytest.skip(f"TestClient requires httpx2/httpx: {e}")
        payload = {
            "brand": "Volkswagen",
            "model": "Golf",
            "year": 2018,
            "mileage_km": 150000,
            "asked_price": 9500
        }
        res = client.post("/api/v1/estimate", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "deal_score" in data
        assert "predicted_market_price_eur" in data


class TestNewScrapers:
    def test_parse_mobile_card(self):
        from bs4 import BeautifulSoup
        from scraper_mobile_de import parse_mobile_card
        html = """
        <article>
            <a href="https://www.mobile.de/auto-inserat/bmw-320d-12345.html">BMW 320d M Sport</a>
            <span class="price">15.500 €</span>
            <p>05/2019, 145.000 km, Diesel</p>
            <div class="seller-info">Berlin, Germania</div>
        </article>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = parse_mobile_card(soup.find("article"))
        assert card["price"] == 15500
        assert card["year"] == 2019
        assert card["mileage_km"] == 145000
        assert card["fuel_type"] == "Diesel"

    def test_parse_lajumate_card(self):
        from bs4 import BeautifulSoup
        from scraper_lajumate import parse_lajumate_card
        html = """
        <div class="item">
            <a href="https://lajumate.ro/audi-a4-2018-98765.html" title="Audi A4 2.0 TDI 2018"></a>
            <span class="price">12.800 EUR</span>
            <p>An: 2018, 160.000 km, motorina</p>
            <span class="location">Cluj-Napoca</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = parse_lajumate_card(soup.find("div"))
        assert card["price"] == 12800
        assert card["year"] == 2018
        assert card["mileage_km"] == 160000
        assert card["fuel_type"] == "Diesel"

    def test_parse_publi24_card(self):
        from bs4 import BeautifulSoup
        from scraper_publi24 import parse_publi24_card
        html = """
        <li class="listing-item">
            <a href="https://www.publi24.ro/anunturi/vw-golf-7-112233.html">Volkswagen Golf 7</a>
            <strong class="price">9.200 EUR</strong>
            <span>2017 • 175.000 km • benzina</span>
            <span class="city">Timisoara</span>
        </li>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = parse_publi24_card(soup.find("li"))
        assert card["price"] == 9200
        assert card["year"] == 2017
        assert card["mileage_km"] == 175000
        assert card["fuel_type"] == "Benzina"

    def test_parse_tiriac_card(self):
        from bs4 import BeautifulSoup
        from scraper_tiriac_auto import parse_tiriac_card
        html = """
        <div class="product">
            <a href="https://www.tiriacautorulate.ro/auto-rulate/skoda-octavia-55667/">
                <h3>Skoda Octavia Style</h3>
            </a>
            <span class="price">14.900 €</span>
            <p>2020 • 120.000 km • diesel</p>
            <span class="location">Showroom Otopeni</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = parse_tiriac_card(soup.find("div"))
        assert card["price"] == 14900
        assert card["year"] == 2020
        assert card["mileage_km"] == 120000
        assert card["fuel_type"] == "Diesel"


class TestMultiAgentEngine:
    def test_agent_initialization(self):
        from crawler_engine import ScraperAgent, MultiAgentCrawlerEngine
        agent = ScraperAgent(agent_id=1)
        assert agent.agent_id == 1
        assert agent.session is not None
        assert "User-Agent" in agent.session.headers

        engine = MultiAgentCrawlerEngine(num_agents=3, batch_size_per_agent=2)
        assert len(engine.agents) == 3


class TestDbOptimizer:
    def test_optimize_database(self):
        from db_optimizer import optimize_database
        res = optimize_database()
        assert res["status"] == "success"
        assert res["final_size_mb"] > 0


class TestProxyManager:
    def test_proxy_health_scoring(self):
        from proxy_manager import ProxyHealth
        ph = ProxyHealth("http://1.2.3.4:8080")
        assert ph.score == 50.0  # scor neutru, neîncercat
        ph.record_success(200.0)
        assert ph.score > 50.0
        assert ph.is_alive is True

    def test_proxy_manager_init(self):
        from proxy_manager import ProxyManager
        pm = ProxyManager(fetch_free=False, max_pool_size=5, custom_proxies=["http://test:1234"])
        stats = pm.get_pool_stats()
        assert stats["total_proxies"] == 1
        assert stats["alive_proxies"] == 1

    def test_proxy_death_after_failures(self):
        from proxy_manager import ProxyHealth
        ph = ProxyHealth("http://dead:9999")
        for _ in range(3):
            ph.record_failure()
        assert ph.is_alive is False


class TestApiAuth:
    def test_generate_and_validate_key(self):
        import tempfile, os
        from api_auth import generate_api_key, validate_api_key, init_auth_tables
        db = os.path.join(tempfile.gettempdir(), "test_auth.db")
        init_auth_tables(db)
        result = generate_api_key("TestUser", "test@example.com", plan="pro", db_path=db)
        assert "api_key" in result
        assert result["plan"] == "pro"
        assert result["api_key"].startswith("rca_")

        profile = validate_api_key(result["api_key"], db_path=db)
        assert profile is not None
        assert profile["owner_name"] == "TestUser"
        assert profile["plan"] == "pro"

        # Cleanup
        try:
            os.remove(db)
        except Exception:
            pass

    def test_rate_limiting(self):
        import tempfile, os
        from api_auth import generate_api_key, check_rate_limit, init_auth_tables
        db = os.path.join(tempfile.gettempdir(), "test_rate.db")
        init_auth_tables(db)
        result = generate_api_key("RateTest", plan="free", db_path=db)
        from api_auth import validate_api_key
        profile = validate_api_key(result["api_key"], db_path=db)

        allowed, count, limit = check_rate_limit(profile["key_hash"], db_path=db)
        assert allowed is True
        assert count == 1
        assert limit == 10  # free plan

        try:
            os.remove(db)
        except Exception:
            pass


class TestAutoScout24:
    def test_parse_autoscout_card(self):
        from bs4 import BeautifulSoup
        from scraper_autoscout24 import parse_autoscout_card
        html = """
        <article>
            <a href="https://www.autoscout24.com/offers/bmw-320d-123456">BMW 320d xDrive</a>
            <h2>BMW 320d xDrive M Sport 2020</h2>
            <span data-testid="price">€ 25.990,-</span>
            <span>2020 • 98.000 km • Diesel • 140 kW</span>
        </article>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = parse_autoscout_card(soup.find("article"))
        assert card is not None
        assert card["price"] == 25990
        assert card["year"] == 2020
        assert card["mileage_km"] == 98000
        assert card["fuel_type"] == "Diesel"


class TestDeduplicator:
    def test_canonical_id_generation(self):
        from deduplicator import _compute_canonical_id, _mileage_bin
        # Același vehicul → același ID
        id1 = _compute_canonical_id("bmw", "seria 3", 2019, _mileage_bin(142000, 5000))
        id2 = _compute_canonical_id("bmw", "seria 3", 2019, _mileage_bin(143500, 5000))
        assert id1 == id2  # ambele se binning-uiesc la 140000

        # Vehicul diferit → ID diferit
        id3 = _compute_canonical_id("audi", "a4", 2019, _mileage_bin(142000, 5000))
        assert id1 != id3


class TestDataExporter:
    def test_market_valuation(self):
        from data_exporter import get_market_valuation
        val = get_market_valuation("BMW", "Seria 3", 2019, 140000)
        assert "status" in val
        # Poate fi "ok" sau "insufficient_data" depinzând de DB
        assert val["brand"] == "BMW"

    def test_residual_value(self):
        from data_exporter import calculate_residual_value
        res = calculate_residual_value("BMW", "Seria 3", 2019, 140000)
        assert "status" in res
        assert res["brand"] == "BMW"


class TestEmailDigest:
    def test_generate_html_report(self):
        from email_digest import generate_html_report
        import pandas as pd
        stats = {"total_listings": 99000, "active_listings": 85000, "new_today": 500}
        drops = pd.DataFrame([{
            "title": "BMW 320d 2019",
            "old_price": 15000,
            "new_price": 13500,
            "drop_eur": 1500,
            "url": "https://example.com/test"
        }])
        html = generate_html_report(stats, drops)
        assert "Radar Comercial Auto" in html
        assert "99,000" in html or "99000" in html
        assert "BMW 320d 2019" in html

