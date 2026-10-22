import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import joblib

from db_helper import get_price_drops, get_db_stats, DB_PATH

st.set_page_config(page_title="Radar Comercial Auto", layout="wide", page_icon="💸")

st.title("💸 Radar Comercial Auto (Powered by ML)")
st.markdown(
    "Acest instrument analizează ofertele auto din România, detectează **scăderile recente de preț** și calculează potențialul de profit pentru **flipping**."
)

PARQUET_FILE = 'data/ml_ready_listings.parquet'
EXCEL_FILE = 'data/ml_ready_listings.xlsx'
MODEL_FILE = 'models/price_model.joblib'
FEATURES = ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size']


@st.cache_data
def load_and_prepare_data():
    """Incarca rapid dataset-ul pregatit (Parquet <0.1s, fallback Excel)."""
    if os.path.exists(PARQUET_FILE):
        df = pd.read_parquet(PARQUET_FILE)
    elif os.path.exists(EXCEL_FILE):
        df = pd.read_excel(EXCEL_FILE)
    else:
        st.error("Nu s-a gasit dataset-ul pregatit. Ruleaza mai intai 'python main.py' sau 'python run_daily_pipeline.py'.")
        st.stop()

    if 'Trim' not in df.columns:
        df['Trim'] = 'Standard'
    df['Trim'] = df['Trim'].fillna('Standard')

    required_cols = ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size', 'price']
    df = df.dropna(subset=required_cols)
    return df.reset_index(drop=True)


@st.cache_resource
def load_trained_model(dataframe):
    """Incarca modelul pre-antrenat de pe disc (0.05s). Daca lipseste, il antreneaza ca fallback."""
    if os.path.exists(MODEL_FILE):
        try:
            payload = joblib.load(MODEL_FILE)
            return payload['model'], payload['mae'], payload['r2'], payload.get('trained_at', 'Salvat')
        except Exception:
            pass

    # Fallback doar daca nu exista model_file
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import mean_absolute_error, r2_score

    X = dataframe[FEATURES]
    y = dataframe['price']
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
            n_estimators=100, max_depth=16, min_samples_split=6, random_state=42, n_jobs=-1
        ))
    ])
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    return model, mae, r2, "Antrenat Live"


df = load_and_prepare_data()
model, mae, r2, model_date = load_trained_model(df)

# Header Metrics
with st.expander("ℹ️ Detalii Tehnice ale Bazei de Date & Modelului ML", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Date Antrenare Curate", f"{len(df):,} mașini")
    c2.metric("Modele Auto Analizate", f"{df['Model'].nunique()} modele")
    c3.metric("Acuratețe (R² pe Test)", f"{r2 * 100:.1f}%")
    c4.metric("Marjă Eroare (MAE)", f"± {mae:,.0f} €")
    st.caption(f"Ultima actualizare model: {model_date}")

st.divider()

tab1, tab2, tab3 = st.tabs([
    "🔍 Analiză Anunț Specific",
    "💎 Vânător de Chilipiruri (Live DB)",
    "📉 Radar Scăderi de Preț (Price Drops Live)"
])

# =====================================================================
# TAB 1: ANALIZA MANUALĂ
# =====================================================================
with tab1:
    st.subheader("Evaluează un Anunț / Calculează Profitul")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        brand_list = sorted(df['Brand'].unique().tolist())
        selected_brand = st.selectbox("1. Marca", brand_list)

        df_brand = df[df['Brand'] == selected_brand]
        model_list = sorted(df_brand['Model'].unique().tolist())
        selected_model = st.selectbox("2. Modelul", model_list)

        df_model_sub = df_brand[df_brand['Model'] == selected_model]
        trim_list = sorted(df_model_sub['Trim'].unique().tolist())
        selected_trim = st.selectbox("3. Echipare / Tracțiune", trim_list)

    with col_b:
        fuel_list = sorted(df_model_sub['fuel_type'].unique().tolist()) if not df_model_sub.empty else ['Diesel', 'Benzina']
        selected_fuel = st.selectbox("4. Combustibil", fuel_list)
        selected_year = st.slider("5. An Fabricație", min_value=int(df['year'].min()), max_value=2026, value=2019)
        selected_km = st.number_input("6. Kilometraj (km)", min_value=0, max_value=400000, value=150000, step=5000)

    with col_c:
        default_engine = float(df_model_sub['engine_size'].median()) if not df_model_sub.empty and pd.notna(df_model_sub['engine_size'].median()) else 2.0
        selected_engine = st.number_input("7. Motor (L)", min_value=0.0, max_value=6.5, value=default_engine, step=0.1)
        pret_cerut = st.number_input("💰 Preț cerut în anunț (EUR)", min_value=500, max_value=100000, value=10000, step=250)

    if st.button("Analizează Oferta", type="primary", use_container_width=True):
        input_data = pd.DataFrame({
            'Brand': [selected_brand],
            'Model': [selected_model],
            'Trim': [selected_trim],
            'year': [selected_year],
            'mileage_km': [selected_km],
            'fuel_type': [selected_fuel],
            'engine_size': [selected_engine]
        })

        predicted_price = model.predict(input_data)[0]
        diferenta = predicted_price - pret_cerut

        st.markdown("---")
        st.subheader("📊 Rezultatul Analizei Comerciale")

        res_1, res_2, res_3 = st.columns(3)
        res_1.metric("Valoare Reală Estimată (ML)", f"{predicted_price:,.0f} €")
        res_2.metric("Preț Vânzător", f"{pret_cerut:,.0f} €")

        if diferenta > mae:
            res_3.metric("Potențial Profit (Arbitraj)", f"+ {diferenta:,.0f} €", "Afacere Excelentă")
            st.success(
                f"🔥 **CHILIPIR:** Vânzătorul cere cu **{diferenta:,.0f} €** sub media pieței pentru echiparea **{selected_trim}**."
            )
        elif diferenta < -mae:
            res_3.metric("Pierdere / Supraevaluată", f"{diferenta:,.0f} €", "De evitat")
            st.error(
                f"⚠️ **SUPRAEVALUATĂ:** Prețul corect de piață este în jur de **{predicted_price:,.0f} €**."
            )
        else:
            res_3.metric("Marjă", f"{diferenta:,.0f} €", "Preț Corect", delta_color="off")
            st.warning("⚖️ **PREȚ CORECT:** Mașina este listată la prețul pieței.")

        # Grafic de depreciere simulat
        st.markdown("### 📉 Curba de Depreciere a acestui Model")
        sim_years = list(range(2014, 2026))
        sim_data = []
        for y in sim_years:
            sim_km = max(5000, selected_km + ((selected_year - y) * 15000))
            sim_data.append({
                'Brand': selected_brand, 'Model': selected_model, 'Trim': selected_trim,
                'year': y, 'mileage_km': sim_km, 'fuel_type': selected_fuel, 'engine_size': selected_engine
            })

        df_sim = pd.DataFrame(sim_data)
        df_sim['Estimare_Pret'] = model.predict(df_sim)

        fig = px.line(
            df_sim, x='year', y='Estimare_Pret', markers=True,
            labels={'year': 'An Fabricație', 'Estimare_Pret': 'Preț Estimat (EUR)'},
            title=f"Evoluția Prețului pentru {selected_brand} {selected_model} ({selected_trim}, {selected_engine}L {selected_fuel})"
        )
        fig.add_scatter(
            x=[selected_year], y=[pret_cerut], mode='markers',
            marker=dict(color='red', size=14, symbol='star'), name='Preț Anunț Analizat'
        )
        st.plotly_chart(fig, use_container_width=True)

# =====================================================================
# TAB 2: VÂNĂTORUL DE CHILIPIRURI
# =====================================================================
with tab2:
    st.subheader("🛒 Găsește cele mai subevaluate mașini din piață")

    fil_1, fil_2, fil_3 = st.columns(3)
    with fil_1:
        marca_filtru = st.selectbox("Alege Marca (sau Toate)", ["Toate"] + brand_list, key="hunter_brand")
    with fil_2:
        pret_max_filtru = st.number_input("Buget Maxim (EUR)", min_value=1000, max_value=100000, value=15000, step=1000, key="hunter_price")
    with fil_3:
        km_max_filtru = st.number_input("Rulaj Maxim (km)", min_value=10000, max_value=400000, value=200000, step=10000, key="hunter_km")

    if st.button("Găsește Chilipiruri (Scanare ML)", type="primary"):
        with st.spinner("Modelul ML evaluează anunțurile..."):
            df_scan = df.copy()
            if marca_filtru != "Toate":
                df_scan = df_scan[df_scan['Brand'] == marca_filtru]

            df_scan = df_scan[(df_scan['price'] <= pret_max_filtru) & (df_scan['mileage_km'] <= km_max_filtru)]

            if not df_scan.empty:
                df_scan['pret_estimat_ml'] = model.predict(df_scan[FEATURES])
                df_scan['marja_profit'] = df_scan['pret_estimat_ml'] - df_scan['price']
                df_scan['discount_pct'] = (df_scan['marja_profit'] / df_scan['pret_estimat_ml']) * 100

                # Filtram chilipiruri realiste (marja > MAE si discount <= 45%)
                oferte_bune = df_scan[
                    (df_scan['marja_profit'] > mae) &
                    (df_scan['discount_pct'] <= 45)
                ].copy()

                oferte_bune = oferte_bune.sort_values(by='marja_profit', ascending=False).head(50)

                if not oferte_bune.empty:
                    st.success(f"Am găsit {len(oferte_bune)} oferte subevaluate realist!")
                    coloane_afisare = [c for c in ['title', 'Brand', 'Model', 'Trim', 'year', 'mileage_km', 'price', 'pret_estimat_ml', 'marja_profit', 'url'] if c in oferte_bune.columns]

                    st.dataframe(
                        oferte_bune[coloane_afisare],
                        column_config={
                            "title": "Titlu Anunț",
                            "Brand": "Marcă",
                            "Model": "Model",
                            "Trim": "Echipare",
                            "year": "An",
                            "mileage_km": st.column_config.NumberColumn("Rulaj", format="%d km"),
                            "price": st.column_config.NumberColumn("Preț Cerut", format="%d €"),
                            "pret_estimat_ml": st.column_config.NumberColumn("Valoare ML", format="%d €"),
                            "marja_profit": st.column_config.NumberColumn("Profit Potențial", format="🟢 +%d €"),
                            "url": st.column_config.LinkColumn("Link Anunț", display_text="🔗 Deschide")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info("Nu am găsit mașini subevaluate clar pentru aceste filtre.")
            else:
                st.error("Nu există mașini în baza de date care să corespundă acestor filtre.")

# =====================================================================
# TAB 3: RADAR SCĂDERI DE PREȚ (LIVE PRICE DROPS)
# =====================================================================
with tab3:
    st.subheader("📉 Radar Scăderi de Preț (Urmărește Ieftinirile Recente)")
    st.markdown("Aici vezi în timp real toate mașinile al căror preț a scăzut. Este cel mai rapid mod de a prinde vânzători presați de timp.")

    d_col1, d_col2 = st.columns(2)
    with d_col1:
        zile_drop = st.selectbox("Interval Scădere", [1, 3, 7, 14, 30], index=2, format_func=lambda x: f"Ultimele {x} zile")
    with d_col2:
        reducere_minima = st.number_input("Reducere minimă (EUR)", min_value=50, max_value=5000, value=150, step=50)

    drops_df = get_price_drops(days=zile_drop, min_drop_eur=reducere_minima)

    if not drops_df.empty:
        # Metrici Sumar
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Ieftiniri Găsite", f"{len(drops_df)} mașini")
        m2.metric("Reducere Medie", f"- {drops_df['drop_eur'].mean():,.0f} €")
        max_drop_row = drops_df.iloc[0]
        m3.metric("Cea mai mare reducere", f"- {max_drop_row['drop_eur']:,.0f} €", f"{max_drop_row['drop_pct']}% reducere")

        st.markdown("### 📋 Lista Anunțurilor cu Preț Redus")
        cols_drop_display = [c for c in ['title', 'source', 'year', 'mileage_km', 'old_price', 'new_price', 'drop_eur', 'drop_pct', 'drop_date', 'url'] if c in drops_df.columns]

        st.dataframe(
            drops_df[cols_drop_display],
            column_config={
                "title": "Anunț",
                "source": "Platformă",
                "year": "An",
                "mileage_km": st.column_config.NumberColumn("Rulaj", format="%d km"),
                "old_price": st.column_config.NumberColumn("Preț Vechi", format="%d €"),
                "new_price": st.column_config.NumberColumn("Preț Nou", format="%d €"),
                "drop_eur": st.column_config.NumberColumn("Economie", format="🔻 -%d €"),
                "drop_pct": st.column_config.NumberColumn("Reducere %", format="-%.1f%%"),
                "drop_date": "Data Ieftinirii",
                "url": st.column_config.LinkColumn("Link Direct", display_text="👉 Vezi Anunț")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info(f"Nu s-au înregistrat scăderi de preț mai mari de {reducere_minima} € în ultimele {zile_drop} zile.")