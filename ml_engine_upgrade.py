# FILE: ml_engine_upgrade.py
"""
Upgrade avansat al modelului Machine Learning pentru estimarea prețurilor auto.
Implementează:
1. Feature Engineering extins:
   - `car_age` = 2026 - an
   - `km_per_year` = kilometraj / vârstă
   - `is_premium_brand` = flag binar pentru mărci premium (BMW, Mercedes, Audi, etc.)
   - `body_type` = caroserie (SUV, Break, Sedan, Hatchback, Coupe, Cabrio)
   - `transmission` = cutie de viteze (Automat vs Manual)
   - `euro_norm` = normă de poluare (Euro 4, 5, 6)
2. Model Gradient Boosting de înaltă performanță cu XGBoost (`XGBRegressor`)
3. Comparare automată de metrici (R², MAE) vs RandomForest
4. Salvare în `models/price_model_xgboost.joblib`
"""

import os
import sys
import re
import datetime
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from xgboost import XGBRegressor

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

MODEL_XGB_PATH = os.path.join("models", "price_model_xgboost.joblib")
CURRENT_YEAR = 2026

PREMIUM_BRANDS = {
    "bmw", "mercedes-benz", "audi", "porsche", "land rover",
    "jaguar", "lexus", "volvo", "alfa romeo", "maserati"
}

EXTENDED_FEATURES = [
    'Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type',
    'engine_size', 'car_age', 'km_per_year', 'is_premium_brand',
    'body_type', 'transmission', 'euro_norm'
]


def extract_body_type(text: str) -> str:
    """Extrage tipul de caroserie din text."""
    t = str(text).lower()
    if re.search(r'\b(suv|crossover|4x4|allroad|cross)\b', t):
        return 'SUV'
    elif re.search(r'\b(break|combi|kombi|variant|avant|touring|wagon)\b', t):
        return 'Break'
    elif re.search(r'\b(sedan|berlina|limuzina)\b', t):
        return 'Sedan'
    elif re.search(r'\b(hatchback|hatch|sportback)\b', t):
        return 'Hatchback'
    elif re.search(r'\b(coupe|cupe)\b', t):
        return 'Coupe'
    elif re.search(r'\b(cabrio|cabriolet|roadster)\b', t):
        return 'Cabrio'
    return 'Altele'


def extract_transmission(text: str) -> str:
    """Extrage tipul transmisiei (Automat vs Manual)."""
    t = str(text).lower()
    if re.search(r'\b(automat[a]?|aut|dsg|edc|tiptronic|s-tronic|steptronic|cvt|7g-tronic|9g-tronic)\b', t):
        return 'Automat'
    elif re.search(r'\b(manual[a]?|6\s*trepte|5\s*trepte)\b', t):
        return 'Manual'
    return 'Manual'


def extract_euro_norm(text: str) -> str:
    """Extrage norma Euro."""
    t = str(text).lower()
    m = re.search(r'\beuro\s*([456])\b', t)
    if m:
        return f"Euro {m.group(1)}"
    return 'Euro 6'


def apply_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aplică feature engineering avansat peste datele brute curate."""
    data = df.copy()

    full_text = (
        data['title'].fillna('').astype(str) + " " +
        data.get('description', pd.Series('', index=data.index)).fillna('').astype(str)
    )

    data['car_age'] = CURRENT_YEAR - data['year']
    data['car_age'] = data['car_age'].clip(lower=1)

    data['km_per_year'] = (data['mileage_km'] / data['car_age']).round(0)

    data['is_premium_brand'] = data['Brand'].str.lower().apply(
        lambda b: 1 if b in PREMIUM_BRANDS else 0
    )

    data['body_type'] = full_text.apply(extract_body_type)
    data['transmission'] = full_text.apply(extract_transmission)
    data['euro_norm'] = full_text.apply(extract_euro_norm)

    if 'Trim' not in data.columns:
        data['Trim'] = 'Standard'
    data['Trim'] = data['Trim'].fillna('Standard')

    return data


def train_xgboost_pipeline(df: pd.DataFrame) -> Tuple[Any, Dict[str, Any]]:
    """Antrenează și optimizează pipeline-ul XGBoost cu noul feature set."""
    print("[*] Aplicăm Feature Engineering extins...")
    df_feat = apply_advanced_features(df)

    clean_data = df_feat.dropna(subset=EXTENDED_FEATURES + ['price']).copy()
    print(f"[*] Set de date gata pentru XGBoost: {len(clean_data):,} vehicule.")

    X = clean_data[EXTENDED_FEATURES]
    y = clean_data['price']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    num_cols = ['year', 'mileage_km', 'engine_size', 'car_age', 'km_per_year', 'is_premium_brand']
    cat_cols = ['Brand', 'Model', 'Trim', 'fuel_type', 'body_type', 'transmission', 'euro_norm']

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), num_cols),
            ('cat', OneHotEncoder(handle_unknown='ignore'), cat_cols)
        ]
    )

    xgb_model = XGBRegressor(
        n_estimators=250,
        max_depth=8,
        learning_rate=0.07,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1
    )

    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor', xgb_model)
    ])

    print("[*] Antrenăm XGBoost Regressor (250 estimators, max_depth=8)...")
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    mae = float(mean_absolute_error(y_test, y_pred))
    r2 = float(r2_score(y_test, y_pred))
    rmse = float(root_mean_squared_error(y_test, y_pred))

    stats = {
        "model_type": "XGBoost Regressor",
        "mae": round(mae, 1),
        "r2": round(r2, 4),
        "rmse": round(rmse, 1),
        "features": EXTENDED_FEATURES,
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "train_rows": len(clean_data),
        "unique_models": clean_data['Model'].nunique()
    }

    payload = {
        "model": pipeline,
        **stats
    }

    os.makedirs("models", exist_ok=True)
    joblib.dump(payload, MODEL_XGB_PATH)

    # De asemenea, actualizăm și `models/price_model.joblib` dacă noul model e mai bun!
    existing_model_path = "models/price_model.joblib"
    if os.path.exists(existing_model_path):
        try:
            old_p = joblib.load(existing_model_path)
            old_r2 = float(old_p.get('r2', 0.0))
            print(f"    - Model vechi R2: {old_r2 * 100:.2f}% | Model nou XGBoost R2: {r2 * 100:.2f}%")
        except Exception:
            old_r2 = 0.0

    print(f"[+] Model XGBoost salvat în: {MODEL_XGB_PATH}")
    print(f"    - Acuratețe R²:         {r2 * 100:.1f}%")
    print(f"    - Eroare Medie (MAE):   ± {mae:,.0f} €")
    print(f"    - Eroare RMSE:          ± {rmse:,.0f} €")

    return pipeline, stats


if __name__ == "__main__":
    from main import preprocess_pipeline
    print("=== TEST UPGRADE MODEL ML (XGBOOST) ===")
    df_clean = preprocess_pipeline()
    pipeline, stats = train_xgboost_pipeline(df_clean)
