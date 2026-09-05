# ==============================
# CAR ANALYZER 4.3 – ÎMBUNĂTĂȚIRI AVANSATE
# ==============================

import pandas as pd
import re, unidecode, numpy as np
import pickle
import time
import logging
from datetime import datetime, timedelta
from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor
from dash import Dash, dcc, html, dash_table, Input, Output, State, callback_context
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
import json

# ==============================
# CONFIGURARE
# ==============================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configurare email pentru alertă (opțional)
EMAIL_CONFIG = {
    'enabled': False,  # Set to True to enable email alerts
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'email': 'your_email@gmail.com',
    'password': 'your_password',
    'recipient': 'recipient@example.com'
}

# Constante
MARCAS = ["fiat", "opel", "peugeot", "ford", "skoda", "dacia", "renault", "bmw", "audi",
          "mercedes", "volkswagen", "seat", "hyundai", "kia", "toyota", "mazda", "nissan"]

DOTARI = ["camera spate", "senzori parcare", "incalzire scaune", "panou solar",
          "oglinzi electrice", "geamuri electrice", "aer conditionat", "cruise control",
          "pilot automat", "scaune piele", "volan incalzit", "trapa", "xenon", "bi-xenon"]

MOTORIZARE = ["gpl", "metan", "benzina+gpl"]


# ==============================
# FUNCȚII UTILITARE ÎMBUNĂTĂȚITE
# ==============================
def setup_logging():
    """Configurare avansată pentru logging"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # Handler pentru fișier
    file_handler = logging.FileHandler(f'car_analyzer_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    file_handler.setLevel(logging.INFO)

    # Handler pentru consolă
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formatare
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Adăugare handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


def load_or_train_model(df, model_path='trained_models/trained_model.pkl', force_retrain=False):
    """
    Încarcă un model antrenat sau antrenează unul nou dacă nu există sau dacă forțăm reantrenarea
    """
    import os
    os.makedirs('../trained_models', exist_ok=True)

    if not force_retrain and os.path.exists(model_path):
        try:
            with open(model_path, 'rb') as f:
                model_data = pickle.load(f)

            # Verifică dacă modelul este învechit (mai vechi de 7 zile)
            if 'timestamp' in model_data and (datetime.now() - model_data['timestamp']).days < 7:
                logger.info("Încărcare model antrenat din cache")
                return model_data['model'], model_data['feature_columns']
        except Exception as e:
            logger.warning(f"Eroare la încărcarea modelului: {e}. Se va reantrena.")

    # Antrenare model nou
    logger.info("Antrenare model nou...")
    df, model, feature_columns = train_advanced_model(df)

    # Salvarea modelului
    model_data = {
        'model': model,
        'feature_columns': feature_columns,
        'timestamp': datetime.now()
    }

    try:
        with open(model_path, 'wb') as f:
            pickle.dump(model_data, f)
        logger.info("Model salvat cu succes")
    except Exception as e:
        logger.error(f"Eroare la salvarea modelului: {e}")

    return model, feature_columns


def send_email_alert(subject, message):
    """Trimite alertă prin email dacă este configurat"""
    if not EMAIL_CONFIG['enabled']:
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['email']
        msg['To'] = EMAIL_CONFIG['recipient']
        msg['Subject'] = subject

        msg.attach(MIMEText(message, 'plain'))

        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['email'], EMAIL_CONFIG['password'])
        server.send_message(msg)
        server.quit()

        logger.info("Email alert trimis cu succes")
    except Exception as e:
        logger.error(f"Eroare la trimiterea emailului: {e}")


def get_market_trends(brand, model):
    """
    Obține trendurile de piață pentru o mașină specifică de pe site-uri externe
    (implementare simplificată - poate fi extinsă)
    """
    try:
        # Exemplu de preluare date de pe un site extern (implementare simplă)
        # În practică, s-ar folosi API-uri oficiale sau scraping responsabil
        time.sleep(0.5)  # Respectful delay

        # Simulare date de piață (în loc de scraping real)
        market_data = {
            'average_price': None,
            'trend': 'stable',
            'demand_level': 'medium'
        }

        # Aici s-ar face cererea HTTP reală și parsarea răspunsului
        # response = requests.get(f"https://example.com/market-data/{brand}/{model}", timeout=10)
        # if response.status_code == 200:
        #     # Parse response and extract data
        #     pass

        return market_data
    except Exception as e:
        logger.error(f"Eroare la obținerea trendurilor de piață: {e}")
        return None


# ==============================
# PREPROCESARE ÎMBUNĂTĂȚITĂ
# ==============================
def clean_text(text):
    """Funcție îmbunătățită pentru curățarea textului"""
    if not isinstance(text, str):
        return ""

    try:
        text = unidecode.unidecode(text.lower())
        text = re.sub(r"[^a-z0-9ăâîșțĂÂÎȘȚ ]", " ", text)  # Suport pentru diacritice
        text = re.sub(r"\s+", " ", text).strip()

        stopwords = ["vand", "se", "vinde", "oferta", "cumpar", "vanzare", "autoutilitara",
                     "occasion", "second", "second hand", "sh", "rabla", "trade"]
        for sw in stopwords:
            text = re.sub(rf"\b{sw}\b", "", text)

        return text.strip()
    except Exception as e:
        logger.error(f"Eroare la curățarea textului: {e}")
        return ""


def extract_brand_model(title):
    """Extrage marca și modelul cu suport îmbunătățit"""
    try:
        title = clean_text(title)
        brand, model = None, None

        for marca in MARCAS:
            if marca in title:
                brand = marca
                # Încearcă să găsească modelul după marcă
                parts = title.split()
                if brand in parts:
                    idx = parts.index(brand)
                    if idx + 1 < len(parts):
                        model = parts[idx + 1]
                        # Verifică dacă modelul este prea scurt sau invalid
                        if len(model) < 2 or model in ['si', 'cu', 'de', 'la']:
                            model = None
                break

        return brand, model
    except Exception as e:
        logger.error(f"Eroare la extragerea brand/model: {e}")
        return None, None


def extract_year(title):
    """Extrage anul cu gestionare îmbunătățită a erorilor"""
    try:
        match = re.search(r"\b(19[8-9]\d|20[0-2]\d)\b", title)
        return int(match.group(0)) if match else None
    except:
        return None


def normalize_price(price, currency):
    """Normalizează prețul cu gestionare îmbunătățită a erorilor"""
    try:
        if pd.isna(price):
            return None

        if isinstance(price, str):
            # Elimină spații și caractere speciale
            price = re.sub(r'[^\d.,]', '', price)
            # Înlocuiește virgula cu punct pentru conversie numerică
            price = price.replace(',', '.')

            # Verifică dacă are multiple puncte (e.g., 1.000.00)
            if price.count('.') > 1:
                # Păstrează doar ultimul punct ca separator zecimal
                parts = price.split('.')
                integer_part = ''.join(parts[:-1])
                decimal_part = parts[-1]
                price = f"{integer_part}.{decimal_part}"

        price = float(price)

        if isinstance(currency, str):
            currency = currency.lower()
            if "eur" in currency or "€" in currency:
                return price
            elif "ron" in currency or "lei" in currency:
                return price / 4.95  # Curs valutar mai precis
            elif "usd" in currency or "$" in currency:
                return price * 0.92  # Curs valutar mai precis

        return price
    except Exception as e:
        logger.error(f"Eroare la normalizarea prețului {price}: {e}")
        return None


def extract_mileage(mileage_val, description=""):
    """Extrage kilometrajul cu gestionare îmbunătățită a erorilor"""
    try:
        if isinstance(mileage_val, (int, float)):
            return mileage_val

        if isinstance(mileage_val, str):
            # Încearcă să extragă numărul direct
            digits = re.sub(r"[^\d]", "", mileage_val)
            if digits:
                return int(digits)

        if isinstance(description, str):
            # Caută în descriere pattern-uri comune pentru kilometraj
            patterns = [
                r"(\d{1,3}(?:\s?\d{3})+)\s*km",  # Formate cu spații: 100 000 km
                r"(\d+)\s*km",  # Format simplu: 100000km
                r"km[:\s]*(\d+(?:\s?\d{3})*)",  # km: 100000
            ]

            for pattern in patterns:
                match = re.search(pattern, description.lower())
                if match:
                    value = match.group(1).replace(" ", "")
                    if value.isdigit():
                        return int(value)

        return None
    except Exception as e:
        logger.error(f"Eroare la extragerea kilometrajului: {e}")
        return None


# ==============================
# CARACTERISTICI DETALIATE ÎMBUNĂTĂȚITE
# ==============================
def extract_detailed_features(text):
    """Extrage caracteristici detaliate din text cu mai multe pattern-uri"""
    try:
        text = str(text).lower()
        features = {}

        # Capacitate motor
        engine_patterns = [
            r'(\d{3,4})\s*cm3',
            r'(\d{1,2}\.\d)\s*l',
            r'(\d{3,4})\s*cc'
        ]

        for pattern in engine_patterns:
            match = re.search(pattern, text)
            if match:
                features['engine_capacity'] = int(match.group(1))
                break
        else:
            features['engine_capacity'] = None

        # Putere motor
        power_patterns = [
            r'(\d{2,3})\s*(cp|hp|cai|putere)',
            r'putere\D*(\d{2,3})',
            r'(\d{2,3})\s*cai'
        ]

        for pattern in power_patterns:
            match = re.search(pattern, text)
            if match:
                features['power'] = int(match.group(1))
                break
        else:
            features['power'] = None

        # Alte caracteristici
        features['de_la_proprietar'] = 1 if any(w in text for w in ['proprietar', 'particular', 'vanator']) else 0
        features['cu_factura'] = 1 if any(w in text for w in ['factura', 'factura', 'facturi']) else 0
        features['cu_garantie'] = 1 if any(w in text for w in ['garantie', 'garanție']) else 0
        features['istoric_complet'] = 1 if any(
            w in text for w in ['istoric complet', 'service autorizat', 'istoric service']) else 0
        features['fara_accidente'] = 1 if any(
            w in text for w in ['fara accidente', 'neaccidentata', 'fară accident', 'nevandalizata']) else 0

        # Tip caroserie
        caroserie_keywords = {
            'berlina': ['berlina', 'sedan'],
            'break': ['break', 'combi', 'station'],
            'hatchback': ['hatchback', 'hatch'],
            'suv': ['suv', 'crossover', '4x4', 'patrupepatru'],
            'coupe': ['coupe', 'cupé'],
            'cabrio': ['cabrio', 'convertible', 'deschis']
        }

        features['caroserie'] = 'altul'
        for car_type, keywords in caroserie_keywords.items():
            if any(kw in text for kw in keywords):
                features['caroserie'] = car_type
                break

        # Norma de poluare
        for euro_norm in ['euro 1', 'euro 2', 'euro 3', 'euro 4', 'euro 5', 'euro 6']:
            if euro_norm in text:
                features['euro_norm'] = euro_norm
                break
        else:
            features['euro_norm'] = None

        return features
    except Exception as e:
        logger.error(f"Eroare la extragerea caracteristicilor detaliate: {e}")
        return {}


# ==============================
# DETECTARE ANUNȚURI SUSPECTE ÎMBUNĂTĂȚITĂ
# ==============================
def detect_fraudulent_listings(df):
    """Detectează anunțuri suspecte cu algoritmi mai avansați"""
    try:
        df['suspect_price'] = 0
        df['suspect_mileage'] = 0
        df['suspect_score'] = 0

        # Analiză pe branduri
        for brand in df['brand'].dropna().unique():
            brand_data = df[df['brand'] == brand]
            if len(brand_data) > 5:
                # Detectare prețuri anormale
                Q1 = brand_data['price_eur'].quantile(0.25)
                Q3 = brand_data['price_eur'].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR

                df.loc[(df['brand'] == brand) & (df['price_eur'] < lower_bound), 'suspect_price'] = 1
                df.loc[(df['brand'] == brand) & (df['price_eur'] > upper_bound), 'suspect_price'] = 1

                # Scor de suspectție bazat pe abaterea de la medie
                brand_mean = brand_data['price_eur'].mean()
                brand_std = brand_data['price_eur'].std()

                if brand_std > 0:
                    z_score = abs((df['price_eur'] - brand_mean) / brand_std)
                    df.loc[df['brand'] == brand, 'price_z_score'] = z_score
                    df.loc[(df['brand'] == brand) & (z_score > 3), 'suspect_score'] += 1

        # Detectare kilometraj inconsistent
        df['age'] = 2025 - df['year_extracted']
        df.loc[df['age'] > 0, 'km_per_year'] = df['mileage'] / df['age']

        df.loc[(df['age'] > 0) & (df['km_per_year'] < 1000), 'suspect_mileage'] = 1
        df.loc[(df['age'] > 0) & (df['km_per_year'] > 30000), 'suspect_mileage'] = 1
        df.loc[df['suspect_mileage'] == 1, 'suspect_score'] += 1

        # Verifică dacă anul este realist pentru kilometraj
        current_year = datetime.now().year
        df.loc[(df['year_extracted'] > current_year) | (df['year_extracted'] < 1980), 'suspect_score'] += 2

        # Verifică prețuri zero sau negative
        df.loc[df['price_eur'] <= 0, 'suspect_score'] += 3

        return df
    except Exception as e:
        logger.error(f"Eroare la detectarea anunțurilor suspecte: {e}")
        return df


# ==============================
# CALCUL PROFITABILITATE ÎMBUNĂTĂȚIT
# ==============================
def calculate_profitability_score(row):
    """Calculează un scor de profitabilitate mai complex și precis"""
    try:
        base_score = row.get('enhanced_profit_score', 0)

        # Ajustări bazate pe caracteristici
        adjustments = {
            'de_la_proprietar': 1.2,  # Bonus pentru vânzător particular
            'istoric_complet': 1.15,  # Bonus pentru istoric complet
            'fara_accidente': 1.1,  # Bonus pentru fără accidente
            'cu_factura': 1.05,  # Bonus pentru factură
            'cu_garantie': 1.07,  # Bonus pentru garanție
            'suspect_price': 0.5,  # Penalizare pentru preț suspect
            'suspect_mileage': 0.7  # Penalizare pentru kilometraj suspect
        }

        for factor, multiplier in adjustments.items():
            if row.get(factor, 0) == 1:
                base_score *= multiplier

        # Ajustări bazate pe vârstă și kilometraj
        if row.get('age', 0) > 0:
            if row['age'] < 5:
                base_score *= 1.1  # Mașini mai noi sunt mai fiabile
            elif row['age'] > 15:
                base_score *= 0.8  # Mașini foarte vechi sunt mai riscante

        # Ajustare bazată pe raportul km/an
        if row.get('km_per_year', 0) > 0:
            if 5000 <= row['km_per_year'] <= 20000:
                base_score *= 1.05  # Utilizare normală
            elif row['km_per_year'] > 25000:
                base_score *= 0.9  # Utilizare intensă

        return max(0, base_score)  # Asigură că scorul nu este negativ
    except Exception as e:
        logger.error(f"Eroare la calculul profitabilității: {e}")
        return 0


# ==============================
# MODEL AVANSAT CU OPTIMIZARE HIPERPARAMETRI
# ==============================
def train_advanced_model(df):
    """Antrenează un model avansat cu optimizare de hiperparametri"""
    try:
        # Selectare și preparare feature-uri
        feature_cols = [
                           "year_extracted", "mileage", "engine_capacity", "power", "age"
                       ] + [col for col in df.columns if col.startswith(("dotare_", "motorizare_", "cutie_"))]

        # Elimină coloanele cu prea multe valori lipsă
        feature_cols = [col for col in feature_cols if col in df.columns and df[col].notna().sum() > len(df) * 0.5]

        # Completează valorile lipsă
        X = df[feature_cols].copy()
        for col in X.columns:
            if X[col].dtype in ['int64', 'float64']:
                X[col].fillna(X[col].median(), inplace=True)
            else:
                X[col].fillna(X[col].mode()[0] if not X[col].mode().empty else 0, inplace=True)

        # Log-transform pentru variabila țintă (pentru a reduce skewness)
        y = np.log1p(df["price_eur"])

        # Împarte datele
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=True)

        # Definire modele și parametri pentru optimizare
        models = {
            'xgb': {
                'model': XGBRegressor(random_state=42),
                'params': {
                    'n_estimators': [100, 500, 1000],
                    'max_depth': [3, 6, 9],
                    'learning_rate': [0.01, 0.05, 0.1],
                    'subsample': [0.8, 0.9, 1.0]
                }
            },
            'rf': {
                'model': RandomForestRegressor(random_state=42),
                'params': {
                    'n_estimators': [100, 200, 500],
                    'max_depth': [None, 10, 20],
                    'min_samples_split': [2, 5, 10]
                }
            }
        }

        best_models = {}
        best_score = float('-inf')
        best_model_name = None

        # Optimizare hiperparametri pentru fiecare model
        for name, model_info in models.items():
            logger.info(f"Optimizare hiperparametri pentru {name.upper()}...")

            search = RandomizedSearchCV(
                model_info['model'],
                model_info['params'],
                n_iter=10,  # Număr de iterații pentru search
                cv=3,
                scoring='neg_mean_absolute_error',
                n_jobs=-1,
                random_state=42
            )

            search.fit(X_train, y_train)
            best_models[name] = search.best_estimator_

            # Evaluare
            y_pred = search.best_estimator_.predict(X_test)
            mae = mean_absolute_error(np.expm1(y_test), np.expm1(y_pred))
            r2 = r2_score(np.expm1(y_test), np.expm1(y_pred))

            logger.info(f"{name.upper()} - Best params: {search.best_params_}")
            logger.info(f"{name.upper()} - MAE: {mae:.2f}, R²: {r2:.4f}")

            # Selectează cel mai bun model
            if search.best_score_ > best_score:
                best_score = search.best_score_
                best_model_name = name

        # Folosește cel mai bun model pentru predicții
        best_model = best_models[best_model_name]
        logger.info(f"Cel mai bun model: {best_model_name.upper()}")

        # Predicții ensemble (media dintre cele mai bune modele)
        predictions = []
        for name, model in best_models.items():
            pred = model.predict(X)
            predictions.append(pred)

        ensemble_pred_log = np.mean(predictions, axis=0)
        ensemble_pred = np.expm1(ensemble_pred_log)

        # Asigură că predicțiile sunt rezonabile
        ensemble_pred = np.clip(ensemble_pred, a_min=0, a_max=df["price_eur"].max() * 2)

        df["enhanced_pred_price"] = ensemble_pred
        df["enhanced_profit_score"] = ((df["enhanced_pred_price"] - df["price_eur"]) / df["enhanced_pred_price"]) * 100

        # Elimină valorile extreme (outliers) din profit score
        Q1 = df["enhanced_profit_score"].quantile(0.05)
        Q3 = df["enhanced_profit_score"].quantile(0.95)
        df["enhanced_profit_score"] = np.clip(df["enhanced_profit_score"], Q1, Q3)

        return df, best_models, feature_cols

    except Exception as e:
        logger.error(f"Eroare la antrenarea modelului: {e}")
        raise


# ==============================
# EXPORT ÎMBUNĂTĂȚIT
# ==============================
def export_top_excel(df, path="top_masini.xlsx", n=20):
    """Exportă topul mașinilor cu mai multe detalii"""
    try:
        top = df[df['suspect_score'] < 3].sort_values("profitability_score", ascending=False).head(n)

        # Coloane de export
        cols = [
            "brand", "model", "year_extracted", "mileage", "price_eur",
            "enhanced_pred_price", "profitability_score", "url", "age",
            "km_per_year", "engine_capacity", "power", "caroserie"
        ]

        # Verifică care coloane există în DataFrame
        cols = [col for col in cols if col in df.columns]

        top[cols].to_excel(path, index=False)
        logger.info(f"📊 Exportat Excel: {path} cu {len(top)} mașini")

        # Trimite alertă dacă există oportunități excepționale
        if len(top) > 0 and top.iloc[0]['profitability_score'] > 30:
            best_car = top.iloc[0]
            message = f"Oportunitate excepțională: {best_car['brand']} {best_car['model']} {best_car['year_extracted']}\n"
            message += f"Preț: {best_car['price_eur']} EUR, Preț estimat: {best_car['enhanced_pred_price']:.2f} EUR\n"
            message += f"Profitabilitate: {best_car['profitability_score']:.2f}%\n"
            message += f"Link: {best_car['url']}"

            send_email_alert("🚨 Oportunitate excepțională de investiție auto", message)

    except Exception as e:
        logger.error(f"Eroare la exportul Excel: {e}")


def export_top_pdf(df, path="top_masini.pdf", n=20):
    """Exportă un raport PDF detaliat"""
    try:
        top = df[df['suspect_score'] < 3].sort_values("profitability_score", ascending=False).head(n)

        # Coloane pentru raport
        cols = ["brand", "model", "year_extracted", "mileage", "price_eur",
                "enhanced_pred_price", "profitability_score"]

        # Verifică care coloane există
        cols = [col for col in cols if col in df.columns]

        # Pregătește datele pentru tabel
        data = [["Brand", "Model", "An", "Km", "Preț (EUR)", "Preț Estimat (EUR)", "Profitabilitate (%)"]]

        for _, row in top.iterrows():
            data.append([
                row.get("brand", ""),
                row.get("model", ""),
                str(row.get("year_extracted", "")),
                f"{row.get('mileage', 0):,}".replace(",", "."),
                f"{row.get('price_eur', 0):.2f}",
                f"{row.get('enhanced_pred_price', 0):.2f}",
                f"{row.get('profitability_score', 0):.2f}%"
            ])

        # Crează document PDF
        doc = SimpleDocTemplate(path, pagesize=landscape(A4))
        styles = getSampleStyleSheet()

        elements = [
            Paragraph("Raport Top Mașini Profitabile", styles['Heading1']),
            Spacer(1, 12),
            Paragraph(f"Generat la: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']),
            Spacer(1, 12)
        ]

        # Crează tabel
        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
        ]))

        elements.append(table)
        doc.build(elements)
        logger.info(f"📄 Exportat PDF: {path}")

    except Exception as e:
        logger.error(f"Eroare la exportul PDF: {e}")


# ==============================
# DASHBOARD AVANSAT
# ==============================
def run_enhanced_dashboard(df):
    """Lansează un dashboard avansat cu mai multe funcționalități"""
    try:
        app = Dash(__name__)

        # Filtre avansate
        brands = sorted(df["brand"].dropna().unique())
        years = sorted(df["year_extracted"].dropna().unique())
        caroserie_types = sorted(df["caroserie"].dropna().unique()) if "caroserie" in df.columns else []

        app.layout = html.Div([
            html.H1("Analiză Avansată Profitabilitate Mașini", style={"textAlign": "center"}),

            # Filtre
            html.Div([
                html.Div([
                    html.Label("Mărci:"),
                    dcc.Dropdown(
                        id="brand_filter",
                        options=[{"label": b, "value": b} for b in brands],
                        multi=True,
                        placeholder="Selectează mărci"
                    )
                ], style={"width": "23%", "display": "inline-block", "marginRight": "2%"}),

                html.Div([
                    html.Label("An minim:"),
                    dcc.Dropdown(
                        id="year_min",
                        options=[{"label": str(y), "value": y} for y in years],
                        placeholder="Selectează an minim"
                    )
                ], style={"width": "15%", "display": "inline-block", "marginRight": "2%"}),

                html.Div([
                    html.Label("Profit minim (%):"),
                    dcc.Input(
                        id="profit_min",
                        type="number",
                        value=10,
                        min=0,
                        max=100,
                        style={"width": "100%"}
                    )
                ], style={"width": "15%", "display": "inline-block", "marginRight": "2%"}),

                html.Div([
                    html.Label("Tip caroserie:"),
                    dcc.Dropdown(
                        id="caroserie_filter",
                        options=[{"label": t, "value": t} for t in caroserie_types],
                        multi=True,
                        placeholder="Selectează tip caroserie"
                    )
                ], style={"width": "20%", "display": "inline-block", "marginRight": "2%"}),

                html.Div([
                    html.Label(" "),
                    html.Button(
                        "Aplică Filtre",
                        id="apply_filters",
                        n_clicks=0,
                        style={"width": "100%", "marginTop": "5px"}
                    )
                ], style={"width": "20%", "display": "inline-block"}),
            ], style={"marginBottom": "20px"}),

            # Grafice și tabele
            dcc.Graph(id="scatter_chart"),

            html.Div([
                html.Div([
                    dcc.Graph(id="distribution_chart")
                ], style={"width": "48%", "display": "inline-block"}),

                html.Div([
                    dcc.Graph(id="correlation_chart")
                ], style={"width": "48%", "display": "inline-block", "float": "right"})
            ]),

            html.H2("Top 20 Mașini Profitabile"),
            dash_table.DataTable(
                id="table_top20",
                columns=[
                    {"name": "Brand", "id": "brand"},
                    {"name": "Model", "id": "model"},
                    {"name": "An", "id": "year_extracted"},
                    {"name": "Km", "id": "mileage"},
                    {"name": "Preț (EUR)", "id": "price_eur"},
                    {"name": "Preț Estimat (EUR)", "id": "enhanced_pred_price"},
                    {"name": "Profitabilitate (%)", "id": "profitability_score"},
                    {"name": "Link", "id": "url", "presentation": "markdown"}
                ],
                style_table={"overflowX": "auto"},
                page_size=10,
                sort_action="native",
                filter_action="native"
            ),

            # Store pentru datele filtrate
            dcc.Store(id='filtered-data')
        ])

        @app.callback(
            Output('filtered-data', 'data'),
            [Input('apply_filters', 'n_clicks')],
            [State('brand_filter', 'value'),
             State('year_min', 'value'),
             State('profit_min', 'value'),
             State('caroserie_filter', 'value')]
        )
        def update_filtered_data(n_clicks, selected_brands, year_min, profit_min, selected_caroserie):
            if n_clicks == 0:
                return df.to_json(date_format='iso', orient='split')

            dff = df.copy()

            if selected_brands:
                dff = dff[dff["brand"].isin(selected_brands)]
            if year_min:
                dff = dff[dff["year_extracted"] >= year_min]
            if profit_min:
                dff = dff[dff["profitability_score"] >= profit_min]
            if selected_caroserie and "caroserie" in dff.columns:
                dff = dff[dff["caroserie"].isin(selected_caroserie)]

            return dff.to_json(date_format='iso', orient='split')

        @app.callback(
            [Output("scatter_chart", "figure"),
             Output("distribution_chart", "figure"),
             Output("correlation_chart", "figure"),
             Output("table_top20", "data")],
            [Input("filtered-data", "data")]
        )
        def update_dashboard(filtered_data):
            if filtered_data is None:
                return go.Figure(), go.Figure(), go.Figure(), []

            dff = pd.read_json(filtered_data, orient='split')

            if dff.empty:
                empty_fig = go.Figure()
                empty_fig.add_annotation(text="Nu există date pentru filtrele selectate",
                                         xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
                return empty_fig, empty_fig, empty_fig, []

            # Scatter plot
            scatter_fig = px.scatter(
                dff,
                x="enhanced_pred_price",
                y="price_eur",
                color="brand",
                hover_data=["model", "year_extracted", "mileage", "url", "profitability_score"],
                title="Preț prezis vs Preț real",
                labels={
                    "enhanced_pred_price": "Preț estimat (EUR)",
                    "price_eur": "Preț real (EUR)",
                    "brand": "Marca"
                }
            )
            scatter_fig.add_trace(
                go.Scatter(
                    x=[dff["enhanced_pred_price"].min(), dff["enhanced_pred_price"].max()],
                    y=[dff["enhanced_pred_price"].min(), dff["enhanced_pred_price"].max()],
                    mode="lines",
                    line=dict(color="black", dash="dash"),
                    name="Linie de egalitate"
                )
            )

            # Distribution plot
            distribution_fig = make_subplots(rows=1, cols=2,
                                             subplot_titles=("Distribuție prețuri", "Distribuție profitabilitate"))

            distribution_fig.add_trace(
                go.Histogram(x=dff["price_eur"], nbinsx=50, name="Preț real"),
                row=1, col=1
            )

            distribution_fig.add_trace(
                go.Histogram(x=dff["enhanced_pred_price"], nbinsx=50, name="Preț estimat"),
                row=1, col=1
            )

            distribution_fig.add_trace(
                go.Histogram(x=dff["profitability_score"], nbinsx=50, name="Profitabilitate"),
                row=1, col=2
            )

            distribution_fig.update_layout(showlegend=True, title_text="Distribuții")

            # Correlation heatmap
            numeric_cols = dff.select_dtypes(include=[np.number]).columns
            correlation_data = dff[numeric_cols].corr()

            correlation_fig = go.Figure(data=go.Heatmap(
                z=correlation_data.values,
                x=correlation_data.columns,
                y=correlation_data.index,
                colorscale='RdBu_r',
                zmin=-1,
                zmax=1
            ))
            correlation_fig.update_layout(title="Matrice de corelație")

            # Top 20 table
            top20 = dff.sort_values("profitability_score", ascending=False).head(20)
            top20["url"] = top20["url"].apply(lambda x: f"[Link]({x})" if pd.notnull(x) else "")

            return scatter_fig, distribution_fig, correlation_fig, top20.to_dict("records")

        logger.info("Dashboard-ul a fost lansat cu succes")
        app.run(debug=True, use_reloader=False)

    except Exception as e:
        logger.error(f"Eroare la lansarea dashboard-ului: {e}")


# ==============================
# FUNCȚIA PRINCIPALĂ ÎMBUNĂTĂȚITĂ
# ==============================
def main():
    """Funcția principală cu gestionare îmbunătățită a erorilor"""
    try:
        logger.info("Începere procesare date...")

        # Încărcare date
        df = pd.read_excel("data/raw_listings_old.xlsx")
        logger.info(f"Date încărcate: {len(df)} înregistrări")

        # Preprocesare
        logger.info("Preprocesare date...")
        df["clean_title"] = df["title"].apply(clean_text)
        df[["brand", "model"]] = df["title"].apply(lambda t: pd.Series(extract_brand_model(t)))
        df["year_extracted"] = df["title"].apply(extract_year)
        df["price_eur"] = df.apply(lambda r: normalize_price(r["price"], r["currency"]), axis=1)
        df["mileage"] = df.apply(lambda r: extract_mileage(r.get("mileage_km"), r.get("description", "")), axis=1)

        # Elimină înregistrări cu preț sau kilometraj invalid
        initial_count = len(df)
        df = df[df["price_eur"].notna() & (df["price_eur"] > 0)]
        df = df[df["mileage"].notna() & (df["mileage"] > 0)]
        logger.info(f"Înregistrări valide după filtrare: {len(df)}/{initial_count}")

        # Extrage caracteristici detaliate
        logger.info("Extragere caracteristici detaliate...")
        detailed_features = df.apply(
            lambda r: pd.Series(extract_detailed_features(
                str(r.get("title", "")) + " " + str(r.get("description", ""))
            )), axis=1
        )
        df = pd.concat([df, detailed_features], axis=1)

        # Detectare anunțuri suspecte
        logger.info("Detectare anunțuri suspecte...")
        df = detect_fraudulent_listings(df)
        suspect_count = len(df[df["suspect_score"] > 0])
        logger.info(f"Anunțuri suspecte detectate: {suspect_count}/{len(df)}")

        # Încarcă sau antrenează modelul
        logger.info("Procesare model machine learning...")
        model, feature_columns = load_or_train_model(df, force_retrain=False)

        # Calcul profitabilitate
        logger.info("Calcul scoruri profitabilitate...")
        df["profitability_score"] = df.apply(calculate_profitability_score, axis=1)

        # Export rezultate
        logger.info("Export rezultate...")
        export_top_excel(df, "top_masini_imbunatatit.xlsx", n=30)
        export_top_pdf(df, "top_masini_imbunatatit.pdf", n=30)

        # Afișează cele mai bune oportunități
        top5 = df[df['suspect_score'] < 3].sort_values("profitability_score", ascending=False).head(5)
        logger.info("Top 5 oportunități:")
        for i, (_, row) in enumerate(top5.iterrows(), 1):
            logger.info(f"{i}. {row['brand']} {row['model']} {row['year_extracted']} - "
                        f"Preț: {row['price_eur']:.2f} EUR, "
                        f"Estimat: {row['enhanced_pred_price']:.2f} EUR, "
                        f"Profit: {row['profitability_score']:.2f}%")

        # Lancează dashboard
        logger.info("Lansare dashboard...")
        run_enhanced_dashboard(df)

    except Exception as e:
        logger.error(f"Eroare în funcția principală: {e}")
        send_email_alert("Eroare în Car Analyzer", f"A apărut o eroare: {str(e)}")


if __name__ == "__main__":
    main()