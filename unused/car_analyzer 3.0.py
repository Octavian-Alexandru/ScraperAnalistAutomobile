import pandas as pd
import re
import unidecode
import plotly.express as px
from rapidfuzz import fuzz
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import openpyxl
import dash
from dash import dcc, html, dash_table, Input, Output


# --- lista de marci si modele ---
MARCAS = [
    "fiat", "opel", "peugeot", "ford", "skoda", "dacia", "renault",
    "bmw", "audi", "mercedes", "volkswagen", "seat", "hyundai", "kia",
    "toyota", "mazda", "nissan"
]

# =============================
# FUNCTII DE PREPROCESARE
# =============================

def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unidecode.unidecode(text.lower())
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    stopwords = ["vand", "se", "vinde", "oferta", "cumpar", "vanzare", "autoutilitara"]
    for sw in stopwords:
        text = text.replace(" " + sw + " ", " ")
    return text.strip()

def extract_brand_model(title: str):
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

def extract_year(title: str):
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

# =============================
# DEDUPLICARE
# =============================

def deduplicate(df, threshold=85):
    seen = []
    unique_rows = []
    for idx, row in df.iterrows():
        title = row["clean_title"]
        duplicate = False
        for prev in seen:
            score = fuzz.ratio(title, prev)
            if score >= threshold and abs(
                    row["price_eur"] - df.loc[df["clean_title"] == prev, "price_eur"].mean()) < 200:
                duplicate = True
                break
        if not duplicate:
            seen.append(title)
            unique_rows.append(idx)
    return df.loc[unique_rows].reset_index(drop=True)

# =============================
# MODELARE + PROFITABILITATE
# =============================

def train_price_model(df):
    data = df[["brand", "model", "year_extracted", "mileage", "price_eur"]].dropna()
    X = data[["brand", "model", "year_extracted", "mileage"]]
    y = data["price_eur"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    categorical = ["brand", "model"]
    numeric = ["year_extracted", "mileage"]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", "passthrough", numeric)
        ]
    )

    model = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("regressor", RandomForestRegressor(n_estimators=200, random_state=42))
    ])

    model.fit(X_train, y_train)
    score = model.score(X_test, y_test)
    print(f"🔍 Acuratete model pe setul de test: {score:.2f}")
    return model

def compute_ml_profitability(df, model):
    features = df[["brand", "model", "year_extracted", "mileage"]].fillna(0)
    preds = model.predict(features)
    df["pred_price"] = preds
    df["profit_score_ml"] = ((df["pred_price"] - df["price_eur"]) / df["pred_price"]) * 100
    return df

def top_profitable_ml(df, n=10):
    return df.sort_values("profit_score_ml", ascending=False).head(n)

def process_excel_ml(path: str):
    df = pd.read_excel(path)
    df["clean_title"] = df["title"].apply(clean_text)
    df[["brand", "model"]] = df["title"].apply(lambda t: pd.Series(extract_brand_model(t)))
    df["year_extracted"] = df["title"].apply(extract_year)
    df["price_eur"] = df.apply(lambda row: normalize_price(row["price"], row["currency"]), axis=1)
    df["mileage"] = df.apply(lambda row: extract_mileage(row["mileage_km"], row.get("description", "")), axis=1)
    df = deduplicate(df)
    model = train_price_model(df)
    df = compute_ml_profitability(df, model)
    return df

# =============================
# DASHBOARD
# =============================

def run_dashboard(df):
    app = dash.Dash(__name__)

    app.layout = html.Div([
        html.H1("Analiza Profitabilitate Mașini", style={"textAlign": "center"}),

        html.Div([
            html.Label("Marca:"),
            dcc.Dropdown(
                options=[{"label": b, "value": b} for b in sorted(df["brand"].dropna().unique())],
                id="brand_filter",
                multi=True,
                placeholder="Selectează una sau mai multe mărci"
            ),
        ], style={"width": "25%", "display": "inline-block"}),

        html.Div([
            html.Label("An minim:"),
            dcc.Input(id="year_min", type="number", value=2005, step=1)
        ], style={"width": "15%", "display": "inline-block", "marginLeft": "20px"}),

        html.Div([
            html.Label("Profit minim (%):"),
            dcc.Input(id="profit_min", type="number", value=10, step=1)
        ], style={"width": "20%", "display": "inline-block", "marginLeft": "20px"}),

        dcc.Graph(id="scatter_chart"),

        html.H2("Top 10 Mașini Profitabile"),
        dash_table.DataTable(
            id="table_top10",
            columns=[{"name": i, "id": i, "presentation": "markdown"} if i == "url"
                     else {"name": i, "id": i}
                     for i in ["brand", "model", "year_extracted", "mileage", "price_eur", "pred_price", "profit_score_ml", "url"]],
            style_table={"overflowX": "auto"},
            page_size=10
        )
    ])

    @app.callback(
        [Output("scatter_chart", "figure"),
         Output("table_top10", "data")],
        [Input("brand_filter", "value"),
         Input("year_min", "value"),
         Input("profit_min", "value")]
    )
    def update_dashboard(selected_brands, year_min, profit_min):
        dff = df.copy()
        if selected_brands:
            dff = dff[dff["brand"].isin(selected_brands)]
        if year_min:
            dff = dff[dff["year_extracted"] >= year_min]
        if profit_min:
            dff = dff[dff["profit_score_ml"] >= profit_min]

        fig = px.scatter(
            dff,
            x="pred_price", y="price_eur",
            color="brand",
            hover_data=["model", "year_extracted", "mileage", "url"],
            title="Preț prezis vs Preț real"
        )
        fig.add_shape(
            type="line",
            x0=dff["pred_price"].min(),
            y0=dff["pred_price"].min(),
            x1=dff["pred_price"].max(),
            y1=dff["pred_price"].max(),
            line=dict(color="black", dash="dash")
        )

        top10 = dff.sort_values("profit_score_ml", ascending=False).head(10)
        top10["url"] = top10["url"].apply(lambda x: f"[Link]({x})" if pd.notnull(x) else "")
        return fig, top10.to_dict("records")

    app.run(debug=True, use_reloader=False)

def export_top_excel(df, path="top_masini.xlsx", n=20):
    """Exportă top N mașini profitabile în Excel."""
    top = df.sort_values("profit_score_ml", ascending=False).head(n)
    cols = ["brand", "model", "year_extracted", "mileage", "price_eur", "pred_price", "profit_score_ml", "url"]
    top[cols].to_excel(path, index=False)
    print(f"📊 Exportat în Excel: {path}")


def export_top_pdf(df, path="top_masini.pdf", n=20):
    """Exportă top N mașini profitabile în PDF."""
    top = df.sort_values("profit_score_ml", ascending=False).head(n)
    cols = ["brand", "model", "year_extracted", "mileage", "price_eur", "pred_price", "profit_score_ml"]

    data = [cols] + top[cols].values.tolist()

    doc = SimpleDocTemplate(path, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Top Mașini Profitabile", styles['Heading1']))
    elements.append(Spacer(1, 12))

    table = Table(data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))

    elements.append(table)
    doc.build(elements)
    print(f"📄 Exportat în PDF: {path}")

# =============================
# MAIN
# =============================

if __name__ == "__main__":
    df = process_excel_ml("raw_listings_old.xlsx")
    top10 = top_profitable_ml(df, n=10)
    print("\n=== Top 10 masini profitabile (bazat pe ML) ===\n")
    print(top10[["brand", "model", "year_extracted", "mileage", "price_eur", "pred_price", "profit_score_ml", "url"]])

    # Export rapoarte
    export_top_excel(df, "top_masini.xlsx", n=20)
    export_top_pdf(df, "top_masini.pdf", n=20)

    # rulează dashboard
    run_dashboard(df)
