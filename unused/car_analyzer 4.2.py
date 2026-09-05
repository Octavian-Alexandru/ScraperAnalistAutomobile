# ==============================
# CAR ANALYZER 4.2 – SCRIPT COMPLET GATA DE RULARE
# ==============================

import pandas as pd
import re, unidecode, numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error
from dash import Dash, dcc, html, dash_table, Input, Output
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# ==============================
# CONSTANTE
# ==============================
MARCAS = ["fiat", "opel", "peugeot", "ford", "skoda", "dacia", "renault", "bmw", "audi",
          "mercedes", "volkswagen", "seat", "hyundai", "kia", "toyota", "mazda", "nissan"]

DOTARI = ["camera spate", "senzori parcare", "incalzire scaune", "panou solar",
          "oglinzi electrice", "geamuri electrice", "aer conditionat", "cruise control",
          "pilot automat", "scaune piele", "volan incalzit", "trapa", "xenon", "bi-xenon"]

MOTORIZARE = ["gpl", "metan", "benzina+gpl"]

# ==============================
# PREPROCESARE
# ==============================
def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = unidecode.unidecode(text.lower())
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    stopwords = ["vand", "se", "vinde", "oferta", "cumpar", "vanzare", "autoutilitara"]
    for sw in stopwords:
        text = text.replace(" " + sw + " ", " ")
    return text.strip()

def extract_brand_model(title):
    title = clean_text(title)
    brand, model = None, None
    for marca in MARCAS:
        if marca in title:
            brand = marca
            break
    if brand:
        parts = title.split()
        if brand in parts:
            idx = parts.index(brand)
            if idx + 1 < len(parts):
                model = parts[idx + 1]
    return brand, model

def extract_year(title):
    match = re.search(r"\b(19[8-9]\d|20[0-2]\d)\b", title)
    return int(match.group(0)) if match else None

def normalize_price(price, currency):
    if pd.isna(price):
        return None
    try:
        price = float(str(price).replace(".", "").replace(",", "").strip())
    except:
        return None
    if isinstance(currency, str):
        currency = currency.lower()
        if "eur" in currency or "€" in currency:
            return price
        elif "ron" in currency or "lei" in currency:
            return price / 5
        elif "usd" in currency or "$" in currency:
            return price * 0.9
    return price

def extract_mileage(mileage_val, description=""):
    if isinstance(mileage_val, (int, float)):
        return mileage_val
    if isinstance(mileage_val, str):
        digits = re.sub(r"[^\d]", "", mileage_val)
        if digits:
            return int(digits)
    if isinstance(description, str):
        match = re.search(r"(\d{2,6})\s*km", description.lower())
        if match:
            return int(match.group(1))
    return None

# ==============================
# CARACTERISTICI DETALIATE
# ==============================
def extract_detailed_features(text):
    text = str(text).lower()
    features = {}
    engine_match = re.search(r'(\d{3,4})\s*cm3', text)
    features['engine_capacity'] = int(engine_match.group(1)) if engine_match else None
    power_match = re.search(r'(\d{2,3})\s*(cp|hp)', text)
    features['power'] = int(power_match.group(1)) if power_match else None
    features['de_la_proprietar'] = 1 if any(w in text for w in ['proprietar', 'particular']) else 0
    features['cu_factura'] = 1 if 'factura' in text else 0
    features['cu_garantie'] = 1 if 'garantie' in text else 0
    features['istoric_complet'] = 1 if any(w in text for w in ['istoric complet', 'service autorizat']) else 0
    features['fara_accidente'] = 1 if any(w in text for w in ['fara accidente', 'neaccidentata']) else 0
    return features

# ==============================
# DETECTARE SUSPECT
# ==============================
def detect_fraudulent_listings(df):
    df['suspect_price'] = 0
    df['suspect_mileage'] = 0
    for brand in df['brand'].dropna().unique():
        brand_data = df[df['brand'] == brand]
        if len(brand_data) > 5:
            Q1 = brand_data['price_eur'].quantile(0.25)
            Q3 = brand_data['price_eur'].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            df.loc[(df['brand'] == brand) & (df['price_eur'] < lower_bound), 'suspect_price'] = 1
    df.loc[(df['year_extracted'] > 0) & ((df['mileage'] / ((2025 - df['year_extracted']) + 1)) < 1000),
           'suspect_mileage'] = 1
    df.loc[(df['year_extracted'] > 0) & ((df['mileage'] / ((2025 - df['year_extracted']) + 1)) > 30000),
           'suspect_mileage'] = 1
    return df

# ==============================
# CALCUL PROFITABILITATE
# ==============================
def calculate_profitability_score(row):
    base_score = row.get('enhanced_profit_score', 0)
    if row.get('de_la_proprietar', 0) == 1: base_score *= 1.2
    if row.get('istoric_complet', 0) == 1: base_score *= 1.15
    if row.get('fara_accidente', 0) == 1: base_score *= 1.1
    if row.get('cu_factura', 0) == 0: base_score *= 0.9
    return base_score

# ==============================
# ENHANCED ML – ENSEMBLE
# ==============================
def enhanced_price_estimation(df):
    """
    Estimare preț îmbunătățită cu ensemble (XGB + RF + GBR)
    - Protecție împotriva valorilor negative
    - Log-transform pentru stabilitate
    """
    feature_cols = ["year_extracted", "mileage", "engine_capacity", "power"]
    X = df[feature_cols].fillna(df[feature_cols].median())

    # Log-transform pe prețuri
    y = np.log1p(df["price_eur"])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    models = {
        'xgb': XGBRegressor(random_state=42),
        'rf': RandomForestRegressor(random_state=42),
        'gbr': GradientBoostingRegressor(random_state=42)
    }

    best_models = {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        best_models[name] = model

        # Predicție pe test
        y_pred = model.predict(X_test)
        mae = mean_absolute_error(np.expm1(y_test), np.expm1(y_pred))
        print(f"{name.upper()} MAE: {mae:.2f}")

    # Ensemble prediction
    ensemble_pred_log = np.mean([m.predict(X) for m in best_models.values()], axis=0)

    # Transform înapoi din log
    ensemble_pred = np.expm1(ensemble_pred_log)

    # Clip pentru a evita valori negative
    ensemble_pred = np.clip(ensemble_pred, a_min=0, a_max=None)

    df["enhanced_pred_price"] = ensemble_pred
    df["enhanced_profit_score"] = ((df["enhanced_pred_price"] - df["price_eur"]) / df["enhanced_pred_price"]) * 100
    df["enhanced_profit_score"] = np.clip(df["enhanced_profit_score"], a_min=0, a_max=None)

    return df, best_models


# ==============================
# EXPORT
# ==============================
def export_top_excel(df, path="top_masini.xlsx", n=20):
    top = df.sort_values("enhanced_profit_score", ascending=False).head(n)
    cols = ["brand", "model", "year_extracted", "mileage", "price_eur", "enhanced_pred_price", "enhanced_profit_score", "url"]
    top[cols].to_excel(path, index=False)
    print(f"📊 Exportat Excel: {path}")

def export_top_pdf(df, path="top_masini.pdf", n=20):
    top = df.sort_values("enhanced_profit_score", ascending=False).head(n)
    cols = ["brand", "model", "year_extracted", "mileage", "price_eur", "enhanced_pred_price", "enhanced_profit_score"]
    data = [cols] + top[cols].values.tolist()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elements = [Paragraph("Top Mașini Profitabile", styles['Heading1']), Spacer(1, 12)]
    table = Table(data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("ALIGN", (0,0), (-1,-1), "CENTER")
    ]))
    elements.append(table)
    doc.build(elements)
    print(f"📄 Exportat PDF: {path}")

# ==============================
# DASHBOARD
# ==============================
def run_enhanced_dashboard(df):
    app = Dash(__name__)
    app.layout = html.Div([
        html.H1("Analiza Profitabilitate Mașini – Enhanced", style={"textAlign": "center"}),
        html.Div([html.Label("Marca:"),
                  dcc.Dropdown(options=[{"label": b, "value": b} for b in sorted(df["brand"].dropna().unique())],
                               id="brand_filter", multi=True, placeholder="Selectează mărci")],
                 style={"width": "25%", "display": "inline-block"}),
        html.Div([html.Label("An minim:"), dcc.Input(id="year_min", type="number", value=2005, step=1)],
                 style={"width": "15%", "display": "inline-block", "marginLeft": "20px"}),
        html.Div([html.Label("Profit minim (%):"), dcc.Input(id="profit_min", type="number", value=10, step=1)],
                 style={"width": "20%", "display": "inline-block", "marginLeft": "20px"}),
        dcc.Graph(id="scatter_chart"),
        html.H2("Top 10 Mașini Profitabile"),
        dash_table.DataTable(
            id="table_top10",
            columns=[{"name": i, "id": i, "presentation": "markdown"} if i == "url" else {"name": i, "id": i}
                     for i in ["brand", "model", "year_extracted", "mileage", "price_eur", "enhanced_pred_price",
                               "enhanced_profit_score", "url"]],
            style_table={"overflowX": "auto"},
            page_size=10
        )
    ])

    @app.callback(
        [Output("scatter_chart", "figure"), Output("table_top10", "data")],
        [Input("brand_filter", "value"), Input("year_min", "value"), Input("profit_min", "value")]
    )
    def update_dashboard(selected_brands, year_min, profit_min):
        dff = df.copy()
        if selected_brands: dff = dff[dff["brand"].isin(selected_brands)]
        if year_min: dff = dff[dff["year_extracted"] >= year_min]
        if profit_min: dff = dff[dff["enhanced_profit_score"] >= profit_min]

        if dff.empty:
            fig = px.scatter(title="Nu există date pentru filtrele selectate")
            top10 = pd.DataFrame()
        else:
            fig = px.scatter(dff, x="enhanced_pred_price", y="price_eur", color="brand",
                             hover_data=["model", "year_extracted", "mileage", "url"],
                             title="Preț prezis vs Preț real")
            fig.add_shape(type="line",
                          x0=dff["enhanced_pred_price"].min(), y0=dff["enhanced_pred_price"].min(),
                          x1=dff["enhanced_pred_price"].max(), y1=dff["enhanced_pred_price"].max(),
                          line=dict(color="black", dash="dash"))
            top10 = dff.sort_values("enhanced_profit_score", ascending=False).head(10)
            top10["url"] = top10["url"].apply(lambda x: f"[Link]({x})" if pd.notnull(x) else "")

        return fig, top10.to_dict("records")

    app.run(debug=True, use_reloader=False)

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    df = pd.read_excel("data/raw_listings_old.xlsx")
    df["clean_title"] = df["title"].apply(clean_text)
    df[["brand", "model"]] = df["title"].apply(lambda t: pd.Series(extract_brand_model(t)))
    df["year_extracted"] = df["title"].apply(extract_year)
    df["price_eur"] = df.apply(lambda r: normalize_price(r["price"], r["currency"]), axis=1)
    df["mileage"] = df.apply(lambda r: extract_mileage(r.get("mileage_km"), r.get("description", "")), axis=1)

    # Caracteristici detaliate
    detailed_features = df.apply(
        lambda r: pd.Series(extract_detailed_features(str(r.get("title", "")) + " " + str(r.get("description", "")))),
        axis=1)
    df = pd.concat([df, detailed_features], axis=1)

    # Detectare anunțuri suspecte
    df = detect_fraudulent_listings(df)

    # Antrenare modele ensemble
    df, trained_models = enhanced_price_estimation(df)

    # Scor profitabilitate
    df["profitability_score"] = df.apply(calculate_profitability_score, axis=1)

    # Export rezultate
    export_top_excel(df, "top_masini_imbunatatit.xlsx", n=30)
    export_top_pdf(df, "top_masini_imbunatatit.pdf", n=30)

    # Dashboard
    run_enhanced_dashboard(df)
