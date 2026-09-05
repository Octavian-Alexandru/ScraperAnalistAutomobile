import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score

# --- CONFIGURARE PAGINA ---
st.set_page_config(page_title="Radar Comercial Auto", layout="wide", page_icon="💸")

st.title("💸 Radar Comercial Auto (Powered by ML)")
st.markdown(
    "Acest instrument analizează ofertele auto și îți calculează potențialul de profit pentru a face flipping (achiziție și revânzare).")


# --- 1. INCARCAREA SI PREGATIREA DATELOR ---
@st.cache_data
def load_and_prepare_data():
    df = pd.read_excel('data/ml_ready_listings.xlsx')
    # Pastram URL-ul si Titlul pentru tab-ul de chilipiruri!
    features = ['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size', 'price', 'url', 'title']

    # Ne asiguram ca avem coloanele de baza
    # (Pastram doar anunturile care au date in coloanele necesare pentru predictie)
    df = df.dropna(subset=['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size', 'price'])
    return df


df = load_and_prepare_data()

# Eliminare matematică a extremelor de preț, grupat pe Brand (doar pentru a curata zgomotul)
Q1 = df.groupby('Brand')['price'].transform(lambda x: x.quantile(0.25))
Q3 = df.groupby('Brand')['price'].transform(lambda x: x.quantile(0.75))
IQR = Q3 - Q1
df = df[(df['price'] >= Q1 - 1.5 * IQR) & (df['price'] <= Q3 + 1.5 * IQR)]


# --- 2. CREAREA SI ANTRENAREA MODELULUI ---
@st.cache_resource
def train_model(dataframe):
    X = dataframe[['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']]
    y = dataframe['price']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), ['year', 'mileage_km', 'engine_size']),
            ('cat', OneHotEncoder(handle_unknown='ignore'), ['Brand', 'Model', 'fuel_type'])
        ])

    model = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor',
         RandomForestRegressor(n_estimators=150, max_depth=15, min_samples_split=5, random_state=42, n_jobs=-1))
    ])

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    return model, mae, r2


with st.spinner('Se analizează piața auto pe baza a mii de anunțuri...'):
    model, mae, r2 = train_model(df)

# --- 3. METRICI ASCUNSE ---
with st.expander("Vezi detaliile tehnice ale modelului ML"):
    c1, c2, c3 = st.columns(3)
    c1.metric("Date Antrenare", f"{len(df):,} mașini")
    c2.metric("Acuratețe (R²)", f"{r2 * 100:.1f}%")
    c3.metric("Marjă Eroare (MAE)", f"± {mae:,.0f} €")

st.divider()

# --- IMPARTIREA IN TAB-URI ---
tab1, tab2 = st.tabs(["🔍 Analiză Anunț Specific", "💎 Vânător de Chilipiruri (Live DB)"])

# =====================================================================
# TAB 1: ANALIZA MANUALĂ
# =====================================================================
with tab1:
    st.subheader("Evaluează un Anunț / Calculează Profitul")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        brand_list = sorted(df['Brand'].unique().tolist())
        selected_brand = st.selectbox("1. Marca", brand_list)
        model_list = sorted(df[df['Brand'] == selected_brand]['Model'].unique().tolist())
        selected_model = st.selectbox("2. Modelul", model_list)
        selected_fuel = st.selectbox("3. Combustibil", df['fuel_type'].unique().tolist())

    with col_b:
        selected_year = st.slider("4. An Fabricație", min_value=2014, max_value=2026, value=2019)
        selected_km = st.number_input("5. Kilometraj (km)", min_value=0, max_value=400000, value=150000, step=5000)
        selected_engine = st.number_input("6. Motor (ex: 1.5, 2.0)", min_value=0.8, max_value=6.0, value=2.0, step=0.1)

    with col_c:
        st.info("Introduceți prețul cerut de vânzător pentru a vedea dacă este o afacere bună.")
        pret_cerut = st.number_input("💰 Preț cerut în anunț (EUR)", min_value=500, max_value=150000, value=10000,
                                     step=500)

    if st.button("Analizează Oferta", type="primary", use_container_width=True):
        input_data = pd.DataFrame({
            'Brand': [selected_brand], 'Model': [selected_model], 'year': [selected_year],
            'mileage_km': [selected_km], 'fuel_type': [selected_fuel], 'engine_size': [selected_engine]
        })

        predicted_price = model.predict(input_data)[0]
        diferenta = predicted_price - pret_cerut

        st.markdown("---")
        st.subheader("📊 Rezultatul Analizei Comerciale")

        res_1, res_2, res_3 = st.columns(3)
        res_1.metric("Valoare Reală Estimată", f"{predicted_price:,.0f} €")
        res_2.metric("Preț Vânzător", f"{pret_cerut:,.0f} €")

        if diferenta > mae:
            res_3.metric("Potențial Profit (Arbitraj)", f"+ {diferenta:,.0f} €", "Afacere Excelentă")
            st.success(
                f"🔥 **CHILIPIR:** Vânzătorul cere cu {diferenta:,.0f} € mai puțin decât prețul mediu al pieței. Această mașină are un potențial mare de revânzare.")
        elif diferenta < -mae:
            res_3.metric("Pierdere / Supraevaluată", f"{diferenta:,.0f} €", "De evitat")
            st.error(
                f"⚠️ **SUPRAEVALUATĂ:** Vânzătorul cere un preț mult prea mare. Valoarea ei corectă este în jur de {predicted_price:,.0f} €.")
        else:
            res_3.metric("Marjă", f"{diferenta:,.0f} €", "Preț Corect", delta_color="off")
            st.warning(
                "⚖️ **PREȚ CORECT:** Mașina este vândută la prețul pieței. Nu există o marjă evidentă pentru bișniță/profit.")

        # GRAFIC DE DEPRECIERE SIMULAT
        st.markdown("### 📉 Curba de Depreciere a acestui Model")

        sim_years = list(range(2014, 2026))
        sim_data = []
        for y in sim_years:
            sim_km = selected_km + ((selected_year - y) * 15000)
            sim_km = max(0, sim_km)
            sim_data.append({
                'Brand': selected_brand, 'Model': selected_model, 'year': y,
                'mileage_km': sim_km, 'fuel_type': selected_fuel, 'engine_size': selected_engine
            })

        df_sim = pd.DataFrame(sim_data)
        df_sim['Estimare_Pret'] = model.predict(df_sim)

        fig = px.line(df_sim, x='year', y='Estimare_Pret', markers=True,
                      labels={'year': 'An Fabricație', 'Estimare_Pret': 'Preț Estimat (EUR)'},
                      title=f"Evoluția Prețului pentru {selected_brand} {selected_model} ({selected_engine} {selected_fuel})")

        fig.add_scatter(x=[selected_year], y=[predicted_price], mode='markers',
                        marker=dict(color='red', size=15), name='Anunțul Tău')

        st.plotly_chart(fig, use_container_width=True)

# =====================================================================
# TAB 2: VÂNĂTORUL DE CHILIPIRURI (Pe toata baza de date)
# =====================================================================
with tab2:
    st.subheader("🛒 Găsește cele mai subevaluate mașini din baza ta de date")
    st.markdown(
        "Alege filtrele dorite, iar modelul ML va scana instant toate cele ~17.000 de oferte extrase, calculând pentru fiecare în parte dacă prețul cerut este mai mic decât valoarea ei reală.")

    fil_1, fil_2, fil_3 = st.columns(3)
    with fil_1:
        marca_filtru = st.selectbox("Alege Marca (sau Toate)", ["Toate"] + brand_list)
    with fil_2:
        pret_max_filtru = st.number_input("Buget Maxim (EUR)", min_value=1000, max_value=100000, value=15000, step=1000)
    with fil_3:
        km_max_filtru = st.number_input("Rulaj Maxim (km)", min_value=10000, max_value=400000, value=200000, step=10000)

    if st.button("Găsește Chilipiruri (Scanare ML)", type="primary"):
        with st.spinner("Modelul ML evaluează mii de anunțuri..."):
            # 1. Filtram dataframe-ul de baza conform cerintelor userului
            df_scan = df.copy()
            if marca_filtru != "Toate":
                df_scan = df_scan[df_scan['Brand'] == marca_filtru]

            df_scan = df_scan[(df_scan['price'] <= pret_max_filtru) & (df_scan['mileage_km'] <= km_max_filtru)]

            if not df_scan.empty:
                # 2. Extragem variabilele independente si facem predictia pe tot subsetul
                X_scan = df_scan[['Brand', 'Model', 'year', 'mileage_km', 'fuel_type', 'engine_size']]
                df_scan['pret_estimat_ml'] = model.predict(X_scan)

                # 3. Calculam marja de profit: Pretul Estimat - Pretul Cerut
                df_scan['marja_profit'] = df_scan['pret_estimat_ml'] - df_scan['price']

                # 4. Filtram doar masinile unde profitul este MAI MARE decat marja medie de eroare a modelului (MAE)
                # Astfel, evitam ofertele care sunt ieftine doar din cauza zgomotului statistic
                oferte_bune = df_scan[df_scan['marja_profit'] > mae].copy()

                # Le sortam dupa cel mai mare profit potential si luam top 50
                oferte_bune = oferte_bune.sort_values(by='marja_profit', ascending=False).head(50)

                if not oferte_bune.empty:
                    st.success(f"Am găsit {len(oferte_bune)} oferte excelente!")
                    st.warning(
                        "⚠️ **Atenție:** Dacă o mașină are o marjă de profit astronomică (ex: +7.000€), este foarte probabil să aibă defecte ascunse grave, volan pe dreapta sau să fie o înșelătorie. Verifică mereu link-ul!")

                    # 5. Configuram tabelul elegant cu link-uri
                    coloane_afisare = ['title', 'year', 'mileage_km', 'price', 'pret_estimat_ml', 'marja_profit', 'url']

                    st.dataframe(
                        oferte_bune[coloane_afisare],
                        column_config={
                            "title": "Titlu Anunț",
                            "year": "An",
                            "mileage_km": st.column_config.NumberColumn("Rulaj (km)", format="%d km"),
                            "price": st.column_config.NumberColumn("Preț Cerut", format="%d €"),
                            "pret_estimat_ml": st.column_config.NumberColumn("Valoare Reală ML", format="%d €"),
                            "marja_profit": st.column_config.NumberColumn("Profit Potențial", format="🟢 %d €"),
                            "url": st.column_config.LinkColumn("Link OLX/Autovit", display_text="🔗 Deschide Anunțul")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info(
                        "Nu am găsit nicio mașină subevaluată clar pentru aceste filtre. Încearcă un buget mai mare!")
            else:
                st.error("Nu există mașini în baza de date care să corespundă acestor filtre.")