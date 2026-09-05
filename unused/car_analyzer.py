# ==============================
# CAR ANALYZER 4.5 - SISTEM COMPLET AVANSAT
# ==============================

import pandas as pd
import re, unidecode, numpy as np
import pickle, time, logging, json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error
import numpy as np
import concurrent.futures
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
from textblob import TextBlob
from sklearn.model_selection import train_test_split, RandomizedSearchCV, cross_val_score
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from xgboost import XGBRegressor
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import warnings
import plotly.express as px
import json
import plotly.graph_objs as go
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output


warnings.filterwarnings('ignore')


# ==============================
# CONFIGURARE
# ==============================
class Config:
    """Management configurare centralizat"""
    # Email settings
    EMAIL_ENABLED = False
    SMTP_SERVER = 'smtp.gmail.com'
    SMTP_PORT = 587
    EMAIL_ADDRESS = 'your_email@gmail.com'
    EMAIL_PASSWORD = 'your_password'
    ALERT_RECIPIENT = 'alerts@example.com'

    # Model settings
    MODEL_CACHE_PATH = '../trained_models/'
    MODEL_CACHE_DAYS = 7
    TRAINING_SAMPLE_SIZE = 10000

    # API settings
    VIN_DECODE_API = 'https://vindecoder.p.rapidapi.com/decode_vin'
    VIN_API_KEY = 'your_vin_api_key'
    MARKET_DATA_API = 'https://api.marketdata.com/automotive'

    # Processing settings
    MAX_WORKERS = 4
    CHUNK_SIZE = 1000

    # Scoring weights
    DATA_QUALITY_WEIGHTS = {
        'price': 0.3,
        'mileage': 0.25,
        'year': 0.2,
        'description': 0.15,
        'location': 0.1
    }

    @classmethod
    def setup_logging(cls):
        """Configurare logging avansat"""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]'
        )

        # File handler
        file_handler = logging.FileHandler(
            f'car_analyzer_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        )
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger


# Inițializare logger
logger = Config.setup_logging()

# Constante
MARCAS = [
    "fiat", "opel", "peugeot", "ford", "skoda", "dacia", "renault",
    "bmw", "audi", "mercedes", "volkswagen", "seat", "hyundai",
    "kia", "toyota", "mazda", "nissan", "volvo", "citroen", "honda"
]

DOTARI = [
    "camera spate", "senzori parcare", "incalzire scaune", "panou solar",
    "oglinzi electrice", "geamuri electrice", "aer conditionat", "cruise control",
    "pilot automat", "scaune piele", "volan incalzit", "trapa", "xenon", "bi-xenon",
    "start stop", "bluetooth", "android auto", "car play", "tempomat", "control viteza"
]

MOTORIZARE = ["gpl", "metan", "benzina+gpl", "hibrid", "electric", "plug-in hybrid"]


# ==============================
# UTILITĂȚI AVANSATE
# ==============================
def timeit(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        logger.info(f"{func.__name__} executed in {end-start:.2f}s")
        return result
    return wrapper

class EmailService:
    """Serviciu avansat pentru notificări email"""

    @staticmethod
    def send_alert(subject: str, message: str, priority: str = 'medium'):
        """Trimite alertă prin email"""
        if not Config.EMAIL_ENABLED:
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = Config.EMAIL_ADDRESS
            msg['To'] = Config.ALERT_RECIPIENT
            msg['Subject'] = f"[{priority.upper()}] {subject}"

            msg.attach(MIMEText(message, 'plain'))

            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)
                server.send_message(msg)

            logger.info(f"Email alert sent: {subject}")
            return True

        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            return False


class APIService:
    """Serviciu pentru interacțiuni cu API-uri externe"""

    @staticmethod
    def decode_vin(vin: str) -> Optional[Dict]:
        """Decodează VIN folosind API extern"""
        try:
            headers = {
                'X-RapidAPI-Key': Config.VIN_API_KEY,
                'X-RapidAPI-Host': 'vindecoder.p.rapidapi.com'
            }

            response = requests.get(
                f"{Config.VIN_DECODE_API}/{vin}",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                return response.json()

        except Exception as e:
            logger.warning(f"VIN decoding failed for {vin}: {e}")

        return None

    @staticmethod
    def get_market_trends(brand: str, model: str, year: int) -> Optional[Dict]:
        """Obține trenduri de piață pentru model specific"""
        try:
            # Simulare date de piață (în practică, s-ar folosi API real)
            time.sleep(0.1)  # Respect rate limiting

            return {
                'average_price': None,
                'price_trend': 'stable',
                'market_demand': 'medium',
                'competition_level': 'medium',
                'days_on_market_avg': 14
            }

        except Exception as e:
            logger.warning(f"Market trends API failed: {e}")
            return None


class DataQualityScorer:
    """Sistem avansat de scoring pentru calitatea datelor"""

    @staticmethod
    def calculate_data_quality(row: pd.Series) -> float:
        """Calculează scorul de calitate al datelor pentru o înregistrare"""
        score = 0.0
        weights = Config.DATA_QUALITY_WEIGHTS

        # Preț
        if pd.notna(row.get('price_eur')) and row['price_eur'] > 0:
            score += weights['price']

        # Kilometraj
        if pd.notna(row.get('mileage')) and 0 < row['mileage'] < 1000000:
            score += weights['mileage']

        # An
        if pd.notna(row.get('year_extracted')) and 1980 <= row['year_extracted'] <= datetime.now().year:
            score += weights['year']

        # Descriere
        if pd.notna(row.get('description')) and len(str(row['description'])) > 10:
            score += weights['description']

        # Locație
        if pd.notna(row.get('location')) and len(str(row['location'])) > 3:
            score += weights['location']

        return round(score * 100, 2)

    @staticmethod
    def validate_data_consistency(df: pd.DataFrame) -> pd.DataFrame:
        """Validează consistența datelor și adaugă scoruri de calitate"""
        df = df.copy()

        # Adaugă scor calitate
        df['data_quality_score'] = df.apply(DataQualityScorer.calculate_data_quality, axis=1)

        # Detectare valori suspicioase
        df['suspicious_price'] = DataQualityScorer._detect_suspicious_prices(df)
        df['suspicious_mileage'] = DataQualityScorer._detect_suspicious_mileage(df)
        df['inconsistent_year'] = DataQualityScorer._detect_inconsistent_years(df)

        # Scor de suspiciune total
        df['suspicion_score'] = (
                df['suspicious_price'] +
                df['suspicious_mileage'] +
                df['inconsistent_year']
        )

        return df

    @staticmethod
    def _detect_suspicious_prices(df: pd.DataFrame) -> pd.Series:
        """Detectează prețuri suspicioase"""
        suspicious = pd.Series(0, index=df.index)

        for brand in df['brand'].dropna().unique():
            brand_mask = df['brand'] == brand
            brand_prices = df.loc[brand_mask, 'price_eur']

            if len(brand_prices) > 5:
                Q1 = brand_prices.quantile(0.25)
                Q3 = brand_prices.quantile(0.75)
                IQR = Q3 - Q1

                lower_bound = Q1 - 3 * IQR
                upper_bound = Q3 + 3 * IQR

                suspicious.loc[brand_mask] = (
                        (df.loc[brand_mask, 'price_eur'] < lower_bound) |
                        (df.loc[brand_mask, 'price_eur'] > upper_bound)
                ).astype(int)

        return suspicious

    @staticmethod
    def _detect_suspicious_mileage(df: pd.DataFrame) -> pd.Series:
        """Detectează kilometraj suspicios"""
        suspicious = pd.Series(0, index=df.index)

        mask = (df['age'] > 0) & (df['mileage'] > 0)
        km_per_year = df.loc[mask, 'mileage'] / df.loc[mask, 'age']

        suspicious.loc[mask] = (
                (km_per_year < 500) | (km_per_year > 40000)
        ).astype(int)

        return suspicious

    @staticmethod
    def _detect_inconsistent_years(df: pd.DataFrame) -> pd.Series:
        """Detectează ani inconsistente"""
        current_year = datetime.now().year
        return (
                (df['year_extracted'] < 1980) |
                (df['year_extracted'] > current_year + 1)
        ).astype(int)

    @staticmethod
    def format_currency(value):
        try:
            return f"{float(value):,.2f} €"
        except:
            return "N/A"

    @staticmethod
    def normalize_text(text: str) -> str:
        return text.lower().strip() if isinstance(text, str) else ""

# ==============================
# PREPROCESARE AVANSATĂ
# ==============================
class AdvancedPreprocessor:
    """Sistem avansat de preprocesare a datelor"""

    @staticmethod
    def clip_extreme_profit(df: pd.DataFrame, lower=0, upper=500):
        df['profit_margin'] = df['profit_margin'].clip(lower=lower, upper=upper)
        return df

    @staticmethod
    def clean_text(text: str) -> str:
        """Curățare text avansată"""
        if not isinstance(text, str):
            return ""

        try:
            # Normalizare diacritice
            text = unidecode.unidecode(text.lower())

            # Eliminare caractere speciale, păstrând diacritice
            text = re.sub(r"[^a-z0-9ăâîșțĂÂÎȘȚ\s]", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            # Eliminare stopwords
            stopwords = {
                "vand", "se", "vinde", "oferta", "cumpar", "vanzare", "autoutilitara",
                "occasion", "second", "second hand", "sh", "rabla", "trade", "negociabil"
            }

            words = text.split()
            filtered_words = [word for word in words if word not in stopwords and len(word) > 2]

            return " ".join(filtered_words)

        except Exception as e:
            logger.error(f"Text cleaning failed: {e}")
            return ""

    @staticmethod
    def extract_sentiment(text: str) -> Dict[str, float]:
        """Analiză sentiment folosind TextBlob"""
        try:
            # Asigură-te că textul este string
            if not isinstance(text, str):
                text = str(text) if pd.notna(text) else ""

            blob = TextBlob(text)
            sentiment = blob.sentiment

            return {
                'sentiment_polarity': sentiment.polarity,
                'sentiment_subjectivity': sentiment.subjectivity
            }

        except Exception as e:
            logger.warning(f"Sentiment analysis failed: {e}")
            return {'sentiment_polarity': 0, 'sentiment_subjectivity': 0}

    @staticmethod
    def extract_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
        """Extrage caracteristici avansate din date"""
        df = df.copy()

        # Analiză sentiment
        sentiment_results = df['description'].apply(AdvancedPreprocessor.extract_sentiment)
        sentiment_df = pd.DataFrame(sentiment_results.tolist(), index=df.index)
        df = pd.concat([df, sentiment_df], axis=1)

        # Caracteristici derivate
        df['age'] = datetime.now().year - df['year_extracted']
        df['km_per_year'] = np.where(
            df['age'] > 0,
            df['mileage'] / df['age'],
            None
        )

        # Tip vehicul bazat pe caracteristici
        df['vehicle_type'] = df.apply(AdvancedPreprocessor._classify_vehicle_type, axis=1)

        return df

    @staticmethod
    def _classify_vehicle_type(row: pd.Series) -> str:
        """Clasifică tipul vehiculului bazat pe caracteristici"""
        description = str(row.get('description', '')).lower()
        title = str(row.get('title', '')).lower()

        text = f"{title} {description}"

        vehicle_types = {
            'family': ['familie', '7 locuri', 'mpv', 'monovolume', 'spatiu'],
            'luxury': ['premium', 'lux', 'executiv', 'clasa superioara'],
            'sport': ['sport', 'rs', 'm3', 'amg', 'gti', 'coupe'],
            'economic': ['economic', 'consum mic', 'eficient', 'ecologic'],
            'commercial': ['comercial', 'duba', 'transport', 'marfa']
        }

        for v_type, keywords in vehicle_types.items():
            if any(keyword in text for keyword in keywords):
                return v_type

        return 'standard'

    @staticmethod
    def clip_extreme_profit(df: pd.DataFrame, lower=0, upper=500):
        """Taie valorile extrem de mari sau negative"""
        df['profit_margin'] = df['profit_margin'].clip(lower=lower, upper=upper)
        return df

# ==============================
# ANALIZĂ AVANSATĂ
# ==============================
class AdvancedAnalyzer:
    """Sistem avansat de analiză a datelor"""

    @staticmethod
    def analyze_market_trends(df: pd.DataFrame) -> Dict:
        """Analiză trenduri de piață avansate"""
        trends = {}

        try:
            # Analiză temporală
            if 'scrape_date' in df.columns:
                df['scrape_date'] = pd.to_datetime(df['scrape_date'])
                trends['time_analysis'] = AdvancedAnalyzer._analyze_time_trends(df)

            # Analiză geografică
            if 'location' in df.columns:
                trends['geographic_analysis'] = AdvancedAnalyzer._analyze_geographic_trends(df)

            # Analiză competiție
            trends['competition_analysis'] = AdvancedAnalyzer._analyze_competition(df)

        except Exception as e:
            logger.error(f"Market trends analysis failed: {e}")

        return trends

    @staticmethod
    def _analyze_time_trends(df: pd.DataFrame) -> Dict:
        """Analiză trenduri temporale"""
        time_df = df.copy()
        time_df['scrape_week'] = time_df['scrape_date'].dt.isocalendar().week

        weekly_stats = time_df.groupby('scrape_week').agg({
            'price_eur': ['mean', 'count'],
            'mileage': 'mean'
        }).round(2)

        return {
            'weekly_price_trend': weekly_stats['price_eur']['mean'].to_dict(),
            'listing_volume': weekly_stats['price_eur']['count'].to_dict()
        }

    @staticmethod
    def _analyze_geographic_trends(df: pd.DataFrame) -> Dict:
        """Analiză trenduri geografice"""
        if 'location' not in df.columns:
            return {}

        location_stats = df.groupby('location').agg({
            'price_eur': ['mean', 'count'],
            'mileage': 'mean'
        }).round(2)

        return location_stats.to_dict()

    @staticmethod
    def _analyze_competition(df: pd.DataFrame) -> Dict:
        """Analiză competiție pentru fiecare vehicul"""
        competition_results = {}

        for idx, row in df.iterrows():
            similar_listings = df[
                (df['brand'] == row['brand']) &
                (df['model'] == row['model']) &
                (df['year_extracted'] == row['year_extracted']) &
                (df.index != idx)
                ]

            competition_results[idx] = {
                'similar_listings_count': len(similar_listings),
                'avg_competition_price': similar_listings['price_eur'].mean() if not similar_listings.empty else None,
                'min_competition_price': similar_listings['price_eur'].min() if not similar_listings.empty else None
            }

        return competition_results


# ==============================
# MODEL AVANSAT ML
# ==============================
class AdvancedModelTrainer:
    """Sistem avansat de antrenare modele ML"""

    @staticmethod
    def train_advanced_model(df):
        logger.info("Training ML model (Linear Regression)")

        # Alegem câteva features de bază
        features = ['year_extracted', 'mileage']
        target = 'price_eur'

        # Eliminăm valorile lipsă
        df_train = df.dropna(subset=features + [target])

        X = df_train[features]
        y = df_train[target]

        # Împărțim train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Model simplu de regresie liniară
        model = LinearRegression()
        model.fit(X_train, y_train)

        # Evaluare rapidă
        y_pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        logger.info(f"ML Model trained. MAE: {mae:.2f} EUR")

        # Adăugăm predicția în dataframe
        df['predicted_price'] = model.predict(df[features])

        return model, features, df

    @staticmethod
    def _prepare_training_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
        """Pregătește datele pentru antrenament"""
        # Selectare features
        numeric_features = [
            'year_extracted', 'mileage', 'engine_capacity', 'power', 'age',
            'km_per_year', 'sentiment_polarity', 'sentiment_subjectivity'
        ]

        categorical_features = [
            'brand', 'model', 'vehicle_type', 'caroserie'
        ]

        # Filtrare features existente
        numeric_features = [f for f in numeric_features if f in df.columns]
        categorical_features = [f for f in categorical_features if f in df.columns]

        feature_columns = numeric_features + categorical_features

        # Pregătește X și y
        X = df[feature_columns].copy()
        y = np.log1p(df['price_eur'])  # Log transform pentru normalizare

        # Preprocesare
        numeric_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler())
        ])

        categorical_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='constant', fill_value='missing')),
            ('onehot', OneHotEncoder(handle_unknown='ignore'))
        ])

        preprocessor = ColumnTransformer(
            transformers=[
                ('num', numeric_transformer, numeric_features),
                ('cat', categorical_transformer, categorical_features)
            ]
        )

        X_processed = preprocessor.fit_transform(X)

        return X_processed, y, feature_columns

    @staticmethod
    def _train_ensemble_models(X, y) -> Dict[str, Any]:
        """Antrenează un ensemble de modele"""
        models = {}

        # Definiție modele și parametri
        model_configs = {
            'xgb': {
                'model': XGBRegressor(random_state=42, n_jobs=-1),
                'params': {
                    'n_estimators': [100, 500, 1000],
                    'max_depth': [3, 6, 9],
                    'learning_rate': [0.01, 0.05, 0.1],
                    'subsample': [0.8, 0.9, 1.0]
                }
            },
            'rf': {
                'model': RandomForestRegressor(random_state=42, n_jobs=-1),
                'params': {
                    'n_estimators': [100, 200, 500],
                    'max_depth': [None, 10, 20, 30],
                    'min_samples_split': [2, 5, 10]
                }
            },
            'gbr': {
                'model': GradientBoostingRegressor(random_state=42),
                'params': {
                    'n_estimators': [100, 200, 500],
                    'learning_rate': [0.01, 0.05, 0.1],
                    'max_depth': [3, 5, 7]
                }
            }
        }

        # Optimizare hiperparametri
        for name, config in model_configs.items():
            logger.info(f"Training {name}...")

            search = RandomizedSearchCV(
                config['model'],
                config['params'],
                n_iter=10,
                cv=3,
                scoring='neg_mean_absolute_error',
                n_jobs=-1,
                random_state=42
            )

            search.fit(X, y)
            models[name] = search.best_estimator_

            # Evaluare
            scores = cross_val_score(models[name], X, y, cv=3, scoring='neg_mean_absolute_error')
            logger.info(f"{name} MAE: {-scores.mean():.2f} (±{scores.std():.2f})")

        return models

    @staticmethod
    def _make_ensemble_predictions(df, models, X, feature_columns) -> pd.DataFrame:
        """Face predicții ensemble"""
        predictions = []

        for name, model in models.items():
            pred = model.predict(X)
            predictions.append(pred)

        # Media predicțiilor
        ensemble_pred = np.mean(predictions, axis=0)
        ensemble_pred = np.expm1(ensemble_pred)  # Reverse log transform

        df['enhanced_pred_price'] = ensemble_pred
        df['enhanced_profit_score'] = (
                (df['enhanced_pred_price'] - df['price_eur']) /
                df['enhanced_pred_price'] * 100
        )

        return df

    @staticmethod
    def _load_cached_model() -> Optional[Dict]:
        """Încarcă model din cache"""
        try:
            import os
            import glob

            model_files = glob.glob(f"{Config.MODEL_CACHE_PATH}model_*.pkl")
            if not model_files:
                return None

            latest_file = max(model_files, key=os.path.getctime)

            with open(latest_file, 'rb') as f:
                model_data = pickle.load(f)

            # Verifică dacă modelul este expirat
            if (datetime.now() - model_data['timestamp']).days > Config.MODEL_CACHE_DAYS:
                return None

            return model_data

        except Exception as e:
            logger.warning(f"Model cache loading failed: {e}")
            return None

    @staticmethod
    def _save_model(models: Dict, feature_columns: List[str]):
        """Salvează model în cache"""
        try:
            import os
            os.makedirs(Config.MODEL_CACHE_PATH, exist_ok=True)

            model_data = {
                'models': models,
                'features': feature_columns,
                'timestamp': datetime.now()
            }

            filename = f"{Config.MODEL_CACHE_PATH}model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"

            with open(filename, 'wb') as f:
                pickle.dump(model_data, f)

            logger.info(f"Model saved to {filename}")

        except Exception as e:
            logger.error(f"Model saving failed: {e}")

    @staticmethod
    def invalidate_model_cache_for(brand: str, model: str):
        """Șterge fișierele cache pentru un anumit model"""
        import os, glob
        files = glob.glob(f"{Config.MODEL_CACHE_PATH}model_*.pkl")
        for f in files:
            try:
                data = pickle.load(open(f, 'rb'))
                if 'features' in data:
                    if brand in data['features'] or model in data['features']:
                        os.remove(f)
            except:
                pass

# ==============================
# CALCUL PROFITABILITATE AVANSAT
# ==============================
class AdvancedProfitabilityCalculator:
    """Sistem avansat de calcul al profitabilității"""

    @staticmethod
    def calculate_advanced_profitability(df, market_trends):
        logger.info("Calculating profitability per listing")

        df['market_price'] = np.nan
        df['profit_margin'] = np.nan
        df['profit_label'] = "Unknown"

        for idx, row in df.iterrows():
            try:
                # Folosim market_trends simulate
                mt = market_trends.get(idx, {"avg_price": None})
                market_price = mt["avg_price"]

                if market_price is None:
                    continue

                df.at[idx, 'market_price'] = market_price

                # Diferență între valoarea estimată de piață și prețul real
                profit = market_price - row['price_eur']
                df.at[idx, 'profit_margin'] = profit

                # Clasificăm
                if profit > 1000:
                    label = "Bargain 🚀"
                elif profit < -1000:
                    label = "Overpriced ❌"
                else:
                    label = "Fair ✅"

                df.at[idx, 'profit_label'] = label

            except Exception as e:
                logger.warning(f"Profitability calculation failed for idx={idx}: {e}")

        return df

    @staticmethod
    def _apply_adjustment_factors(df: pd.DataFrame, market_trends: Dict) -> pd.DataFrame:
        """Aplică factori de ajustare avansați"""
        df = df.copy()
        df['adjustment_factor'] = 1.0

        # Calitate date
        df['adjustment_factor'] *= AdvancedProfitabilityCalculator._data_quality_adjustment(df)

        # Sentiment
        df['adjustment_factor'] *= AdvancedProfitabilityCalculator._sentiment_adjustment(df)

        # Competiție
        df['adjustment_factor'] *= AdvancedProfitabilityCalculator._competition_adjustment(df, market_trends)

        # Trend piață
        df['adjustment_factor'] *= AdvancedProfitabilityCalculator._market_trend_adjustment(df, market_trends)

        return df

    @staticmethod
    def _data_quality_adjustment(df: pd.DataFrame) -> pd.Series:
        """Ajustare bazată pe calitatea datelor"""
        return np.where(
            df['data_quality_score'] > 80, 1.1,
            np.where(df['data_quality_score'] > 60, 1.0, 0.9)
        )

    @staticmethod
    def _sentiment_adjustment(df: pd.DataFrame) -> pd.Series:
        """Ajustare bazată pe sentiment"""
        return 1 + (df['sentiment_polarity'] * 0.2)  # +20% pentru sentiment pozitiv

    @staticmethod
    def _competition_adjustment(df: pd.DataFrame, market_trends: Dict) -> pd.Series:
        """Ajustare bazată pe competiție"""
        adjustment = pd.Series(1.0, index=df.index)

        for idx, row in df.iterrows():
            comp_data = market_trends['competition_analysis'].get(idx, {})
            similar_count = comp_data.get('similar_listings_count', 0)

            if similar_count > 10:  # Multă competiție
                adjustment.loc[idx] = 0.9
            elif similar_count < 3:  # Puțină competiție
                adjustment.loc[idx] = 1.1

        return adjustment

    @staticmethod
    def _market_trend_adjustment(df: pd.DataFrame, market_trends: Dict) -> pd.Series:
        """Ajustare bazată pe trendurile pieței"""
        # Implementare simplă - în practică s-ar folosi date reale
        return pd.Series(1.0, index=df.index)


# ==============================
# DASHBOARD AVANSAT
# ==============================
class AdvancedDashboard:
    """Dashboard avansat cu multiple funcționalități"""

    @staticmethod
    def create_dashboard(df: pd.DataFrame, market_trends: Dict):
        """Creează dashboard avansat"""
        app = Dash(__name__)

        app.layout = html.Div([
            # Header
            html.H1("🚗 Car Analyzer Pro - Advanced Analytics", style={
                'textAlign': 'center',
                'color': '#2c3e50',
                'marginBottom': '30px'
            }),

            # Filtre avansate
            html.Div([
                html.Div([
                    html.Label("🔍 Marca:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(
                        id='brand-filter',
                        options=[{'label': b, 'value': b} for b in sorted(df['brand'].dropna().unique())],
                        multi=True,
                        placeholder='Selectează mărci...'
                    )
                ], style={'width': '18%', 'display': 'inline-block', 'marginRight': '2%'}),

                html.Div([
                    html.Label("📅 An:", style={'fontWeight': 'bold'}),
                    dcc.RangeSlider(
                        id='year-slider',
                        min=int(df['year_extracted'].min()),
                        max=int(df['year_extracted'].max()),
                        value=[2010, 2023],
                        marks={year: str(year) for year in range(
                            int(df['year_extracted'].min()),
                            int(df['year_extracted'].max()) + 1,
                            5
                        )}
                    )
                ], style={'width': '30%', 'display': 'inline-block', 'marginRight': '2%'}),

                html.Div([
                    html.Label("💰 Profit Min (%):", style={'fontWeight': 'bold'}),
                    dcc.Slider(
                        id='profit-slider',
                        min=0,
                        max=50,
                        value=10,
                        marks={i: f'{i}%' for i in range(0, 51, 10)}
                    )
                ], style={'width': '20%', 'display': 'inline-block', 'marginRight': '2%'}),

                html.Div([
                    html.Label("⭐ Calitate Date:", style={'fontWeight': 'bold'}),
                    dcc.Slider(
                        id='quality-slider',
                        min=0,
                        max=100,
                        value=60,
                        marks={i: f'{i}%' for i in range(0, 101, 20)}
                    )
                ], style={'width': '20%', 'display': 'inline-block'})
            ], style={'marginBottom': '30px', 'padding': '20px', 'backgroundColor': '#f8f9fa'}),

            # Main content
            html.Div([
                # Left column - Charts
                html.Div([
                    dcc.Graph(id='price-comparison-chart'),
                    dcc.Graph(id='profit-distribution-chart'),
                    dcc.Graph(id='market-trends-chart')
                ], style={'width': '65%', 'display': 'inline-block'}),

                # Right column - Stats and Table
                html.Div([
                    html.Div([
                        html.H3("📊 Statistics", style={'color': '#2c3e50'}),
                        html.Div(id='summary-stats')
                    ], style={'marginBottom': '20px'}),

                    html.Div([
                        html.H3("🏆 Top Opportunities", style={'color': '#2c3e50'}),
                        dash_table.DataTable(
                            id='top-opportunities-table',
                            columns=[
                                {'name': 'Brand', 'id': 'brand'},
                                {'name': 'Model', 'id': 'model'},
                                {'name': 'Year', 'id': 'year_extracted'},
                                {'name': 'Price', 'id': 'price_eur', 'type': 'numeric', 'format': {'specifier': '.2f'}},
                                {'name': 'Est. Price', 'id': 'enhanced_pred_price', 'type': 'numeric',
                                 'format': {'specifier': '.2f'}},
                                {'name': 'Profit %', 'id': 'profit_margin', 'type': 'numeric',
                                 'format': {'specifier': '.2f'}},
                                {'name': 'Quality', 'id': 'data_quality_score', 'type': 'numeric',
                                 'format': {'specifier': '.2f'}}
                            ],
                            style_cell={'textAlign': 'center'},
                            style_header={'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold'},
                            page_size=10,
                            sort_action='native',
                            filter_action='native'
                        )
                    ])
                ], style={'width': '33%', 'display': 'inline-block', 'float': 'right', 'paddingLeft': '20px'})
            ]),

            # Hidden storage
            dcc.Store(id='filtered-data'),
            dcc.Store(id='market-trends-data')
        ])

        # Callbacks
        @app.callback(
            [Output('filtered-data', 'data'),
             Output('market-trends-data', 'data')],
            [Input('brand-filter', 'value'),
             Input('year-slider', 'value'),
             Input('profit-slider', 'value'),
             Input('quality-slider', 'value')]
        )
        def update_filtered_data(selected_brands, year_range, min_profit, min_quality):
            try:
                filtered_df = df.copy()

                # Aplică filtre
                if selected_brands:
                    filtered_df = filtered_df[filtered_df['brand'].isin(selected_brands)]

                filtered_df = filtered_df[
                    (filtered_df['year_extracted'] >= year_range[0]) &
                    (filtered_df['year_extracted'] <= year_range[1]) &
                    (filtered_df['profit_margin'] >= min_profit) &
                    (filtered_df['data_quality_score'] >= min_quality)
                    ]

                # Log pentru debug
                logging.info(f"Filtered DF rows: {len(filtered_df)}")

                # Transform tuple keys în string pentru market_trends
                market_trends_str_keys = {str(k): v for k, v in market_trends.items()}
                logging.info(
                    f"Market trends JSON keys: {list(market_trends_str_keys.keys())[:5]}")  # doar primele 5 chei

                # Return JSON pentru Dash
                df_json = filtered_df.to_json(date_format='iso', orient='split')
                market_json = json.dumps(market_trends_str_keys)

                return df_json, market_json

            except Exception as e:
                logging.error(f"Exception in update_filtered_data: {e}")
                # Return JSON gol în caz de eroare
                return json.dumps({}), json.dumps({})

        # Callback pentru statistici
        @app.callback(
            Output('summary-stats', 'children'),
            [Input('filtered-data', 'data')]
        )
        def update_summary_stats(filtered_data):
            if filtered_data is None:
                return html.Div("No data available")

            df_filtered = pd.read_json(filtered_data, orient='split')

            if df_filtered.empty:
                return html.Div("No data available after filtering")

            total_listings = len(df_filtered)
            avg_price = df_filtered['price_eur'].mean()
            avg_pred_price = df_filtered['enhanced_pred_price'].mean()
            avg_profit = df_filtered['profit_margin'].mean()
            avg_quality = df_filtered['data_quality_score'].mean()

            return html.Div([
                html.P(f"Total Listings: {total_listings}"),
                html.P(f"Average Price: €{avg_price:.2f}"),
                html.P(f"Average Estimated Price: €{avg_pred_price:.2f}"),
                html.P(f"Average Profit %: {avg_profit:.2f}%"),
                html.P(f"Average Data Quality: {avg_quality:.2f}%")
            ])

            # Callback pentru grafice

        @app.callback(
            [Output('price-comparison-chart', 'figure'),
             Output('profit-distribution-chart', 'figure'),
             Output('market-trends-chart', 'figure')],
            [Input('filtered-data', 'data')]
        )
        def update_charts(filtered_data):
            if filtered_data is None:
                return go.Figure(), go.Figure(), go.Figure()

            df_filtered = pd.read_json(filtered_data, orient='split')
            if df_filtered.empty:
                return go.Figure(), go.Figure(), go.Figure()

            # Chart 1: Price comparison by brand
            fig_price = px.box(df_filtered, x='brand', y='price_eur', color='brand',
                               title="📦 Price Distribution by Brand")
            fig_price.update_layout(showlegend=False)

            # Chart 2: Profit distribution
            fig_profit = px.histogram(df_filtered, x='profit_margin', nbins=30,
                                      title="💰 Profit % Distribution")
            fig_profit.update_layout(xaxis_title="Profit %", yaxis_title="Count")

            # Chart 3: Market trends over time (if available)
            if 'scrape_date' in df_filtered.columns:
                df_filtered['scrape_date'] = pd.to_datetime(df_filtered['scrape_date'])
                trends_df = df_filtered.groupby('scrape_date').agg({'enhanced_pred_price': 'mean'}).reset_index()
                fig_trends = px.line(trends_df, x='scrape_date', y='enhanced_pred_price',
                                     title="📈 Average Estimated Price Over Time")
            else:
                fig_trends = go.Figure()

            return fig_price, fig_profit, fig_trends

        # Run app
        print(df.columns)
        print(df.head(3))
        app.run(debug=False, port=8050)

