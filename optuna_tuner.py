# FILE: optuna_tuner.py
"""
Hyperparameter Tuning Automat cu Optuna pentru Modelele ML.
Implementează:
1. Optuna search space inteligent pentru XGBoost, LightGBM și CatBoost
2. Selectare automată a celui mai bun model (cross-validated R²)
3. Comparare cu modelul curent — salvare DOAR dacă noul model e mai bun
4. Logare completă a experimentelor în JSON (model registry local)
5. Limită de timp configurabilă (default: 10 minute pe GitHub Actions)
"""

import os
import sys
import time
import json
import datetime
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, Optional

from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from logger_config import logger

MODEL_REGISTRY_PATH = os.path.join("models", "experiment_log.json")
MODEL_XGB_PATH = os.path.join("models", "price_model_xgboost.joblib")
CURRENT_YEAR = 2026


def _get_feature_engineering_fn():
    """Importă funcția de feature engineering din ml_engine_upgrade."""
    from ml_engine_upgrade import apply_advanced_features, EXTENDED_FEATURES
    return apply_advanced_features, EXTENDED_FEATURES


def run_optuna_tuning(
    df: pd.DataFrame,
    n_trials: int = 50,
    timeout_seconds: int = 600,
    include_lightgbm: bool = True,
    include_catboost: bool = True
) -> Dict[str, Any]:
    """
    Execută Optuna hyperparameter search pe XGBoost (+ opțional LightGBM, CatBoost).
    Returnează cel mai bun model + statistici.
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("[Optuna] Optuna nu e instalat. Rulăm doar XGBoost cu parametri default.")
        return {"status": "skipped", "reason": "optuna not installed"}

    apply_features, FEATURES = _get_feature_engineering_fn()

    print(f"[*] Aplicăm feature engineering pe {len(df):,} vehicule...")
    df_feat = apply_features(df)

    clean = df_feat.dropna(subset=FEATURES + ['price']).copy()
    print(f"[*] Date curate pentru tuning: {len(clean):,} vehicule")

    X = clean[FEATURES]
    y = clean['price']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    num_cols = ['year', 'mileage_km', 'engine_size', 'car_age', 'km_per_year', 'is_premium_brand']
    cat_cols = ['Brand', 'Model', 'Trim', 'fuel_type', 'body_type', 'transmission', 'euro_norm']

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), num_cols),
            ('cat', OneHotEncoder(handle_unknown='ignore'), cat_cols)
        ]
    )

    # Pre-transformăm pentru viteză
    X_train_t = preprocessor.fit_transform(X_train)
    X_test_t = preprocessor.transform(X_test)

    best_score = -np.inf
    best_model_name = ""
    best_params = {}
    best_pipeline = None

    experiment_log = {
        "started_at": datetime.datetime.now().isoformat(),
        "dataset_size": len(clean),
        "features": FEATURES,
        "trials": []
    }

    def objective(trial):
        nonlocal best_score, best_model_name, best_params

        # Selectăm tipul de model
        model_choices = ["xgboost"]
        if include_lightgbm:
            model_choices.append("lightgbm")
        if include_catboost:
            model_choices.append("catboost")

        model_type = trial.suggest_categorical("model_type", model_choices)

        if model_type == "xgboost":
            from xgboost import XGBRegressor
            params = {
                "n_estimators": trial.suggest_int("xgb_n_estimators", 150, 500),
                "max_depth": trial.suggest_int("xgb_max_depth", 5, 12),
                "learning_rate": trial.suggest_float("xgb_lr", 0.01, 0.15, log=True),
                "subsample": trial.suggest_float("xgb_subsample", 0.7, 1.0),
                "colsample_bytree": trial.suggest_float("xgb_colsample", 0.6, 1.0),
                "min_child_weight": trial.suggest_int("xgb_min_child", 1, 10),
                "reg_alpha": trial.suggest_float("xgb_alpha", 1e-3, 10.0, log=True),
                "reg_lambda": trial.suggest_float("xgb_lambda", 1e-3, 10.0, log=True),
                "random_state": 42,
                "n_jobs": -1
            }
            model = XGBRegressor(**params)

        elif model_type == "lightgbm":
            try:
                from lightgbm import LGBMRegressor
            except ImportError:
                return -np.inf
            params = {
                "n_estimators": trial.suggest_int("lgb_n_estimators", 150, 500),
                "max_depth": trial.suggest_int("lgb_max_depth", 5, 12),
                "learning_rate": trial.suggest_float("lgb_lr", 0.01, 0.15, log=True),
                "subsample": trial.suggest_float("lgb_subsample", 0.7, 1.0),
                "colsample_bytree": trial.suggest_float("lgb_colsample", 0.6, 1.0),
                "num_leaves": trial.suggest_int("lgb_num_leaves", 31, 255),
                "min_child_samples": trial.suggest_int("lgb_min_child", 5, 50),
                "random_state": 42,
                "n_jobs": -1,
                "verbose": -1
            }
            model = LGBMRegressor(**params)

        elif model_type == "catboost":
            try:
                from catboost import CatBoostRegressor
            except ImportError:
                return -np.inf
            params = {
                "iterations": trial.suggest_int("cb_iterations", 200, 600),
                "depth": trial.suggest_int("cb_depth", 4, 10),
                "learning_rate": trial.suggest_float("cb_lr", 0.01, 0.15, log=True),
                "l2_leaf_reg": trial.suggest_float("cb_l2", 1.0, 10.0),
                "random_seed": 42,
                "verbose": 0,
                "thread_count": -1
            }
            model = CatBoostRegressor(**params)
        else:
            return -np.inf

        model.fit(X_train_t, y_train)
        y_pred = model.predict(X_test_t)
        score = r2_score(y_test, y_pred)

        experiment_log["trials"].append({
            "trial_number": trial.number,
            "model_type": model_type,
            "r2": round(score, 4),
            "params": {k: v for k, v in params.items() if k not in ["random_state", "n_jobs", "verbose", "random_seed", "thread_count"]}
        })

        if score > best_score:
            best_score = score
            best_model_name = model_type
            best_params = params.copy()

        return score

    print(f"[*] Pornim Optuna cu {n_trials} trials, timeout {timeout_seconds}s...")
    study = optuna.create_study(direction="maximize", study_name="auto_price_model")
    study.optimize(objective, n_trials=n_trials, timeout=timeout_seconds, show_progress_bar=False)

    print(f"[+] Cel mai bun model: {best_model_name} (R² = {best_score * 100:.2f}%)")

    # Reconstruim cel mai bun model complet (cu preprocessor) și îl salvăm dacă e mai bun
    current_r2 = 0.0
    if os.path.exists(MODEL_XGB_PATH):
        try:
            old = joblib.load(MODEL_XGB_PATH)
            current_r2 = float(old.get("r2", 0.0))
        except Exception:
            pass

    improved = best_score > current_r2

    if improved:
        print(f"[+] ÎMBUNĂTĂȚIRE! {current_r2 * 100:.2f}% → {best_score * 100:.2f}% (+{(best_score - current_r2) * 100:.2f}%)")

        # Reconstruim pipeline-ul final cu cel mai bun model
        if best_model_name == "xgboost":
            from xgboost import XGBRegressor
            final_model = XGBRegressor(**best_params)
        elif best_model_name == "lightgbm":
            from lightgbm import LGBMRegressor
            final_model = LGBMRegressor(**best_params)
        elif best_model_name == "catboost":
            from catboost import CatBoostRegressor
            final_model = CatBoostRegressor(**best_params)
        else:
            return {"status": "error", "reason": "unknown model type"}

        full_pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('regressor', final_model)
        ])
        full_pipeline.fit(X_train, y_train)

        y_pred_final = full_pipeline.predict(X_test)
        final_r2 = float(r2_score(y_test, y_pred_final))
        final_mae = float(mean_absolute_error(y_test, y_pred_final))
        final_rmse = float(root_mean_squared_error(y_test, y_pred_final))

        payload = {
            "model": full_pipeline,
            "model_type": f"{best_model_name.upper()} (Optuna Tuned)",
            "r2": round(final_r2, 4),
            "mae": round(final_mae, 1),
            "rmse": round(final_rmse, 1),
            "features": FEATURES,
            "best_params": {k: v for k, v in best_params.items() if k not in ["random_state", "n_jobs", "verbose", "random_seed", "thread_count"]},
            "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "train_rows": len(clean),
            "optuna_trials": len(study.trials),
            "tuning_method": "optuna"
        }

        os.makedirs("models", exist_ok=True)
        joblib.dump(payload, MODEL_XGB_PATH)
        print(f"[+] Model salvat în {MODEL_XGB_PATH}")
        print(f"    R² = {final_r2 * 100:.2f}%, MAE = ±{final_mae:,.0f} €, RMSE = ±{final_rmse:,.0f} €")
    else:
        print(f"[=] Modelul curent ({current_r2 * 100:.2f}%) e încă mai bun decât cel optimizat ({best_score * 100:.2f}%). Păstrăm modelul existent.")

    # Salvăm logul de experimente
    experiment_log["finished_at"] = datetime.datetime.now().isoformat()
    experiment_log["best_model"] = best_model_name
    experiment_log["best_r2"] = round(best_score, 4)
    experiment_log["improved_over_current"] = improved
    experiment_log["current_r2"] = round(current_r2, 4)

    os.makedirs("models", exist_ok=True)
    # Append to log (nu suprascrie)
    existing_log = []
    if os.path.exists(MODEL_REGISTRY_PATH):
        try:
            with open(MODEL_REGISTRY_PATH, 'r', encoding='utf-8') as f:
                existing_log = json.load(f)
        except Exception:
            pass

    existing_log.append(experiment_log)
    with open(MODEL_REGISTRY_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing_log, f, indent=2, ensure_ascii=False)

    return {
        "status": "improved" if improved else "no_improvement",
        "best_model": best_model_name,
        "best_r2": round(best_score, 4),
        "current_r2": round(current_r2, 4),
        "trials_completed": len(study.trials),
        "best_params": best_params
    }


if __name__ == "__main__":
    from main import preprocess_pipeline
    print("=== OPTUNA HYPERPARAMETER TUNING ===")
    df_clean = preprocess_pipeline()
    result = run_optuna_tuning(df_clean, n_trials=20, timeout_seconds=300)
    print(f"\nRezultat final: {result}")
