import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.tree import plot_tree

st.set_page_config(page_title="Laborator ML", layout="wide", page_icon="🎓")

st.title("🎓 Laboratorul de Machine Learning")
st.markdown(
    "Aici vizualizăm **Arborii de Decizie** și experimentăm cu parametrii modelului pentru a înțelege conceptele de **Underfitting** și **Overfitting**.")


# --- INCARCAREA DATELOR ---
@st.cache_data
def load_data():
    df = pd.read_excel('data/ml_ready_listings.xlsx')
    features = ['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']
    df = df.dropna(subset=features + ['price'])
    # Eliminam extremele la fel ca in app-ul principal
    Q1 = df.groupby('Brand')['price'].transform(lambda x: x.quantile(0.25))
    Q3 = df.groupby('Brand')['price'].transform(lambda x: x.quantile(0.75))
    IQR = Q3 - Q1
    df = df[(df['price'] >= Q1 - 1.5 * IQR) & (df['price'] <= Q3 + 1.5 * IQR)]
    return df


df = load_data()

# --- INTERFATA DE CONTROL (HYPERPARAMETERS) ---
st.sidebar.header("🎛️ Panou de Comandă ML")
st.sidebar.markdown("Joacă-te cu aceste slidere și urmărește cum se schimbă acuratețea și forma arborelui.")

# Slider pentru Numarul de Arbori
n_trees = st.sidebar.slider("1. Număr de Arbori (n_estimators)", min_value=1, max_value=100, value=50, step=1,
                            help="Câți 'experți' votează prețul. Mai mulți = Pădure mai stabilă, dar mai lentă.")

# Slider pentru Adâncimea Arborelui
max_depth = st.sidebar.slider("2. Adâncime Maximă (max_depth)", min_value=1, max_value=30, value=12, step=1,
                              help="Câte întrebări succesive are voie să pună un arbore. Prea mic = Underfit. Prea mare = Overfit.")

# --- PREGATIREA MODELULUI (LIVE) ---
X = df[['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']]
y = df['price']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), ['year', 'mileage_km', 'engine_size']),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['Brand', 'Model', 'fuel_type'])
    ])

# Antrenam pipeline-ul
with st.spinner('Antrenăm modelul cu noii parametri...'):
    # Transformam datele manual pentru a putea extrage numele coloanelor pentru grafic
    X_train_processed = preprocessor.fit_transform(X_train)
    X_test_processed = preprocessor.transform(X_test)

    # Obtinem numele coloanelor transformate (ex: Brand_BMW, Model_Seria 3)
    feature_names = preprocessor.get_feature_names_out()

    # Definim si antrenam padurea
    rf = RandomForestRegressor(n_estimators=n_trees, max_depth=max_depth, random_state=42, n_jobs=-1)
    rf.fit(X_train_processed, y_train)

    # Predictii Train
    y_train_pred = rf.predict(X_train_processed)
    r2_train = r2_score(y_train, y_train_pred)
    rmse_train = np.sqrt(mean_squared_error(y_train, y_train_pred))

    # Predictii Test
    y_test_pred = rf.predict(X_test_processed)
    r2_test = r2_score(y_test, y_test_pred)
    rmse_test = np.sqrt(mean_squared_error(y_test, y_test_pred))

# --- AFISARE REZULTATE SI METRICI ---
st.subheader("📊 Cum se descurcă algoritmul?")
st.markdown(
    "Compară performanța pe datele pe care le-a învățat (**Train**) cu performanța pe date noi, nevăzute (**Test**).")

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
    st.warning(
        "⚠️ **UNDERFITTING (Sub-învățare):** Arborele este prea mic. Nu pune destule întrebări ca să înțeleagă piața auto. Ambele scoruri (Train și Test) sunt mici.")
elif r2_train - r2_test > 0.15:  # Daca diferenta e mai mare de 15%
    st.error(
        "🚨 **OVERFITTING (Supra-învățare / Tocit):** Modelul a învățat pe de rost datele de antrenare (Acuratețe Train uriașă), dar se pierde complet la date noi (Acuratețe Test mică). Adâncimea este prea mare!")
else:
    st.success(
        "✅ **ZONĂ OPTIMĂ (Generalizare Bună):** Modelul are o adâncime corectă. Înțelege regulile pieței fără să memoreze mașini individuale.")

# --- VIZUALIZAREA ARBORELUI ---
st.markdown("---")
st.subheader(f"🌳 Anatomia unui Arbore de Decizie (Adâncime maximă arătată: {min(max_depth, 3)})")
st.markdown(
    "Aici este Primul Arbore din Pădurea ta Aleatoare. Urmărește cum se împart datele din 'Rădăcină' (sus) până la 'Frunze' (prețul estimat jos).")

# Desenam arborele (limitam afisarea la max_depth=3 ca sa nu blocheze ecranul cu milioane de noduri)
fig, ax = plt.subplots(figsize=(20, 10), dpi=150)
plot_tree(rf.estimators_[0],
          feature_names=feature_names,
          filled=True,
          rounded=True,
          fontsize=10,
          max_depth=3,  # Il limitam vizual ca sa incapa pe ecran
          precision=0,
          ax=ax)

st.pyplot(fig)

with st.expander("🤔 Cum se citește acest grafic?"):
    st.markdown("""
    * **Prima linie (ex: `num__year <= 2018.5`)**: Este întrebarea pe care o pune algoritmul.
    * **mse**: Eroarea matematică în acel punct. Scopul arborelui e să scadă acest MSE la fiecare pas.
    * **samples**: Câte mașini au ajuns la acest nivel de decizie.
    * **value**: Prețul estimat al mașinilor din acel nod (Dacă s-ar opri aici).
    * **Culori**: Culorile mai închise indică valori mai mari ale prețului.
    """)