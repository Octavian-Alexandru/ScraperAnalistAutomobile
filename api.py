# FILE: api.py
"""
REST API profesional pentru Radarul Comercial Auto construit cu FastAPI.
Permite integrarea de către aplicații mobile, CRM-uri de dealeri și sisteme externe.

Documentație interactivă automată disponibilă la:
- Swagger UI: http://localhost:8000/docs
- ReDoc:      http://localhost:8000/redoc
"""

import os
import sys
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_db_stats, get_price_drops, get_all_listings_df, DB_PATH
from deal_scorer import compute_deal_score
from maintenance_estimator import estimate_maintenance_cost, calculate_net_profit
from liquidity_tracker import get_model_liquidity, get_top_liquid_models
from seller_intelligence import get_seller_profile
from watchlist_manager import add_watchlist_rule, get_all_watchlists
from api_auth import verify_api_key, generate_api_key, get_all_api_keys, deactivate_api_key, get_usage_stats
from data_exporter import get_market_valuation, calculate_residual_value, export_market_report
from deduplicator import get_top_spreads

app = FastAPI(
    title="Radar Comercial Auto - REST API",
    description="API comercial pentru estimare ML, arbitraj, calcul costuri recondiționare și urmărire lichiditate auto în România.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- SCHEME PYDANTIC PENTRU REQUEST & RESPONSE ---
class ImportCalculationRequest(BaseModel):
    country_code: str = Field("DE", json_schema_extra={"example": "DE"})
    city_or_zip: Optional[str] = Field(None, json_schema_extra={"example": "München"})
    car_purchase_price_eur: float = Field(..., gt=0, json_schema_extra={"example": 12000.0})
    expected_romanian_selling_price_eur: Optional[float] = Field(None, json_schema_extra={"example": 15500.0})
    buyer_type: str = Field("persoana_fizica", json_schema_extra={"example": "srl_platitor_tva_vies"})
    vat_deductible: bool = Field(True, json_schema_extra={"example": True})
    use_export_plates: bool = Field(True, json_schema_extra={"example": True})
    include_opportunity_cost: bool = Field(True, json_schema_extra={"example": True})


class CarEstimateRequest(BaseModel):
    brand: str = Field(..., json_schema_extra={"example": "BMW"})
    model: str = Field(..., json_schema_extra={"example": "Seria 3"})
    year: int = Field(..., ge=2005, le=2026, json_schema_extra={"example": 2019})
    mileage_km: int = Field(..., ge=0, le=500000, json_schema_extra={"example": 140000})
    fuel_type: Optional[str] = Field("Diesel", json_schema_extra={"example": "Diesel"})
    engine_size: Optional[float] = Field(2.0, json_schema_extra={"example": 2.0})
    trim: Optional[str] = Field("Standard", json_schema_extra={"example": "M Sport"})
    asked_price: Optional[float] = Field(None, json_schema_extra={"example": 13500.0})
    seller_type: Optional[str] = Field("Particular", json_schema_extra={"example": "Particular"})


class WatchlistCreateRequest(BaseModel):
    user_name: str = Field(..., json_schema_extra={"example": "Alexandru"})
    brand: Optional[str] = Field(None, json_schema_extra={"example": "BMW"})
    model: Optional[str] = Field(None, json_schema_extra={"example": "X3"})
    min_year: Optional[int] = Field(2018, json_schema_extra={"example": 2018})
    max_year: Optional[int] = Field(2022, json_schema_extra={"example": 2022})
    max_price_eur: Optional[float] = Field(20000.0, json_schema_extra={"example": 20000.0})
    max_mileage_km: Optional[int] = Field(150000, json_schema_extra={"example": 150000})
    min_deal_score: Optional[int] = Field(75, json_schema_extra={"example": 75})
    contact_channel: Optional[str] = Field("telegram", json_schema_extra={"example": "telegram"})
    contact_target: Optional[str] = Field("@dealeralex", json_schema_extra={"example": "@dealeralex"})


# --- ENDPOINT-URI PRINCIPALE ---
@app.get("/", tags=["Sistem"])
def root():
    return {
        "status": "online",
        "service": "Radar Comercial Auto API",
        "version": "2.0.0",
        "docs_url": "/docs"
    }


@app.get("/health", tags=["Sistem"])
def health_check():
    stats = get_db_stats()
    return {
        "status": "healthy",
        "database": "connected",
        "total_listings": stats["total_listings"],
        "active_listings": stats["active_listings"],
        "timestamp": datetime.datetime.now().isoformat()
    }


@app.post("/api/v1/estimate", tags=["Evaluare & Arbitraj"])
def estimate_car_value(req: CarEstimateRequest, user=Depends(verify_api_key)):
    """Estimează valoarea reală de piață a unui autoturism, costurile de recondiționare și Deal Score-ul."""
    from valuation_engine import valuation_engine
    val_res = valuation_engine.estimate_price(
        brand=req.brand,
        model=req.model,
        year=req.year,
        mileage_km=req.mileage_km,
        fuel_type=req.fuel_type,
        engine_size=req.engine_size,
        trim=req.trim
    )

    pred_price = val_res["predicted_price_eur"]
    model_used = val_res["model_details"]
    asked = req.asked_price or pred_price

    deal = compute_deal_score(
        predicted_market_price=pred_price,
        asked_price=asked,
        brand=req.brand,
        model=req.model,
        year=req.year,
        mileage_km=req.mileage_km,
        fuel_type=req.fuel_type,
        seller_type=req.seller_type
    )

    return {
        "predicted_market_price_eur": pred_price,
        "asked_price_eur": asked,
        "valuation_tier": val_res["valuation_tier"],
        "confidence_score": val_res["confidence_score"],
        "price_range": {
            "low_eur": val_res["price_low_eur"],
            "high_eur": val_res["price_high_eur"],
            "mae_eur": val_res["mae_eur"]
        },
        "model_engine": model_used,
        "deal_score": deal["deal_score"],
        "badge": deal["badge"],
        "recommendation": deal["recommendation"],
        "target_buy_offer_eur": deal["target_buy_offer_eur"],
        "financial_breakdown": deal["financials"],
        "liquidity": deal["liquidity"],
        "calculated_at": datetime.datetime.now().isoformat()
    }


@app.get("/api/v1/price-drops", tags=["Radar Preturi"])
def list_price_drops(days: int = Query(7, ge=1, le=30), min_drop: float = Query(150.0, ge=50), user=Depends(verify_api_key)):
    """Returnează mașinile cu preț redus în ultimele zile."""
    drops = get_price_drops(days=days, min_drop_eur=min_drop)
    if drops.empty:
        return {"count": 0, "results": []}
    return {
        "count": len(drops),
        "days_filter": days,
        "min_drop_eur": min_drop,
        "results": drops.to_dict(orient="records")
    }


@app.get("/api/v1/liquidity", tags=["Lichiditate & Piata"])
def get_liquidity(brand: Optional[str] = None, model: Optional[str] = None, year: Optional[int] = None, user=Depends(verify_api_key)):
    """Returnează indicatorii de lichiditate și durata medie de vânzare."""
    if brand and model:
        data = get_model_liquidity(brand, model, year)
        return data
    else:
        top_models = get_top_liquid_models(limit=15)
        return {"top_liquid_models": top_models.to_dict(orient="records")}


@app.get("/api/v1/seller/{seller_name}", tags=["Seller Intelligence"])
def get_seller(seller_name: str, user=Depends(verify_api_key)):
    """Profilare comerciant / detectare samsar deghizat."""
    profile = get_seller_profile(seller_name)
    return profile


@app.get("/api/v1/watchlists", tags=["Watchlist"])
def list_watchlists():
    return {"watchlists": get_all_watchlists(active_only=True)}


@app.post("/api/v1/watchlists", tags=["Watchlist"])
def create_watchlist(req: WatchlistCreateRequest, user=Depends(verify_api_key)):
    rule_id = add_watchlist_rule(
        user_name=req.user_name,
        brand=req.brand,
        model=req.model,
        min_year=req.min_year,
        max_year=req.max_year,
        max_price_eur=req.max_price_eur,
        max_mileage_km=req.max_mileage_km,
        min_deal_score=req.min_deal_score or 70,
        contact_channel=req.contact_channel or "telegram",
        contact_target=req.contact_target
    )
    return {"status": "created", "rule_id": rule_id}


# --- ENDPOINT-URI NOI: Valuare Piață, Export, Admin ---

@app.get("/api/v1/valuation", tags=["Evaluare & Arbitraj"])
def market_valuation(
    brand: str = Query(..., description="Marca (ex: BMW)"),
    model: str = Query(..., description="Modelul (ex: Seria 3)"),
    year: int = Query(..., ge=2005, le=2026),
    mileage_km: int = Query(..., ge=0, le=500000),
    fuel_type: Optional[str] = None,
    user=Depends(verify_api_key)
):
    """Valuare de piață pentru companii de asigurări — preț median, min, max, intervale de încredere."""
    return get_market_valuation(brand, model, year, mileage_km, fuel_type)


@app.get("/api/v1/residual-value", tags=["Evaluare & Arbitraj"])
def residual_value(
    brand: str = Query(...),
    model: str = Query(...),
    year: int = Query(..., ge=2005, le=2026),
    mileage_km: int = Query(..., ge=0, le=500000),
    lease_months: int = Query(36, ge=12, le=72),
    annual_km: int = Query(15000, ge=5000, le=50000),
    user=Depends(verify_api_key)
):
    """Estimare valoare reziduală pentru firme de leasing."""
    return calculate_residual_value(brand, model, year, mileage_km, lease_months, annual_km)


@app.get("/api/v1/duplicates", tags=["Cross-Platform"])
def list_duplicates(
    min_spread: float = Query(300, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user=Depends(verify_api_key)
):
    """Returnează mașini duplicate pe platforme diferite cu diferență de preț."""
    df = get_top_spreads(limit=limit, min_spread=min_spread)
    if df.empty:
        return {"count": 0, "results": []}
    return {"count": len(df), "results": df.to_dict(orient="records")}


@app.post("/api/v1/import/calculate", tags=["Import & Cross-Border"])
def api_calculate_import_costs(req: ImportCalculationRequest):
    """
    Calculează negru pe alb costurile de import (Deplasare personală vs Platformă)
    și rentabilitatea economică (cu avantaj fiscal Netto pe firmă VIES).
    """
    from import_cost_calculator import calculate_import_costs
    return calculate_import_costs(
        country_code=req.country_code,
        city_or_zip=req.city_or_zip,
        car_purchase_price_eur=req.car_purchase_price_eur,
        expected_romanian_selling_price_eur=req.expected_romanian_selling_price_eur,
        use_export_plates=req.use_export_plates,
        include_opportunity_cost=req.include_opportunity_cost,
        buyer_type=req.buyer_type,
        vat_deductible=req.vat_deductible
    )


@app.get("/api/v1/import/top-deals", tags=["Import & Cross-Border"])
def api_get_top_import_deals(
    min_profit_eur: float = Query(1500.0, ge=100.0),
    min_roi_pct: float = Query(12.0, ge=1.0),
    limit: int = Query(20, ge=1, le=100),
    buyer_type: str = Query("persoana_fizica", pattern="^(persoana_fizica|srl_platitor_tva_vies)$")
):
    """
    Returnează cele mai profitabile oportunități de import din Germania, Austria și Europa de Vest.
    """
    from cross_border_arbitrage import find_top_import_arbitrage_deals
    df = find_top_import_arbitrage_deals(
        min_profit_eur=min_profit_eur,
        min_roi_pct=min_roi_pct,
        limit=limit,
        buyer_type=buyer_type
    )
    if df.empty:
        return {"count": 0, "results": []}
    return {"count": len(df), "results": df.to_dict(orient="records")}


@app.post("/api/v1/admin/generate-key", tags=["Admin"])
def admin_generate_key(
    owner_name: str = Query(...),
    owner_email: str = Query(""),
    plan: str = Query("free", pattern="^(free|pro|business)$")
):
    """Generează un nou API key (endpoint admin — protejează în producție!)."""
    return generate_api_key(owner_name, owner_email, plan)


@app.get("/api/v1/admin/keys", tags=["Admin"])
def admin_list_keys():
    """Listează toate API key-urile (fără hash complet)."""
    return {"keys": get_all_api_keys()}


@app.get("/api/v1/admin/usage", tags=["Admin"])
def admin_usage_stats(days: int = Query(7, ge=1, le=30)):
    """Statistici de utilizare API pe ultimele N zile."""
    return {"usage": get_usage_stats(days)}


if __name__ == "__main__":
    import uvicorn
    print("[*] Pornim serverul API FastAPI pe http://127.0.0.1:8000...")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
