import pandas as pd
import numpy as np
import re
import os
import unicodedata
from sklearn.preprocessing import LabelEncoder

# --- CONFIGURARE CAI FISIERE ---
FILE_PATH_IN = os.path.join("data", "raw_listings_old.xlsx")
FILE_PATH_OUT = os.path.join("data", "ml_ready_listings.xlsx")
CURS_EUR = 5.09


def strip_accents(s):
    if pd.isna(s): return s
    return ''.join(c for c in unicodedata.normalize('NFD', str(s))
                   if unicodedata.category(c) != 'Mn')


KNOWN_BRANDS = [
    "mercedes-benz", "land rover", "alfa romeo", "aston martin", "rolls-royce",
    "volkswagen", "vw", "ssangyong", "mitsubishi", "chevrolet", "maserati",
    "porsche", "peugeot", "renault", "hyundai", "citroen", "bentley",
    "suzuki", "nissan", "toyota", "jaguar", "subaru", "dacia", "skoda",
    "volvo", "honda", "mazda", "lexus", "smart", "dodge", "cupra", "tesla",
    "ford", "audi", "opel", "fiat", "jeep", "mini", "bmw", "kia", "mg", "seat"
]

# Am marit si organizat baza de date cu "Echipari"
KNOWN_TRIMS = [
    # Sport/Performanta
    "amg", "m sport", "m pachet", "m-paket", "m-sport", "mpack", "s line", "s-line", "r-line", "r line", "gt-line",
    "gt line",
    "st-line", "st line", "rs", "gti", "gtd", "gte", "vrs", "fr", "cupra", "john cooper works", "jcw", "r-design",
    "rdesign",
    # Vw/Skoda/Seat
    "highline", "trendline", "comfortline", "lounge", "style", "life", "business", "ambition", "clever",
    "laurin & klement", "l&k", "sportline", "scout", "alltrack", "xcellence", "reference", "active", "iq drive",
    "soleil",
    # Renault/Dacia/Peugeot
    "allure", "active pack", "allure pack", "gt pack", "initiale paris", "intens", "zen", "bose", "stepway",
    "prestige", "essential", "expression", "extreme", "equilibre", "techno", "rs line", "r.s.line", "bose edition",
    # Audi/BMW/Mercedes
    "exclusive", "luxury", "avantgarde", "elegance", "comfort", "advanced", "design", "urban", "progressive",
    "edition 1",
    # Volvo/Ford/Altele
    "cross country", "summumm", "summum", "momentum", "inscription", "kinetic", "tekna", "acenta", "n-connecta",
    "visia", "vignale", "titanium",
    # Tractiune & Caroserie
    "4matic", "xdrive", "x-drive", "quattro", "4motion", "allgrip", "4wd", "4x4", "awd",
    "avant", "variant", "touring", "sportstourer", "sports tourer", "estate", "combi", "kombi",
    "cabrio", "coupe", "gran coupe", "grand coupe", "sportback", "fastback",
    "edition", "limited edition", "black edition", "shadow", "xline", "x-line"
]


def parse_car_title(title: str):
    if pd.isna(title) or not isinstance(title, str):
        return pd.Series([None, None, None])

    title_normalized = strip_accents(title).lower()
    found_brand = None

    for brand in KNOWN_BRANDS:
        if re.search(rf'\b{re.escape(brand)}\b', title_normalized):
            found_brand = brand
            break

    if not found_brand:
        return pd.Series([None, None, None])

    pattern_after_brand = rf'\b{re.escape(found_brand)}\b(.*)'
    match = re.search(pattern_after_brand, title_normalized)

    model_clean = ""
    trim_extracted = []

    if match:
        after_brand = match.group(1).strip()

        # 1. Extragem ECHIPARILE
        for trim in KNOWN_TRIMS:
            if re.search(rf'\b{re.escape(trim)}\b', after_brand):
                trim_extracted.append(trim.title())
                after_brand = re.sub(rf'\b{re.escape(trim)}\b', '', after_brand)

        # 2. TAIEREA RADICALA a Cifrelor "Murdare"
        # Taie: 1.5, 2.0, 18d, 20d, 35 tfsi, 110, 130, 140, 190, e-tech, tsi, crdi etc.
        cut_patterns = r'(\b\d\.\d\b|\b\d{2,3}d\b|\b\d{2}\s*tfsi\b|\b\d{2,4}\s*(cp|hp|kw|cmc|cc)\b|\b\d{3}\b|\b(19|20)\d{2}\b|\(|\||garantie|rate|livrare|pret|avans|\btdi\b|\btce\b|\bdci\b|\bdsg\b|\bedc\b|\bcdti\b|\bcrdi\b|\bmhev\b|\bphev\b|\bev\b|\be-tech\b|\btfsi\b|\btsi\b|\bfsi\b|\bbluehdi\b|\bhdi\b|\bmjet\b|\bhybrid\b|\bhibrid\b)'
        model_part = re.split(cut_patterns, after_brand)[0]

        # 3. CURATAREA DE CUVINTE GUNOI (Stopwords)
        junk_words = [
            'de vanzare', 'de vânzare', 'leasing', 'tva', 'deductibil', 'urgent',
            'impecabil', 'unic proprietar', 'proprietar', 'gpl', 'nou', 'inmatriculat',
            'oferta', 'credit', 'automat', 'automata', 'aut', 'manual', 'manuala', 'full', 'extra', 'navigatie',
            'navi', 'piele', 'xenon', 'trapa', 'kredit', 'tbi', 'buy back',
            'buy-back', 'rate', 'variante', 'schimb', 'cai', 'cp', 'kw', 'km', 'mii',
            'sedan', 'break', 'hatchback', 'suv', 'berlina', 'cutie', 'viteze',
            'primul', 'ro', 'inmatriculata', 'stare', 'foarte', 'buna', 'functionare',
            'fara', 'accident', 'daune', 'istoric', 'reprezentanta', 'facturi',
            'an', 'fab', 'fabricatie', 'facelift', 'model', 'generatie', 'gen',
            'motor', 'motorizare', 'disel', 'diesel', 'benzina', 'gaz', 'electric',
            's tronic', 'stronic', 'geartronic', 'xtronic', 'tiptronic', 'steptronic',
            'blueefficiency', 'bluetec', 'ecoboost', 'ecoblue', 'puretech', 'stop start', 's&s',
            'startstop', 'start&stop'
        ]

        model_clean = model_part.lower()
        for word in junk_words:
            model_clean = re.sub(rf'\b{word}\b', '', model_clean)

        # Curatam caracterele speciale la final (ex: *, -, _, /, ., !)
        model_clean = re.sub(r'[^a-zA-Z0-9\s-]', '', model_clean)
        model_clean = " ".join(model_clean.split()).strip(' -/,|').title()

    brand_map = {
        "citroen": "Citroën",
        "vw": "Volkswagen",
        "volkswagen": "Volkswagen",
        "bmw": "BMW",
        "mg": "MG",
        "mercedes-benz": "Mercedes-Benz"
    }

    brand_formatted = brand_map.get(found_brand, found_brand.title())
    model_formatted = model_clean if model_clean else None

    # Unim echiparile gasite
    trim_formatted = " ".join(trim_extracted) if trim_extracted else "Standard"

    return pd.Series([brand_formatted, model_formatted, trim_formatted])


def preprocess_pipeline():
    print("[+] Incarcam datele brute...")
    df = pd.read_excel(FILE_PATH_IN)
    initial_len = len(df)

    print("[+] Extragem Brand, Model si Echipare (Trim)...")
    df[['Brand', 'Model', 'Trim']] = df['title'].apply(parse_car_title)

    print("[+] Extragem Capacitatea Motorului (engine_size)...")
    df['engine_size'] = df['title'].str.extract(r'\b(\d\.\d)\b').astype(float)
    df.loc[(df['engine_size'] < 0.8) | (df['engine_size'] > 6.0), 'engine_size'] = np.nan
    df['engine_size'] = df['engine_size'].fillna(df['engine_size'].median())

    df = df.drop_duplicates(subset=['car_id', 'title', 'price', 'year'])

    df['currency'] = df['currency'].astype(str).str.upper().str.strip()
    mask_ron = df['currency'] == 'RON'
    df.loc[mask_ron, 'price'] = df.loc[mask_ron, 'price'] / CURS_EUR
    df.loc[mask_ron, 'currency'] = 'EUR'
    df['price'] = df['price'].round(2)

    print("[+] Tratam valorile lipsa...")
    df = df.dropna(subset=['Brand', 'Model', 'price', 'year'])
    df = df[df['Model'].str.len() > 0]  # Stergem randurile in care modelul a devenit "gol"

    if 'dealer' in df.columns:
        df['dealer'] = df['dealer'].fillna('Privat')

    df['mileage_km'] = df.groupby('year')['mileage_km'].transform(lambda x: x.fillna(x.median()))
    df['mileage_km'] = df['mileage_km'].fillna(df['mileage_km'].median())

    print("[+] Tratam outlierii...")
    df = df[(df['year'] >= 1990) & (df['year'] <= 2026)]
    df = df[(df['price'] >= 500) & (df['price'] <= 150000)]
    df = df[~((df['year'] < 2025) & (df['mileage_km'] < 100))]
    df = df[df['mileage_km'] <= 800000]

    print("[+] Aplicam Categorical Encoding...")
    le = LabelEncoder()

    if 'fuel_type' in df.columns:
        df['fuel_type'] = df['fuel_type'].fillna('Necunoscut')
        df['fuel_type_encoded'] = le.fit_transform(df['fuel_type'].astype(str))

    if 'seller_type' in df.columns:
        df['seller_type'] = df['seller_type'].fillna('Necunoscut')
        df['seller_type_encoded'] = le.fit_transform(df['seller_type'].astype(str))

    df.to_excel(FILE_PATH_OUT, index=False)

    final_len = len(df)
    print("=" * 40)
    print("📋 RAPORT PREPROCESARE:")
    print(f"Rânduri inițiale: {initial_len}")
    print(f"Rânduri eliminate (lipsuri/outlieri): {initial_len - final_len}")
    print(f"Rânduri finale valide: {final_len}")
    print(f"[+] Datele curate au fost salvate în: {FILE_PATH_OUT}")
    print("=" * 40)


if __name__ == "__main__":
    preprocess_pipeline()