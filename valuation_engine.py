# FILE: valuation_engine.py
"""
Motor Multi-Nivel de Estimare a Prețului de Piață (Valuation Multi-Tier Fallback Engine).
Garantează că ORICE vehicul primește o evaluare corectă de piață, chiar dacă
modelele Machine Learning lipsesc de pe disc sau datele de intrare sunt atipice.

Lanț de Evaluare:
Nivel 1: Model ML XGBoost Regressor (Acuratețe R2 ~92%, eroare MAE redusă)
Nivel 2: Model ML RandomForest (Model de bază stabil)
Nivel 3: Mediană Statistică din Baza de Date SQLite (grupare Brand + Model + An ± 1 an)
Nivel 4: Algoritm Euristic de Depreciere Europeană (MSRP Nou - Decădere Anuală - Corecție Rulaj)
Nivel 5: Medie Segmentică Globală pe categorii de vechime
"""

import os
import sys
import sqlite3
import joblib
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import DB_PATH, get_connection
from logger_config import logger

CURRENT_YEAR = 2026

# Estimări MSRP mașină nouă pe segmente și mărci (pentru algoritmul euristic)
SEGMENT_MSRP_MAP = {
    # Mărci de volum / economice
    "dacia": 18000.0,
    "renault": 25000.0,
    "fiat": 22000.0,
    "ford": 28000.0,
    "opel": 27000.0,
    "peugeot": 29000.0,
    "citroen": 26000.0,
    "hyundai": 28000.0,
    "kia": 28000.0,
    "skoda": 31000.0,
    "seat": 28000.0,
    "volkswagen": 34000.0,
    "toyota": 33000.0,
    "nissan": 30000.0,
    "mazda": 32000.0,
    "honda": 34000.0,

    # Mărci Premium
    "bmw": 54000.0,
    "mercedes-benz": 58000.0,
    "mercedes": 58000.0,
    "audi": 52000.0,
    "volvo": 50000.0,
    "lexus": 55000.0,
    "alfa romeo": 44000.0,
    "land rover": 68000.0,
    "jaguar": 60000.0,
    "porsche": 105000.0,
    "maserati": 115000.0
}

# Bonusuri specifice modelelor populare (raportate la clasa medie)
MODEL_MSRP_MULTIPLIER = {
    "golf": 1.0,
    "passat": 1.3,
    "touareg": 2.2,
    "tiguan": 1.25,
    "seria 3": 1.0,
    "seria 5": 1.45,
    "seria 7": 2.1,
    "x3": 1.25,
    "x5": 1.8,
    "clasa c": 1.0,
    "clasa e": 1.45,
    "clasa s": 2.2,
    "gle": 1.85,
    "a3": 0.85,
    "a4": 1.0,
    "a6": 1.45,
    "q5": 1.25,
    "q7": 1.8,
    "octavia": 1.0,
    "superb": 1.35,
    "duster": 1.15,
    "logan": 0.85
}


class MultiTierValuationEngine:
    """Motor de estimare multi-tier cu fallback garantat."""

    def __init__(
        self,
        xgb_path: str = "models/price_model_xgboost.joblib",
        rf_path: str = "models/price_model.joblib",
        db_path: str = DB_PATH
    ):
        self.xgb_path = xgb_path
        self.rf_path = rf_path
        self.db_path = db_path
        self._xgb_payload = None
        self._rf_payload = None

    def _load_model(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        try:
            return joblib.load(path)
        except Exception as e:
            logger.debug(f"[Valuation] Nu s-a putut încărca modelul din {path}: {e}")
            return None

    def estimate_price(
        self,
        brand: str,
        model: str,
        year: int,
        mileage_km: int,
        fuel_type: Optional[str] = None,
        engine_size: Optional[float] = None,
        trim: Optional[str] = None,
        body_type: Optional[str] = None,
        transmission: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluează prețul corect de piață al unei mașini folosind lanțul complet de fallback.
        Returnează întotdeauna o estimare validă, intervalul de încredere și nivelul aplicat.
        """
        brand_clean = str(brand).strip().title() if brand else "Necunoscut"
        model_clean = str(model).strip() if model else "Necunoscut"
        year_clean = int(year) if year and 1990 <= int(year) <= CURRENT_YEAR + 1 else 2018
        km_clean = max(100, int(mileage_km)) if mileage_km is not None else 150000
        fuel_clean = str(fuel_type).capitalize() if fuel_type else "Diesel"

        # -------------------------------------------------------------
        # NIVEL 1: MODEL ML XGBOOST
        # -------------------------------------------------------------
        if self._xgb_payload is None:
            self._xgb_payload = self._load_model(self.xgb_path)

        if self._xgb_payload and 'model' in self._xgb_payload:
            try:
                ml_model = self._xgb_payload['model']
                features = self._xgb_payload.get('features', [])
                mae = float(self._xgb_payload.get('mae', 1200.0))

                car_age = max(1, CURRENT_YEAR - year_clean)
                row_data = {
                    'Brand': brand_clean,
                    'Model': model_clean,
                    'Trim': trim or 'Standard',
                    'year': year_clean,
                    'mileage_km': km_clean,
                    'fuel_type': fuel_clean,
                    'engine_size': float(engine_size or 2.0),
                    'car_age': car_age,
                    'km_per_year': round(km_clean / car_age),
                    'is_premium_brand': 1 if brand_clean.lower() in ["bmw", "mercedes-benz", "audi", "porsche", "volvo"] else 0,
                    'body_type': body_type or 'Sedan',
                    'transmission': transmission or 'Manual',
                    'euro_norm': 'Euro 6' if year_clean >= 2015 else 'Euro 5'
                }
                df_input = pd.DataFrame([row_data])
                avail_feats = [f for f in features if f in df_input.columns]
                pred = float(ml_model.predict(df_input[avail_feats])[0])

                if 800 <= pred <= 250000:
                    return {
                        "predicted_price_eur": round(pred, 0),
                        "valuation_tier": "ml_xgboost",
                        "confidence_score": 0.94,
                        "mae_eur": round(mae, 0),
                        "price_low_eur": round(max(500, pred - mae), 0),
                        "price_high_eur": round(pred + mae, 0),
                        "model_details": f"XGBoost Regressor (MAE: ±{mae:,.0f} €)"
                    }
            except Exception as e:
                logger.debug(f"[Valuation] Nivel 1 (XGBoost) a eșuat la predicție ({e}). Trecem la Nivelul 2...")

        # -------------------------------------------------------------
        # NIVEL 2: MODEL ML RANDOM FOREST
        # -------------------------------------------------------------
        if self._rf_payload is None:
            self._rf_payload = self._load_model(self.rf_path)

        if self._rf_payload and 'model' in self._rf_payload:
            try:
                rf_model = self._rf_payload['model']
                rf_feats = self._rf_payload.get('features', ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size'])
                rf_mae = float(self._rf_payload.get('mae', 1600.0))

                row_rf = {
                    'Brand': brand_clean,
                    'Model': model_clean,
                    'Trim': trim or 'Standard',
                    'year': year_clean,
                    'mileage_km': km_clean,
                    'fuel_type': fuel_clean,
                    'engine_size': float(engine_size or 2.0)
                }
                df_rf = pd.DataFrame([row_rf])
                avail = [f for f in rf_feats if f in df_rf.columns]
                pred_rf = float(rf_model.predict(df_rf[avail])[0])

                if 800 <= pred_rf <= 250000:
                    return {
                        "predicted_price_eur": round(pred_rf, 0),
                        "valuation_tier": "ml_rf",
                        "confidence_score": 0.88,
                        "mae_eur": round(rf_mae, 0),
                        "price_low_eur": round(max(500, pred_rf - rf_mae), 0),
                        "price_high_eur": round(pred_rf + rf_mae, 0),
                        "model_details": f"RandomForest Pipeline (MAE: ±{rf_mae:,.0f} €)"
                    }
            except Exception as e:
                logger.debug(f"[Valuation] Nivel 2 (RF) a eșuat ({e}). Trecem la Nivelul 3 (Statistici DB)...")

        # -------------------------------------------------------------
        # NIVEL 3: MEDIANĂ STATISTICĂ DIN BAZA DE DATE SQLITE
        # -------------------------------------------------------------
        stat_eval = self._estimate_from_db_stats(brand_clean, model_clean, year_clean, km_clean)
        if stat_eval:
            return stat_eval

        # -------------------------------------------------------------
        # NIVEL 4: ALGORITM EURISTIC DE DEPRECIERE EUROPEANĂ
        # -------------------------------------------------------------
        heuristic_eval = self._estimate_heuristic_depreciation(brand_clean, model_clean, year_clean, km_clean, fuel_clean)
        if heuristic_eval:
            return heuristic_eval

        # -------------------------------------------------------------
        # NIVEL 5: MEDIE GLOBALĂ DE SEGMENT (GARANTATĂ)
        # -------------------------------------------------------------
        age = max(1, CURRENT_YEAR - year_clean)
        global_fallback = max(1500.0, 30000.0 * (0.87 ** age))
        return {
            "predicted_price_eur": round(global_fallback, 0),
            "valuation_tier": "segment_baseline",
            "confidence_score": 0.50,
            "mae_eur": 2500.0,
            "price_low_eur": round(global_fallback * 0.8, 0),
            "price_high_eur": round(global_fallback * 1.2, 0),
            "model_details": "Segment Baseline Heuristic (Vechime generală)"
        }

    def _estimate_from_db_stats(
        self,
        brand: str,
        model: str,
        year: int,
        mileage_km: int
    ) -> Optional[Dict[str, Any]]:
        """Calculează mediana și intervalul de preț direct din istoricul SQLite."""
        if not os.path.exists(self.db_path):
            return None

        try:
            with get_connection(self.db_path) as conn:
                cursor = conn.cursor()
                # Căutăm mașini similare în baza de date: același an ± 1, același brand
                query = """
                    SELECT price_eur, mileage_km
                    FROM listings
                    WHERE LOWER(title) LIKE LOWER(?)
                      AND year BETWEEN ? AND ?
                      AND price_eur BETWEEN 800 AND 200000
                      AND is_active = 1
                """
                like_term = f"%{brand}%{model}%" if model and model != "Necunoscut" else f"%{brand}%"
                cursor.execute(query, (like_term, year - 1, year + 1))
                rows = cursor.fetchall()

                if len(rows) >= 3:
                    prices = [r['price_eur'] for r in rows if r['price_eur']]
                    if len(prices) >= 3:
                        median_price = float(np.median(prices))
                        q25 = float(np.percentile(prices, 25))
                        q75 = float(np.percentile(prices, 75))
                        spread = max(800.0, (q75 - q25) / 2.0)

                        # Ajustare ușoară pentru rulaj vs media lotului
                        kms = [r['mileage_km'] for r in rows if r['mileage_km']]
                        avg_km = np.mean(kms) if kms else 150000
                        km_diff = mileage_km - avg_km
                        km_adjustment = - (km_diff / 50000.0) * (median_price * 0.05)
                        adjusted_price = max(800.0, median_price + km_adjustment)

                        return {
                            "predicted_price_eur": round(adjusted_price, 0),
                            "valuation_tier": "db_statistical",
                            "confidence_score": 0.82,
                            "mae_eur": round(spread, 0),
                            "price_low_eur": round(max(500, adjusted_price - spread), 0),
                            "price_high_eur": round(adjusted_price + spread, 0),
                            "model_details": f"Mediana Statistică SQLite (eșantion: {len(prices)} vehicule similare)"
                        }
        except Exception as e:
            logger.debug(f"[Valuation] Eroare la interogarea statistică DB: {e}")

        return None

    def _estimate_heuristic_depreciation(
        self,
        brand: str,
        model: str,
        year: int,
        mileage_km: int,
        fuel_type: str
    ) -> Dict[str, Any]:
        """
        Algoritm euristic bazat pe curba matematică standard de depreciere auto.
        Formula: MSRP * (1 - r_an1) * (1 - r_an)^age * (1 - corectie_km)
        """
        b_low = brand.lower()
        m_low = model.lower()

        base_msrp = SEGMENT_MSRP_MAP.get(b_low, 32000.0)
        # Multiplicator model
        for m_key, mult in MODEL_MSRP_MULTIPLIER.items():
            if m_key in m_low:
                base_msrp *= mult
                break

        age = max(0, CURRENT_YEAR - year)

        # Rata anuală de depreciere (anul 1 e cel mai abrupt)
        if age == 0:
            residual_factor = 0.90
        elif age == 1:
            residual_factor = 0.80
        elif age <= 4:
            residual_factor = 0.80 * (0.88 ** (age - 1))
        elif age <= 8:
            residual_factor = 0.80 * (0.88 ** 3) * (0.91 ** (age - 4))
        else:
            residual_factor = 0.80 * (0.88 ** 3) * (0.91 ** 4) * (0.93 ** (age - 8))

        residual_factor = max(0.08, residual_factor)

        # Ajustare rulaj: standard 15.000 km / an
        expected_km = age * 16000 + 10000
        km_delta = mileage_km - expected_km
        # Penalizare: ~3% la fiecare 30.000 km peste medie
        km_factor = 1.0 - (km_delta / 30000.0) * 0.03
        km_factor = min(1.20, max(0.65, km_factor))

        est_price = max(1200.0, base_msrp * residual_factor * km_factor)
        spread = est_price * 0.12

        return {
            "predicted_price_eur": round(est_price, 0),
            "valuation_tier": "depreciation_curve",
            "confidence_score": 0.70,
            "mae_eur": round(spread, 0),
            "price_low_eur": round(max(500, est_price - spread), 0),
            "price_high_eur": round(est_price + spread, 0),
            "model_details": f"Curba Euristică de Depreciere (MSRP Estimativ: {base_msrp:,.0f} €)"
        }


# Instanță globală singleton
valuation_engine = MultiTierValuationEngine()
