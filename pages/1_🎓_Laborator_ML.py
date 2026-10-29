import os
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.tree import plot_tree

st.set_page_config(page_title="Laborator ML", layout="wide", page_icon="🎓")

st.title("🎓 Laboratorul de Machine Learning")
st.markdown(
    "Aici vizualizăm **Arborii de Decizie** și experimentăm cu parametrii modelului pentru a înțelege conceptele de **Underfitting** și **Overfitting**."
)

PARQUET_FILE = 'data/ml_ready_listings.parquet'
EXCEL_FILE = 'data/ml_ready_listings.xlsx'


# --- INCARCAREA DATELOR ---
@st.cache_data
def load_data():
    if os.path.exists(PARQUET_FILE):
        df = pd.read_parquet(PARQUET_FILE)
    elif os.path.exists(EXCEL_FILE):
        df = pd.read_excel(EXCEL_FILE)
    else:
        st.warning("Nu s-a găsit dataset-ul pregătit. Rulează mai întâi pipeline-ul.")
        st.stop()

    features = ['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']
    df = df.dropna(subset=features + ['price'])
    return df


df = load_data()

# --- INTERFATA DE CONTROL (HYPERPARAMETERS) ---
st.sidebar.header("🎛️ Panou de Comandă ML")
st.sidebar.markdown("Joacă-te cu aceste controale și urmărește cum se schimbă acuratețea și forma arborelui în timp real.")

# Selector Brand pentru antrenare rapida interactiva
marci_disponibile = ["Toate Mărcile (Eșantion rapid)"] + sorted(df['Brand'].unique().tolist())
select_marca = st.sidebar.selectbox("Filtrează pe Marcă", marci_disponibile, index=0)

if select_marca != "Toate Mărcile (Eșantion rapid)":
    df_lab = df[df['Brand'] == select_marca].copy()
else:
    # Eșantion de 5.000 mașini pentru ca re-antrenarea live la slider să fie sub 1 secundă
    df_lab = df.sample(min(len(df), 5000), random_state=42).copy()

# Slider pentru Numarul de Arbori
n_trees = st.sidebar.slider(
    "1. Număr de Arbori (n_estimators)", min_value=1, max_value=80, value=30, step=1,
    help="Câți 'experți' votează prețul. Mai mulți = Pădure mai stabilă, dar mai lentă."
)

# Slider pentru Adâncimea Arborelui
max_depth = st.sidebar.slider(
    "2. Adâncime Maximă (max_depth)", min_value=1, max_value=25, value=10, step=1,
    help="Câte întrebări succesive are voie să pună un arbore. Prea mic = Underfit. Prea mare = Overfit."
)

# --- PREGATIREA MODELULUI (LIVE) ---
X = df_lab[['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']]
y = df_lab['price']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), ['year', 'mileage_km', 'engine_size']),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['Brand', 'Model', 'fuel_type'])
    ]
)

# Antrenam pipeline-ul
with st.spinner(f"Antrenăm modelul pe {len(df_lab):,} mașini..."):
    X_train_processed = preprocessor.fit_transform(X_train)
    X_test_processed = preprocessor.transform(X_test)
    feature_names = preprocessor.get_feature_names_out()

    rf = RandomForestRegressor(n_estimators=n_trees, max_depth=max_depth, random_state=42, n_jobs=-1)
    rf.fit(X_train_processed, y_train)

    y_train_pred = rf.predict(X_train_processed)
    r2_train = r2_score(y_train, y_train_pred)
    rmse_train = np.sqrt(mean_squared_error(y_train, y_train_pred))

    y_test_pred = rf.predict(X_test_processed)
    r2_test = r2_score(y_test, y_test_pred)
    rmse_test = np.sqrt(mean_squared_error(y_test, y_test_pred))

# --- AFISARE REZULTATE SI METRICI ---
st.subheader("📊 Cum se descurcă algoritmul?")
st.markdown("Compară performanța pe datele pe care le-a învățat (**Train**) cu performanța pe date noi, nevăzute (**Test**).")

col1, col2 = st.columns(2)
with col1:
    st.info("📚 **Pe Datele Învățate (Train Data)**")
    st.metric("Acuratețe Train (R²)", f"{r2_train * 100:.1f}%")
    st.metric("Eroare (RMSE Train)", f"± {rmse_train:,.0f} €")

with col2:
    st.success("🎯 **Pe Datele Nevăzute (Test Data - Viața Reală)**")
    st.metric("Acuratețe Test (R²)", f"{r2_test * 100:.1f}%")
    st.metric("Eroare (RMSE Test)", f"± {rmse_test:,.0f} €")

# --- DIAGNOSTIC AUTOMAT ---
st.markdown("---")
if max_depth <= 3:
    st.warning("⚠️ **UNDERFITTING (Sub-învățare):** Arborele este prea mic. Nu pune destule întrebări ca să înțeleagă piața auto. Ambele scoruri (Train și Test) sunt mici.")
elif r2_train - r2_test > 0.15:
    st.error("🚨 **OVERFITTING (Supra-învățare / Tocit):** Modelul a învățat pe de rost datele de antrenare (Acuratețe Train uriașă), dar se pierde pe date noi (Acuratețe Test mică). Adâncimea este prea mare!")
else:
    st.success("✅ **ZONĂ OPTIMĂ (Generalizare Bună):** Modelul are o adâncime corectă. Înțelege regulile pieței fără să memoreze mașini individuale.")

# --- VIZUALIZAREA ARBORELUI ---
st.markdown("---")
st.subheader(f"🌳 Anatomia unui Arbore de Decizie (Adâncime maximă vizualizată: {min(max_depth, 3)})")
st.markdown("Aici este Primul Arbore din Pădurea Aleatoare. Urmărește cum se împart deciziile din 'Rădăcină' până la 'Frunze'.")

fig, ax = plt.subplots(figsize=(20, 10), dpi=150)
plot_tree(
    rf.estimators_[0],
    feature_names=feature_names,
    filled=True,
    rounded=True,
    fontsize=10,
    max_depth=3,
    precision=0,
    ax=ax
)

st.pyplot(fig)

with st.expander("🤔 Cum se citește acest grafic?"):
    st.markdown("""
    * **Prima linie (ex: `num__year <= 2018.5`)**: Întrebarea pe care o pune nodul.
    * **mse**: Eroarea pătratică medie în acel punct.
    * **samples**: Numărul de mașini care au ajuns la acest nivel.
    * **value**: Prețul estimat al mașinilor din acel nod.
    * **Culori**: Nuanțele mai închise indică valori mai mari ale prețului.
    """)