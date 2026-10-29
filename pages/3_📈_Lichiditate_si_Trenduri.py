import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from db_helper import DB_PATH
from liquidity_tracker import get_top_liquid_models, get_model_liquidity
from price_trend_analyzer import analyze_model_price_trend, get_market_wide_trends

st.set_page_config(page_title="Lichiditate & Trenduri Preț", layout="wide", page_icon="📈")

st.title("📈 Lichiditate & Trenduri de Preț Auto")
st.markdown(
    "Află **cât de repede se vinde fiecare model** (rotația stocului / Days-to-Sell) "
    "și anticipează **direcția prețurilor** pentru a nu bloca capital în mașini greu vandabile."
)

PARQUET_FILE = 'data/ml_ready_listings.parquet'

@st.cache_data
def load_available_models():
    if os.path.exists(PARQUET_FILE):
        try:
            df = pd.read_parquet(PARQUET_FILE)
            brands = sorted(df['Brand'].dropna().unique().tolist())
            return df, brands
        except Exception:
            pass
    return pd.DataFrame(), ["Volkswagen", "BMW", "Audi", "Skoda", "Dacia", "Ford", "Renault"]

df_cars, brands_list = load_available_models()

tab_liq, tab_trend = st.tabs([
    "🚀 Tracker Lichiditate (Days-to-Sell)",
    "📊 Trenduri de Preț & Prognoză Time-Series"
])

# =====================================================================
# TAB 1: TRACKER LICHIDITATE
# =====================================================================
with tab_liq:
    st.subheader("⚡ Cât de repede se vând mașinile pe piața din România?")
    st.markdown(
        "> **Regula de Aur în Flipping:** *O marjă de 1.500 € pe o mașină care se vinde în 14 zile "
        "bate o marjă de 3.000 € pe o mașină care stă 90 de zile pe piață (capital blocat = profit pierdut).*"
    )

    top_liquid_df = get_top_liquid_models(limit=25)

    if not top_liquid_df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Cele mai lichide modele", f"{len(top_liquid_df)} segmente")
        c2.metric("Timp median de vânzare (Top)", f"{top_liquid_df['median_days_to_sell'].min():.0f} zile", "Rotație fulger")
        c3.metric("Scor Mediu Lichiditate", f"{top_liquid_df['liquidity_score'].mean():.0f} / 100")

        st.markdown("### 📋 Clasamentul Modelelor după Viteza de Vânzare")

        filter_tier = st.multiselect(
            "Filtrează după Categoria de Rotație a Capitalului:",
            options=["Ultra-Lichid", "Lichid", "Moderat", "Greu Vandabil"],
            default=["Ultra-Lichid", "Lichid"]
        )

        display_liq = top_liquid_df[top_liquid_df['liquidity_tier'].isin(filter_tier)].copy()

        st.dataframe(
            display_liq,
            column_config={
                "brand": "Marcă",
                "model": "Model",
                "year_range": "Interval Ani",
                "median_days_to_sell": st.column_config.NumberColumn("Zile Mediane Vânzare", format="%.0f zile"),
                "active_listings_count": st.column_config.NumberColumn("Anunțuri Active", format="%d"),
                "avg_price_eur": st.column_config.NumberColumn("Preț Mediu", format="%d €"),
                "liquidity_tier": "Categorie Rotație",
                "liquidity_score": st.column_config.ProgressColumn("Scor Lichiditate", min_value=0, max_value=100, format="%d / 100")
            },
            hide_index=True,
            use_container_width=True
        )

        # Grafic comparativ
        fig_liq = px.bar(
            display_liq.head(15),
            x='model', y='liquidity_score', color='brand',
            title="Top 15 Modele cu Cerere Maximă în România",
            labels={'model': 'Model Auto', 'liquidity_score': 'Scor Lichiditate (0-100)'}
        )
        st.plotly_chart(fig_liq, use_container_width=True)
    else:
        st.info("Datele de lichiditate sunt în curs de calcul. Rulează pipeline-ul zilnic.")

# =====================================================================
# TAB 2: TRENDURI DE PREȚ & PROGNOZĂ
# =====================================================================
with tab_trend:
    st.subheader("📉 Analiză Istorică a Prețurilor & Direcție Piață")
    st.markdown("Selectează marca și modelul pentru a vedea evoluția prețului median și prognoza la 30/60 de zile.")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        sel_brand = st.selectbox("Alege Marca:", brands_list, index=brands_list.index("Volkswagen") if "Volkswagen" in brands_list else 0)
    with col_t2:
        if not df_cars.empty:
            models_for_brand = sorted(df_cars[df_cars['Brand'] == sel_brand]['Model'].dropna().unique().tolist())
        else:
            models_for_brand = ["Golf", "Passat", "Tiguan", "Touareg"]
        sel_model = st.selectbox("Alege Modelul:", models_for_brand)

    with st.spinner("Calculăm regresia pe istoricul de preț..."):
        trend = analyze_model_price_trend(sel_brand, sel_model)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Preț Curent Mediu", f"{trend['avg_current_price']:,.0f} €" if trend['avg_current_price'] else "N/A")
    m2.metric("Direcție Trend", trend['trend_direction'], f"{trend['monthly_change_pct']:+.1f}% / lună")
    m3.metric("Prognoză peste 30 zile", f"{trend['forecast_30d']:,.0f} €" if trend['forecast_30d'] else "N/A")
    m4.metric("Prognoză peste 60 zile", f"{trend['forecast_60d']:,.0f} €" if trend['forecast_60d'] else "N/A")

    st.info(trend['status_text'])

    if trend.get('daily_data') and len(trend['daily_data']) >= 2:
        df_plot = pd.DataFrame(trend['daily_data'])
        fig_trend = px.line(
            df_plot, x='date', y='price_eur', markers=True,
            title=f"Evoluția Prețului Istoric pentru {sel_brand} {sel_model}",
            labels={'date': 'Data Înregistrării', 'price_eur': 'Preț Mediu (EUR)'}
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    st.divider()
    st.markdown("### 🌐 Sinteză Trenduri Top 10 Modele din România")
    market_summary = get_market_wide_trends()
    st.dataframe(market_summary, hide_index=True, use_container_width=True)
