# FILE: main.py
"""
Pipeline de preprocesare a datelor auto si antrenare a modelului ML.
- Incarca datele direct din SQLite (data/cars.db) sau din Excel ca fallback.
- Standardizeaza Brand, Model, Trim, Combustibil si Capacitate Cilindrica.
- Elimina anunturile capcana (daune, leasing, volan dreapta).
- Salveaza dataset-ul curat in `data/ml_ready_listings.parquet` (rapid) si `.xlsx`.
- Antreneaza automat modelul de estimare a preturilor si il salveaza in `models/price_model.joblib`.
"""

import os
import re
import datetime
import unicodedata
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score

from db_helper import get_all_listings_df, DB_PATH

# --- CONFIGURARE CAI FISIERE ---
FILE_PATH_IN = os.path.join("data", "raw_listings_old.xlsx")
FILE_PATH_OUT = os.path.join("data", "ml_ready_listings.xlsx")
PARQUET_PATH_OUT = os.path.join("data", "ml_ready_listings.parquet")
MODEL_PATH = os.path.join("models", "price_model.joblib")
CURS_EUR = 5.09

FEATURES = ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size']


def strip_accents(s):
    if pd.isna(s):
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(s))
                   if unicodedata.category(c) != 'Mn')


KNOWN_BRANDS = [
    "mercedes-benz", "mercedes", "land rover", "alfa romeo", "aston martin", "rolls-royce",
    "volkswagen", "vw", "ssangyong", "mitsubishi", "chevrolet", "maserati",
    "porsche", "peugeot", "renault", "hyundai", "citroen", "bentley",
    "suzuki", "nissan", "toyota", "jaguar", "subaru", "dacia", "skoda",
    "volvo", "honda", "mazda", "lexus", "smart", "dodge", "cupra", "tesla",
    "ford", "audi", "opel", "fiat", "jeep", "mini", "bmw", "kia", "mg", "seat"
]

BRAND_MAP = {
    "citroen": "Citroën",
    "vw": "Volkswagen",
    "volkswagen": "Volkswagen",
    "bmw": "BMW",
    "mg": "MG",
    "mercedes-benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "skoda": "Škoda"
}

KNOWN_TRIMS = [
    "amg", "m sport", "m pachet", "m-paket", "m-sport", "mpack", "s line", "s-line",
    "r-line", "r line", "gt-line", "gt line", "st-line", "st line", "rs line", "r.s.line",
    "vrs", "fr", "john cooper works", "jcw", "r-design", "rdesign",
    "highline", "trendline", "comfortline", "style", "business", "ambition",
    "laurin & klement", "l&k", "sportline", "scout", "alltrack", "xcellence",
    "allure", "gt pack", "initiale paris", "intens", "zen", "bose", "stepway",
    "prestige", "extreme", "equilibre", "techno", "exclusive", "luxury",
    "avantgarde", "elegance", "progressive", "cross country", "summum",
    "momentum", "inscription", "tekna", "acenta", "n-connecta", "vignale", "titanium",
    "4matic", "xdrive", "x-drive", "quattro", "4motion", "allgrip", "4x4", "awd"
]

CANONICAL_MODELS = {
    "BMW": [
        (r'\b(seria\s*1|11[468][di]?|12[035][di]?)\b', 'Seria 1'),
        (r'\b(seria\s*2|21[8][di]?|22[05][di]?)\b', 'Seria 2'),
        (r'\b(seria\s*3|31[68][di]?|32[0358][di]?|33[05][di]?|g20|f30|e90)\b', 'Seria 3'),
        (r'\b(seria\s*4|418[di]?|42[058][di]?|43[05][di]?)\b', 'Seria 4'),
        (r'\b(seria\s*5|518[di]?|52[0358][di]?|53[05][di]?|540[di]?|g30|f10)\b', 'Seria 5'),
        (r'\b(seria\s*6|630[di]?|640[di]?)\b', 'Seria 6'),
        (r'\b(seria\s*7|730[di]?|740[di]?|750[di]?)\b', 'Seria 7'),
        (r'\b(x\s*1|x1)\b', 'X1'), (r'\b(x\s*2|x2)\b', 'X2'), (r'\b(x\s*3|x3)\b', 'X3'),
        (r'\b(x\s*4|x4)\b', 'X4'), (r'\b(x\s*5|x5)\b', 'X5'), (r'\b(x\s*6|x6)\b', 'X6'),
        (r'\b(x\s*7|x7)\b', 'X7'), (r'\b(i3)\b', 'i3'), (r'\b(i4)\b', 'i4'), (r'\b(ix3)\b', 'iX3')
    ],
    "Mercedes-Benz": [
        (r'\b(clasa\s*a|a\s*class|a\s*1[68]0|a\s*2[025]0|a180|a200)\b', 'Clasa A'),
        (r'\b(clasa\s*b|b\s*class|b\s*180|b\s*200|b180|b200)\b', 'Clasa B'),
        (r'\b(clasa\s*c|c\s*class|c\s*180|c\s*2[025]0|c\s*300|c180|c200|c220|w204|w205)\b', 'Clasa C'),
        (r'\b(clasa\s*e|e\s*class|e\s*2[025]0|e\s*3[05]0|e200|e220|w212|w213)\b', 'Clasa E'),
        (r'\b(clasa\s*s|s\s*class|s\s*350|s\s*400|s\s*500|s350|s400|s500)\b', 'Clasa S'),
        (r'\b(cla)\b', 'CLA'), (r'\b(cls)\b', 'CLS'), (r'\b(gla)\b', 'GLA'),
        (r'\b(glb)\b', 'GLB'), (r'\b(glc)\b', 'GLC'), (r'\b(gle)\b', 'GLE'),
        (r'\b(gls)\b', 'GLS'), (r'\b(ml|m-class)\b', 'ML'), (r'\b(glk)\b', 'GLK'),
        (r'\b(vito)\b', 'Vito'), (r'\b(v\s*class|clasa\s*v)\b', 'Clasa V'), (r'\b(sprinter)\b', 'Sprinter')
    ],
    "Audi": [
        (r'\b(a1)\b', 'A1'), (r'\b(a2)\b', 'A2'), (r'\b(a3)\b', 'A3'),
        (r'\b(a4)\b', 'A4'), (r'\b(a5)\b', 'A5'), (r'\b(a6)\b', 'A6'),
        (r'\b(a7)\b', 'A7'), (r'\b(a8)\b', 'A8'),
        (r'\b(q2)\b', 'Q2'), (r'\b(q3)\b', 'Q3'), (r'\b(q5)\b', 'Q5'),
        (r'\b(q7)\b', 'Q7'), (r'\b(q8)\b', 'Q8'), (r'\b(e-tron)\b', 'e-tron')
    ],
    "Volkswagen": [
        (r'\b(golf)\b', 'Golf'), (r'\b(passat)\b', 'Passat'), (r'\b(tiguan)\b', 'Tiguan'),
        (r'\b(touareg)\b', 'Touareg'), (r'\b(polo)\b', 'Polo'), (r'\b(arteon)\b', 'Arteon'),
        (r'\b(t-roc|troc)\b', 'T-Roc'), (r'\b(t-cross|tcross)\b', 'T-Cross'),
        (r'\b(touran)\b', 'Touran'), (r'\b(sharan)\b', 'Sharan'), (r'\b(caddy)\b', 'Caddy')
    ]
}

BLACKLIST_PATTERNS = re.compile(
    r'\b(?:avariat[ae]?|daun[ae]|accidentat[ae]?| pt\s*piese|dezmembr|volan\s*(?:pe\s*)?dreapta|anglia|'
    r'predare\s*leasing|cesiune\s*leasing|preluare\s*leasing|doar\s*avans|avans\s*\d+|'
    r'inchiriez|inchiriere|rent\s*a\s*car|motor\s*defect|cutie\s*defecta|defect[ae]?)\b',
    re.IGNORECASE
)


def parse_car_title(title: str):
    if pd.isna(title) or not isinstance(title, str):
        return pd.Series([None, None, "Standard"])

    title_norm = strip_accents(title).lower()
    found_brand = None

    for brand in KNOWN_BRANDS:
        if re.search(rf'\b{re.escape(brand)}\b', title_norm):
            found_brand = brand
            break

    if not found_brand:
        return pd.Series([None, None, "Standard"])

    brand_formatted = BRAND_MAP.get(found_brand, found_brand.title())

    # 1. Extragem Echiparile (Trim)
    trim_extracted = []
    text_for_model = title_norm
    for trim in KNOWN_TRIMS:
        if re.search(rf'\b{re.escape(trim)}\b', text_for_model):
            trim_extracted.append(trim.upper() if len(trim) <= 3 else trim.title())
            text_for_model = re.sub(rf'\b{re.escape(trim)}\b', ' ', text_for_model)

    trim_formatted = " ".join(sorted(set(trim_extracted))) if trim_extracted else "Standard"

    # 2. Verificam daca avem o regula canonica
    if brand_formatted in CANONICAL_MODELS:
        for pattern, canonical_name in CANONICAL_MODELS[brand_formatted]:
            if re.search(pattern, title_norm):
                return pd.Series([brand_formatted, canonical_name, trim_formatted])

    # 3. Extragere generica
    match = re.search(rf'\b{re.escape(found_brand)}\b(.*)', text_for_model)
    if not match:
        return pd.Series([brand_formatted, None, trim_formatted])

    after_brand = match.group(1).strip()
    cut_regex = (
        r'(?:\b\d\.\d\b|\b\d{2,3}\s*(?:cp|hp|kw|cai)\b|\b\d{3,4}\s*(?:cmc|cc|cm3)\b|'
        r'\b(?:199\d|20[0-2]\d)\b|\(|\||garantie|rate|livrare|pret|avans|'
        r'\b(?:tdi|tce|dci|dsg|edc|cdti|crdi|mhev|phev|e-tech|tfsi|tsi|fsi|bluehdi|hdi|mjet|hybrid|hibrid|gpl|automat[a]?|manual[a]?|euro\s*\d)\b)'
    )
    model_part = re.split(cut_regex, after_brand)[0]

    junk_words = [
        'de vanzare', 'vand', 'oferta', 'urgent', 'impecabil', 'impecabila', 'proprietar',
        'unic', 'inmatriculat', 'inmatriculata', ' Romania', 'ro', 'full', 'extra', 'dotari',
        'navigatie', 'piele', 'trapa', 'xenon', 'led', 'matrix', ' sport', 'sedan', 'berlina',
        'break', 'hatchback', 'suv', 'combi', 'kombi', 'variant', 'avant', 'touring', 'sportback',
        'cabrio', 'coupe', 'facelift', 'model', 'nou', 'stare', 'perfecta', 'diesel', 'benzina',
        'electric', 'electrica', 'auto', ' autoturism', 'tva', 'deductibil', 'factura'
    ]
    for word in junk_words:
        model_part = re.sub(rf'\b{word.strip()}\b', ' ', model_part)

    model_part = re.sub(r'\b(golf|octavia|fabia|focus|fiesta|megane|clio|astra|corsa|leon|ibiza|polo|passat)\s+(?:[1-8]|i{1,3}|iv|v|vi|vii|viii|b[5-9]|mk\d)\b', r'\1', model_part)
    model_part = re.sub(r'[^a-zA-Z0-9\s-]', ' ', model_part)
    tokens = [t for t in model_part.split() if len(t) > 0]

    if not tokens:
        return pd.Series([brand_formatted, None, trim_formatted])

    two_word_models = {
        "santa fe", "grand scenic", "grand cherokee", "land cruiser", "range rover",
        "discovery sport", "c max", "c-max", "b max", "b-max", "s max", "s-max",
        "cee d", "pro ceed", "serie 1", "serie 3", "serie 5", "clasa a", "clasa c", "clasa e"
    }
    first_two = " ".join(tokens[:2]).lower()
    if first_two in two_word_models or (tokens[0] in ['grand', 'range', 'land', 'alfa', 'aston', 'seria', 'clasa'] and len(tokens) >= 2):
        model_clean = " ".join(tokens[:2]).title()
    else:
        model_clean = tokens[0].upper() if len(tokens[0]) <= 3 and any(c.isdigit() for c in tokens[0]) else tokens[0].title()

    return pd.Series([brand_formatted, model_clean, trim_formatted])


def infer_fuel_type(row):
    current = str(row.get('fuel_type', '')).strip().lower()
    if current in ['diesel', 'benzina', 'benzină', 'hibrid', 'hybrid', 'electric', 'gpl']:
        if current in ['benzină', 'benzina']: return 'Benzina'
        if current in ['hibrid', 'hybrid']: return 'Hibrid'
        return current.capitalize()

    text = strip_accents(f"{row.get('title', '')} {row.get('description', '')}").lower()
    if re.search(r'\b(electric[a]?|100%\s*electric|ev|id\.?[345]|model\s*[3ysx]|zoe|spring|kona\s*ev|e-golf|ioniq\s*5)\b', text):
        return 'Electric'
    if re.search(r'\b(hibrid|hybrid|phev|mhev|e-tech|gti\s*gte|gte|iv|e-hybrid)\b', text):
        return 'Hibrid'
    if re.search(r'\b(gpl|gaz)\b', text):
        return 'GPL'
    if re.search(r'\b(tdi|dci|hdi|bluehdi|cdti|crdi|tdci|mjet|multijet|bluetec|cdi|d4d|d-4d|diesel|disel|\d{3}d|2\.0d|1\.5d|3\.0d)\b', text):
        return 'Diesel'
    if re.search(r'\b(tsi|tfsi|fsi|tce|ecoboost|puretech|vti|mpi|gdi|tgdi|vtec|vvti|benzina|\d{3}i)\b', text):
        return 'Benzina'

    return 'Diesel'


def infer_engine_size(row):
    if row.get('fuel_type') == 'Electric':
        return 0.0

    text = strip_accents(f"{row.get('title', '')} {row.get('description', '')}").lower()
    m_liters = re.search(r'\b([0-6]\.[0-9])\b', text)
    if m_liters:
        val = float(m_liters.group(1))
        if 0.8 <= val <= 6.5:
            return val

    m_cc = re.search(r'\b([89]\d{2}|[1-5]\d{3})\s*(?:cm3|cmc|cc)\b', text)
    if m_cc:
        val = round(int(m_cc.group(1)) / 1000.0, 1)
        if 0.8 <= val <= 6.5:
            return val

    return np.nan


def load_raw_data() -> pd.DataFrame:
    """Incarca datele brute prioritizand SQLite, apoi Excel."""
    if os.path.exists(DB_PATH):
        try:
            print(f"[+] Incarcam datele din baza de date SQLite {DB_PATH}...")
            df = get_all_listings_df(active_only=False, db_path=DB_PATH)
            if not df.empty:
                # Aliniere nume coloana pret
                if 'price_eur' in df.columns:
                    df['price'] = df['price_eur']
                return df
        except Exception as e:
            print(f"[!] Eroare la citirea SQLite: {e}. Trecem pe Excel fallback.")

    if os.path.exists(FILE_PATH_IN):
        print(f"[+] Incarcam datele din Excel {FILE_PATH_IN}...")
        return pd.read_excel(FILE_PATH_IN)

    raise FileNotFoundError(f"Nu s-au gasit nici {DB_PATH} si nici {FILE_PATH_IN}!")


def preprocess_pipeline() -> pd.DataFrame:
    df = load_raw_data()
    initial_len = len(df)

    # 1. Filtrare anunturi capcana
    full_text = df['title'].fillna('').astype(str) + " " + df.get('description', pd.Series('', index=df.index)).fillna('').astype(str)
    mask_blacklist = full_text.str.contains(BLACKLIST_PATTERNS, regex=True, na=False)
    print(f"[!] Eliminam {mask_blacklist.sum()} anunturi capcana (avariate / leasing / piese).")
    df = df[~mask_blacklist].copy()

    # 2. Conversie Valutara daca e cazul
    df['currency'] = df['currency'].astype(str).str.upper().str.strip()
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    mask_ron = df['currency'].isin(['RON', 'LEI'])
    df.loc[mask_ron, 'price'] = (df.loc[mask_ron, 'price'] / CURS_EUR).round(0)
    df.loc[mask_ron, 'currency'] = 'EUR'

    # 3. Extragere Brand, Model, Trim
    print("[+] Extragem si standardizam Brand, Model si Trim...")
    df[['Brand', 'Model', 'Trim']] = df['title'].apply(parse_car_title)

    # 4. Curatare An si Rulaj
    df['year'] = pd.to_numeric(df['year'], errors='coerce')
    df['mileage_km'] = pd.to_numeric(df['mileage_km'], errors='coerce')

    df = df.dropna(subset=['Brand', 'Model', 'price', 'year'])
    df = df[df['Model'].str.len() >= 2]

    # 5. Deduplicare
    df = df.drop_duplicates(subset=['Brand', 'Model', 'year', 'mileage_km', 'price'])

    # 6. Deductie combustibil si motor
    print("[+] Deductie inteligenta pentru combustibil si motorizare...")
    df['fuel_type'] = df.apply(infer_fuel_type, axis=1)
    df['engine_size'] = df.apply(infer_engine_size, axis=1)

    df['engine_size'] = df['engine_size'].fillna(df.groupby(['Brand', 'Model'])['engine_size'].transform('median'))
    df['engine_size'] = df['engine_size'].fillna(df.groupby('Brand')['engine_size'].transform('median'))
    df['engine_size'] = df['engine_size'].fillna(df['engine_size'].median())

    # Corectie rulaje tastate scurt
    mask_km_scurt = (df['year'] <= 2023) & (df['mileage_km'] >= 50) & (df['mileage_km'] <= 450)
    df.loc[mask_km_scurt, 'mileage_km'] = df.loc[mask_km_scurt, 'mileage_km'] * 1000

    df['mileage_km'] = df['mileage_km'].fillna(df.groupby('year')['mileage_km'].transform('median'))
    df['mileage_km'] = df['mileage_km'].fillna(df['mileage_km'].median())

    # 7. Filtrare Outlieri Fizici
    df = df[(df['year'] >= 2010) & (df['year'] <= 2026)]
    df = df[(df['price'] >= 1000) & (df['price'] <= 150000)]
    df = df[(df['mileage_km'] >= 100) & (df['mileage_km'] <= 500000)]

    model_counts = df.groupby(['Brand', 'Model'])['price'].transform('count')
    df = df[model_counts >= 5].copy()

    # Eliminare outlieri per (Brand, Model) prin IQR
    Q1 = df.groupby(['Brand', 'Model'])['price'].transform(lambda x: x.quantile(0.20))
    Q3 = df.groupby(['Brand', 'Model'])['price'].transform(lambda x: x.quantile(0.80))
    IQR = Q3 - Q1
    df = df[(df['price'] >= Q1 - 1.5 * IQR) & (df['price'] <= Q3 + 1.5 * IQR)].copy()

    # Salvare Parquet (rapid) si Excel (backup)
    os.makedirs("data", exist_ok=True)
    df.to_parquet(PARQUET_PATH_OUT, index=False, engine="pyarrow")
    print(f"[+] Dataset salvat ca Parquet: {PARQUET_PATH_OUT} ({len(df):,} masini)")

    print("=" * 50)
    print("RAPORT PREPROCESARE COMPLETA:")
    print(f"Randuri initiale:          {initial_len:,}")
    print(f"Randuri valide ML:         {len(df):,}")
    print(f"Marci unice:               {df['Brand'].nunique()}")
    print(f"Modele canonice curate:    {df['Model'].nunique()}")
    print("=" * 50)

    return df


def train_and_save_model(dataframe: pd.DataFrame):
    """Antreneaza modelul de pret si il salveaza pe disc in models/price_model.joblib."""
    print("[*] Incepem antrenarea modelului ML pe datele curate...")
    os.makedirs("models", exist_ok=True)

    df_ml = dataframe.dropna(subset=FEATURES + ['price']).copy()
    X = df_ml[FEATURES]
    y = df_ml['price']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), ['year', 'mileage_km', 'engine_size']),
            ('cat', OneHotEncoder(handle_unknown='ignore'), ['Brand', 'Model', 'Trim', 'fuel_type'])
        ]
    )

    model = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor', RandomForestRegressor(
            n_estimators=150,
            max_depth=18,
            min_samples_split=6,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        ))
    ])

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    model_payload = {
        "model": model,
        "mae": round(mae, 1),
        "r2": round(r2, 4),
        "features": FEATURES,
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "train_rows": len(df_ml),
        "unique_models": df_ml['Model'].nunique()
    }

    joblib.dump(model_payload, MODEL_PATH)
    print(f"[+] Model ML salvat cu succes in: {MODEL_PATH}")
    print(f"    - Acuratete R2:     {r2 * 100:.1f}%")
    print(f"    - Eroare Medie MAE: +- {mae:,.0f} EUR")
    print(f"    - Modele analizate: {model_payload['unique_models']}")
    return model_payload


def run_preprocessing_and_training():
    df_clean = preprocess_pipeline()
    model_stats = train_and_save_model(df_clean)
    return df_clean, model_stats


if __name__ == "__main__":
    run_preprocessing_and_training()