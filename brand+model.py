import pandas as pd
import re
import os
import unicodedata

# Fisierul de intrare/iesire
FILE_PATH_IN = os.path.join("data", "raw_listings_old.xlsx")
FILE_PATH_OUT = os.path.join("data", "processed_listings.xlsx")

# Functie ajutatoare pentru a scoate accentele (ë -> e)
def strip_accents(s):
   return ''.join(c for c in unicodedata.normalize('NFD', s)
                  if unicodedata.category(c) != 'Mn')

# 1. Lista de branduri recunoscute
# (Sortate descrescator dupa lungime pentru a prinde "Land Rover" inainte de "Rover")
KNOWN_BRANDS = [
    "mercedes-benz", "land rover", "alfa romeo", "aston martin", "rolls-royce",
    "volkswagen","vw", "ssangyong", "mitsubishi", "chevrolet", "maserati",
    "porsche", "peugeot", "renault", "hyundai", "citroen", "bentley",
    "suzuki", "nissan", "toyota", "jaguar", "subaru", "dacia", "skoda",
    "volvo", "honda", "mazda", "lexus", "smart", "dodge", "cupra", "tesla",
    "ford", "audi", "opel", "fiat", "jeep", "mini", "bmw", "kia", "mg", "seat"
]


def parse_car_title(title: str):
    if pd.isna(title) or not isinstance(title, str):
        return pd.Series([None, None])

    # PASUL 1: Normalizam titlul (scoatem 'ë' si facem lowercase)
    # Exemplu: "Vând CITROËN C3" -> "vand citroen c3"
    title_normalized = strip_accents(title).lower()

    found_brand = None

    # Pasul 2: Gasim Brand-ul
    for brand in KNOWN_BRANDS:
        if re.search(rf'\b{re.escape(brand)}\b', title_normalized):
            found_brand = brand
            break

    if not found_brand:
        return pd.Series([None, None])

    # Pasul 3: Extragem ce urmeaza DUPA brand folosind titlul normalizat
    pattern_after_brand = rf'\b{re.escape(found_brand)}\b(.*)'
    match = re.search(pattern_after_brand, title_normalized)

    model_clean = None
    if match:
        after_brand = match.group(1).strip()

        # Regex-ul tau pentru taiere (pastrat/ajustat)
        cut_patterns = r'(\d\.\d|\b\d{2,4}\s*(cp|hp|kw)\b|\b(19|20)\d{2}\b|\(|\||garantie|rate|livrare|pret|avans|\btdi\b|\btce\b|\bdci\b|\bdsg\b)'
        model_part = re.split(cut_patterns, after_brand)[0]
        model_clean = model_part.strip(' -/,|').title()

    # Formatari estetice finala
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

    return pd.Series([brand_formatted, model_formatted])

def process_excel():
    if not os.path.exists(FILE_PATH_IN):
        print(f"[!] Fisierul {FILE_PATH_IN} nu exista!")
        return

    print(f"[+] Incarcam datele din {FILE_PATH_IN}...")
    df = pd.read_excel(FILE_PATH_IN)

    if 'title' not in df.columns:
        print("[!] Coloana 'title' nu a fost gasita in fisier!")
        return

    print("[+] Extragem Brand si Model...")
    # Aplicam functia pe coloana title si cream automat 2 coloane noi
    df[['Brand', 'Model']] = df['title'].apply(parse_car_title)

    # Reordonam coloanele pentru a pune Brand si Model fix dupa 'title' (optional, pentru lizibilitate)
    cols = df.columns.tolist()
    # Mutam Brand si Model la inceput (dupa title)
    title_idx = cols.index('title')
    cols.insert(title_idx + 1, cols.pop(cols.index('Brand')))
    cols.insert(title_idx + 2, cols.pop(cols.index('Model')))
    df = df[cols]

    # Salvam inapoi in fisier
    df.to_excel(FILE_PATH_OUT, index=False)
    print(f"[+] Procesare finalizata! Fisierul a fost salvat ca: {FILE_PATH_OUT}")

    # Afisam un mic preview
    print(df[['title', 'Brand', 'Model']].head(10).to_string(index=False))


if __name__ == "__main__":
    process_excel()