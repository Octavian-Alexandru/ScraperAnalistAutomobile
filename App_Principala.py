# FILE: App_Principala.py
"""
Dashboard Streamlit Comercial Auto (Radar Comercial Auto).
Include:
- Analiză detaliată per ofertă cu evaluare ML (XGBoost / RandomForest)
- Estimator costuri recondiționare (piese + manoperă detaliate)
- Profit Net Real după cheltuieli și marjă de siguranță
- Deal Score compozit (0-100) și recomandare de ofertă la negociere
- Vânător de chilipiruri sortat după Deal Score și Profit Net
- Radar scăderi de preț (Price Drops Live)
- Analiză Arbitraj Piața Germană (Mobile.de delta)
"""

import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import joblib

from db_helper import get_price_drops, get_db_stats, DB_PATH
from maintenance_estimator import calculate_net_profit, estimate_maintenance_cost
from deal_scorer import compute_deal_score
from cross_border_arbitrage import analyze_cross_border_deal
from liquidity_tracker import get_model_liquidity

st.set_page_config(page_title="Radar Comercial Auto", layout="wide", page_icon="💸")

st.title("💸 Radar Comercial Auto (Powered by ML)")
st.markdown(
    "Acest instrument analizează ofertele auto din România, calculează **costurile reale de recondiționare**, "
    "atribuie un **Deal Score (0-100)** și identifică oportunități de **arbitraj și flipping** profitabil."
)

PARQUET_FILE = 'data/ml_ready_listings.parquet'
EXCEL_FILE = 'data/ml_ready_listings.xlsx'
MODEL_XGB_FILE = 'models/price_model_xgboost.joblib'
MODEL_RF_FILE = 'models/price_model.joblib'
FEATURES = ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size']


@st.cache_data
def load_and_prepare_data():
    df = None
    if os.path.exists(PARQUET_FILE):
        try:
            df = pd.read_parquet(PARQUET_FILE)
        except Exception:
            pass

    if df is None or df.empty:
        if os.path.exists(EXCEL_FILE):
            try:
                df = pd.read_excel(EXCEL_FILE)
            except Exception:
                pass

    if df is None or df.empty:
        if os.path.exists(DB_PATH):
            try:
                from db_helper import get_active_listings_df
                df = get_active_listings_df()
                if not df.empty and 'price' not in df.columns and 'price_eur' in df.columns:
                    df['price'] = df['price_eur']
            except Exception:
                pass

    if df is None or df.empty:
        st.error("⚠️ Nu s-a găsit dataset-ul pregătit. Rulează mai întâi pipeline-ul zilnic.")
        st.stop()

    if 'Trim' not in df.columns:
        df['Trim'] = 'Standard'
    df['Trim'] = df['Trim'].fillna('Standard')

    if 'price' not in df.columns and 'price_eur' in df.columns:
        df['price'] = df['price_eur']

    required_cols = ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size', 'price']
    df = df.dropna(subset=[c for c in required_cols if c in df.columns])
    return df.reset_index(drop=True)


@st.cache_resource
def load_trained_model(dataframe):
    # Prioritizăm modelul nou XGBoost
    for path in [MODEL_XGB_FILE, MODEL_RF_FILE]:
        if os.path.exists(path):
            try:
                payload = joblib.load(path)
                m_type = payload.get('model_type', 'RandomForest')
                return payload['model'], payload['mae'], payload['r2'], payload.get('trained_at', 'GitHub Actions'), payload.get('features', FEATURES), m_type
            except Exception:
                pass

    # Fallback local
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
        ('regressor', RandomForestRegressor(n_estimators=80, max_depth=14, min_samples_split=6, random_state=42, n_jobs=-1))
    ])
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    return model, mae, r2, "Antrenat Local (Fallback)", FEATURES, "RandomForest Fallback"


df = load_and_prepare_data()
model, mae, r2, model_date, active_features, model_type = load_trained_model(df)

# Header Metrics
with st.expander("ℹ️ Detalii Tehnice ale Bazei de Date & Modelului ML", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Date Antrenare Curate", f"{len(df):,} mașini")
    c2.metric("Modele Auto Analizate", f"{df['Model'].nunique()} modele")
    c3.metric("Acuratețe (R² pe Test)", f"{r2 * 100:.1f}%", f"{model_type}")
    c4.metric("Marjă Eroare (MAE)", f"± {mae:,.0f} €")
    st.caption(f"🤖 **Motor ML activ:** {model_type} | Antrenat la: {model_date}")

st.divider()

tab1, tab2, tab3 = st.tabs([
    "🔍 Analiză Anunț Specific & Deal Score",
    "💎 Vânător de Chilipiruri (Clasament Profit Net)",
    "📉 Radar Scăderi de Preț (Live Price Drops)"
])

# =====================================================================
# TAB 1: ANALIZA MANUALĂ
# =====================================================================
with tab1:
    st.subheader("Evaluează un Anunț / Calculează Profitul Net & Deal Score")

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
        selected_seller = st.selectbox("8. Tip Vânzător:", ["Particular (Proprietar)", "Dealer / Parc Auto"])

    if st.button("Analizează Oferta Completă", type="primary", use_container_width=True):
        input_data = pd.DataFrame([{
            'Brand': selected_brand,
            'Model': selected_model,
            'Trim': selected_trim,
            'year': selected_year,
            'mileage_km': selected_km,
            'fuel_type': selected_fuel,
            'engine_size': selected_engine,
            'car_age': 2026 - selected_year,
            'km_per_year': round(selected_km / max(1, 2026 - selected_year)),
            'is_premium_brand': 1 if selected_brand.lower() in ['bmw', 'audi', 'mercedes-benz', 'porsche'] else 0,
            'body_type': 'Sedan',
            'transmission': 'Manual',
            'euro_norm': 'Euro 6'
        }])

        avail_cols = [c for c in active_features if c in input_data.columns]
        predicted_price = float(model.predict(input_data[avail_cols])[0])

        # Calcul financiar complet (Profit Net după piese & manoperă)
        deal_info = compute_deal_score(
            predicted_market_price=predicted_price,
            asked_price=pret_cerut,
            brand=selected_brand,
            model=selected_model,
            year=selected_year,
            mileage_km=selected_km,
            fuel_type=selected_fuel,
            seller_type=selected_seller
        )

        fin = deal_info['financials']
        liq = deal_info['liquidity']

        st.markdown("---")
        st.subheader("📊 Rezultatul Analizei Financiare & Tehnice")

        # 5 Metrici Cheie
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Valoare Reală ML", f"{predicted_price:,.0f} €")
        r2.metric("Preț Vânzător", f"{pret_cerut:,.0f} €")
        r3.metric("Cost Recondiționare", f"{fin['maintenance_cost']:,.0f} €", f"Piese + Manoperă")
        r4.metric("Profit NET Real", f"{fin['net_profit_margin']:+,.0f} €", f"ROI: {fin['net_roi_pct']}%")
        r5.metric("Deal Score", f"{deal_info['deal_score']} / 100", deal_info['badge'])

        st.info(f"💡 **Recomandare de Negociere:** {deal_info['recommendation']} | **Preț Țintă de Ofertă:** **{deal_info['target_buy_offer_eur']:,.0f} €**")

        # Expander pentru defalcarea costurilor de recondiționare
        with st.expander("🔧 Defalcare Piese & Manoperă Recondiționare", expanded=True):
            maint_details = fin['maintenance_details']['breakdown']
            df_maint = pd.DataFrame([
                {
                    "Componentă": k.replace("_", " ").title(),
                    "Cost Piese (EUR)": f"{v['piese']} €",
                    "Manoperă Service (EUR)": f"{v['manopera']} €",
                    "Total Estimativ": f"{v['total']} €"
                }
                for k, v in maint_details.items()
            ])
            st.dataframe(df_maint, hide_index=True, use_container_width=True)
            st.caption(f"Include 10% rezervă pentru cheltuieli neprevăzute ({fin['maintenance_details']['contingency_buffer']} €).")

        # Analiză Arbitraj vs Germania
        with st.expander("🚢 Comparație Arbitraj cu Piața Germană (Mobile.de)", expanded=False):
            cb = analyze_cross_border_deal(
                romanian_price_eur=pret_cerut,
                brand=selected_brand,
                model=selected_model,
                year=selected_year,
                mileage_km=selected_km,
                fuel_type=selected_fuel
            )
            c_de1, c_de2, c_de3 = st.columns(3)
            c_de1.metric("Preț Mediu Germania", f"{cb['german_price_eur']:,.0f} €")
            c_de2.metric("Diferență (Delta RO vs DE)", f"{cb['delta_eur']:+,.0f} €", f"{cb['delta_pct']:+.1f}%")
            c_de3.metric("Cost Estimativ Import", f"{cb['import_overhead_eur']:,.0f} €", "Transport + RAR + Acte")
            st.write(cb['verdict'])

        # Grafic de depreciere simulat
        st.markdown("### 📉 Curba de Depreciere a acestui Model")
        sim_years = list(range(2014, 2026))
        sim_data = []
        for y in sim_years:
            sim_km = max(5000, selected_km + ((selected_year - y) * 15000))
            sim_data.append({
                'Brand': selected_brand, 'Model': selected_model, 'Trim': selected_trim,
                'year': y, 'mileage_km': sim_km, 'fuel_type': selected_fuel, 'engine_size': selected_engine,
                'car_age': 2026 - y, 'km_per_year': round(sim_km / max(1, 2026 - y)),
                'is_premium_brand': 1 if selected_brand.lower() in ['bmw', 'audi', 'mercedes-benz', 'porsche'] else 0,
                'body_type': 'Sedan', 'transmission': 'Manual', 'euro_norm': 'Euro 6'
            })

        df_sim = pd.DataFrame(sim_data)
        avail_sim = [c for c in active_features if c in df_sim.columns]
        df_sim['Estimare_Pret'] = model.predict(df_sim[avail_sim])

        fig = px.line(
            df_sim, x='year', y='Estimare_Pret', markers=True,
            labels={'year': 'An Fabricație', 'Estimare_Pret': 'Preț Estimat (EUR)'},
            title=f"Evoluția Prețului pentru {selected_brand} {selected_model} ({selected_trim})"
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
    st.subheader("🛒 Găsește cele mai rentabile oportunități (Clasate după Profit Net & Deal Score)")

    fil_1, fil_2, fil_3 = st.columns(3)
    with fil_1:
        marca_filtru = st.selectbox("Alege Marca (sau Toate)", ["Toate"] + brand_list, key="hunter_brand")
    with fil_2:
        pret_max_filtru = st.number_input("Buget Maxim (EUR)", min_value=1000, max_value=100000, value=18000, step=1000, key="hunter_price")
    with fil_3:
        km_max_filtru = st.number_input("Rulaj Maxim (km)", min_value=10000, max_value=400000, value=200000, step=10000, key="hunter_km")

    if st.button("Găsește Chilipiruri (Scanare ML Avansată)", type="primary"):
        with st.spinner("Modelul ML evaluează oportunitățile și calculează costurile de recondiționare..."):
            df_scan = df.copy()
            if marca_filtru != "Toate":
                df_scan = df_scan[df_scan['Brand'] == marca_filtru]

            df_scan = df_scan[(df_scan['price'] <= pret_max_filtru) & (df_scan['mileage_km'] <= km_max_filtru)]

            if not df_scan.empty:
                # Feature engineering pentru modelele compatibile
                df_scan['car_age'] = (2026 - df_scan['year']).clip(lower=1)
                df_scan['km_per_year'] = (df_scan['mileage_km'] / df_scan['car_age']).round(0)
                df_scan['is_premium_brand'] = df_scan['Brand'].str.lower().apply(lambda b: 1 if b in ['bmw', 'audi', 'mercedes-benz', 'porsche'] else 0)
                if 'body_type' not in df_scan.columns: df_scan['body_type'] = 'Sedan'
                if 'transmission' not in df_scan.columns: df_scan['transmission'] = 'Manual'
                if 'euro_norm' not in df_scan.columns: df_scan['euro_norm'] = 'Euro 6'

                avail_cols = [c for c in active_features if c in df_scan.columns]
                df_scan['pret_estimat_ml'] = model.predict(df_scan[avail_cols])
                df_scan['marja_profit'] = df_scan['pret_estimat_ml'] - df_scan['price']
                df_scan['discount_pct'] = (df_scan['marja_profit'] / df_scan['pret_estimat_ml']) * 100

                # Filtram chilipiruri realiste
                oferte_bune = df_scan[
                    (df_scan['marja_profit'] > mae) &
                    (df_scan['discount_pct'] <= 50)
                ].copy().head(30)

                if not oferte_bune.empty:
                    # Calculăm Deal Score și cost de recondiționare
                    enhanced_list = []
                    for _, r in oferte_bune.iterrows():
                        ds = compute_deal_score(
                            predicted_market_price=r['pret_estimat_ml'],
                            asked_price=r['price'],
                            brand=r['Brand'],
                            model=r['Model'],
                            year=int(r['year']),
                            mileage_km=int(r['mileage_km']),
                            fuel_type=r.get('fuel_type'),
                            seller_type=r.get('seller_type')
                        )
                        enhanced_list.append({
                            "title": r.get('title', f"{r['Brand']} {r['Model']}"),
                            "Brand": r['Brand'],
                            "Model": r['Model'],
                            "year": int(r['year']),
                            "mileage_km": int(r['mileage_km']),
                            "price": r['price'],
                            "pret_estimat_ml": r['pret_estimat_ml'],
                            "cost_reconditionare": ds['financials']['maintenance_cost'],
                            "profit_net": ds['financials']['net_profit_margin'],
                            "roi_pct": ds['financials']['net_roi_pct'],
                            "deal_score": ds['deal_score'],
                            "badge": ds['badge'],
                            "url": r.get('url', '')
                        })

                    df_results = pd.DataFrame(enhanced_list).sort_values(by='deal_score', ascending=False)

                    st.success(f"Am găsit {len(df_results)} oferte rentabile clasificate după Deal Score!")

                    st.dataframe(
                        df_results[[
                            'title', 'Brand', 'Model', 'year', 'mileage_km', 'price',
                            'pret_estimat_ml', 'cost_reconditionare', 'profit_net',
                            'deal_score', 'badge', 'url'
                        ]],
                        column_config={
                            "title": "Titlu Anunț",
                            "Brand": "Marcă",
                            "Model": "Model",
                            "year": "An",
                            "mileage_km": st.column_config.NumberColumn("Rulaj", format="%d km"),
                            "price": st.column_config.NumberColumn("Preț Cerut", format="%d €"),
                            "pret_estimat_ml": st.column_config.NumberColumn("Valoare ML", format="%d €"),
                            "cost_reconditionare": st.column_config.NumberColumn("Recondiționare", format="🔧 %d €"),
                            "profit_net": st.column_config.NumberColumn("Profit NET", format="🟢 +%d €"),
                            "deal_score": st.column_config.ProgressColumn("Deal Score", min_value=0, max_value=100, format="%d/100"),
                            "badge": "Verdict",
                            "url": st.column_config.LinkColumn("Link", display_text="🔗 Deschide")
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