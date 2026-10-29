import os
import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from db_helper import get_price_history, DB_PATH

st.set_page_config(page_title="Analiză Ofertă", layout="wide", page_icon="📊")

st.title("📊 Analiză la Microscop a unei Oferte")
st.markdown(
    "Introdu link-ul unui anunț sau cuvinte din titlu pentru a găsi mașina în baza de date. "
    "Vom afișa **evoluția istorică a prețului**, zilele pe piață și comparația directă cu mașinile similare din România."
)

PARQUET_FILE = 'data/ml_ready_listings.parquet'
EXCEL_FILE = 'data/ml_ready_listings.xlsx'


# --- 1. INCARCAREA DATELOR ---
@st.cache_data
def load_data():
    try:
        if os.path.exists(PARQUET_FILE):
            df = pd.read_parquet(PARQUET_FILE)
        elif os.path.exists(EXCEL_FILE):
            df = pd.read_excel(EXCEL_FILE)
        else:
            return pd.DataFrame()
        return df.dropna(subset=['Brand', 'Model', 'price', 'year', 'mileage_km', 'title', 'url'])
    except Exception as e:
        st.error(f"Eroare la încărcarea datelor: {e}")
        return pd.DataFrame()


df = load_data()

if df.empty:
    st.warning("Baza de date nu este încă disponibilă. Rulează mai întâi pipeline-ul zilnic.")
    st.stop()

# --- 2. MOTORUL DE CĂUTARE ---
st.markdown("### 🔍 Găsește Mașina")
search_query = st.text_input("Introdu URL-ul anunțului SAU cuvinte din titlu (ex: 'bmw seria 3 2019' sau 'audi q5'):")

if search_query:
    query_lower = search_query.lower().strip()

    if "http" in query_lower:
        rezultate = df[df['url'].str.lower() == query_lower]
    else:
        cuvinte_cheie = query_lower.split()
        rezultate = df[df['title'].str.lower().apply(lambda x: all(cuvant in x for cuvant in cuvinte_cheie))]

    if rezultate.empty:
        st.warning("Nu am găsit nicio mașină care să corespundă căutării tale. Încearcă alte cuvinte!")
    else:
        st.success(f"Am găsit {len(rezultate)} anunțuri care se potrivesc!")

        optiuni_masini = rezultate.apply(
            lambda row: f"{row['title']} | {row['year']} | {row['mileage_km']:,.0f} km | {row['price']:,.0f} €", axis=1
        ).tolist()

        masina_selectata_str = st.selectbox("Alege mașina exactă pe care vrei să o analizezi:", optiuni_masini)
        index_selectat = optiuni_masini.index(masina_selectata_str)
        masina_tinta = rezultate.iloc[index_selectat]

        st.divider()

        # --- 3. INFORMAȚII TEMPORALE & ZILE PE PIAȚĂ ---
        cid = masina_tinta.get('car_id', '')
        first_seen = masina_tinta.get('first_seen')
        last_seen = masina_tinta.get('last_seen')

        days_on_market = None
        if pd.notna(first_seen) and pd.notna(last_seen):
            try:
                dt_first = pd.to_datetime(first_seen)
                dt_last = pd.to_datetime(last_seen)
                days_on_market = max(1, (dt_last - dt_first).days)
            except Exception:
                pass

        # Istoric de pret pentru masina
        hist_df = get_price_history(str(cid)) if cid else pd.DataFrame()

        st.markdown(f"## 📋 Detalii Anunț: **{masina_tinta['title']}**")

        meta_c1, meta_c2, meta_c3, meta_c4 = st.columns(4)
        meta_c1.metric("Preț Curent", f"{masina_tinta['price']:,.0f} €")
        meta_c2.metric("Rulaj", f"{masina_tinta['mileage_km']:,.0f} km")
        meta_c3.metric("An Fabricație", f"{masina_tinta['year']}")

        if days_on_market is not None:
            negotiation_tip = "🔥 Nou listat" if days_on_market <= 7 else ("⚖️ Normal" if days_on_market <= 45 else "💰 Potențial Negociere Ridicat")
            meta_c4.metric("Zile pe Piață", f"{days_on_market} zile", negotiation_tip)
        else:
            meta_c4.metric("Platformă", str(masina_tinta.get('source', 'Web')).capitalize())

        st.markdown(f"[🔗 Deschide Anunțul Original Aici]({masina_tinta['url']})")

        # --- GRAFIC EVOLUȚIE PREȚ ÎN TIMP ---
        if not hist_df.empty and len(hist_df) > 1:
            st.markdown("### 📈 Evoluția în Timp a Prețului pentru acest Anunț")
            st.info(f"Acest anunț a înregistrat **{len(hist_df)} modificări de preț** în baza noastră de date.")

            fig_hist = px.line(
                hist_df, x='recorded_at', y='price_eur', markers=True,
                labels={'recorded_at': 'Data Înregistrării', 'price_eur': 'Preț (EUR)'},
                title="Istoric Cronologic de Preț"
            )
            fig_hist.update_traces(line=dict(color='#00CC96', width=3), marker=dict(size=10, color='red'))
            st.plotly_chart(fig_hist, use_container_width=True)
        elif not hist_df.empty:
            st.caption(f"ℹ️ Prețul a rămas stabil la {masina_tinta['price']:,.0f} € de la data primei înregistrări ({first_seen or 'recent'}).")

        st.markdown("---")

        # --- 4. EXTRAGERE PEERS (MASINI SIMILARE PENTRU PIATA) ---
        brand_tinta = masina_tinta['Brand']
        model_tinta = masina_tinta['Model']
        an_tinta = masina_tinta['year']
        pret_tinta = masina_tinta['price']
        km_tinta = masina_tinta['mileage_km']

        df_piata = df[(df['Brand'] == brand_tinta) & (df['Model'] == model_tinta)]

        st.markdown(f"## 🎯 Analiza Pieței pentru {brand_tinta} {model_tinta}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Preț Oferta Ta", f"{pret_tinta:,.0f} €")
        c2.metric("Preț Mediu Piață", f"{df_piata['price'].mean():,.0f} €",
                  f"{pret_tinta - df_piata['price'].mean():,.0f} € față de medie",
                  delta_color="inverse")
        c3.metric("Rulaj Oferta Ta", f"{km_tinta:,.0f} km")
        c4.metric("Rulaj Mediu Piață", f"{df_piata['mileage_km'].mean():,.0f} km")

        if len(df_piata) > 3:
            df_piata_vizual = df_piata[df_piata['mileage_km'] > 1000].copy()

            # --- GRAFIC 1: Pret vs Kilometraj ---
            st.markdown("### 1. Poziționarea Calitate/Preț (Preț vs. Kilometri)")

            col_opt_1, col_opt_2 = st.columns([1, 3])
            with col_opt_1:
                color_option = st.radio("Colorează punctele după:", ["An Fabricație (year)", "Echipare (Trim)"])
            with col_opt_2:
                st.info("💡 **Sfat:** Linia roșie punctată reprezintă 'Prețul Corect' matematic. Ce este sub linie reprezintă o afacere bună!")

            culoare_grafic = 'year' if "An" in color_option else 'Trim'

            fig1 = px.scatter(df_piata_vizual, x='mileage_km', y='price', color=culoare_grafic,
                              hover_data=['title', 'price', 'mileage_km', 'year', 'Trim'],
                              trendline="ols", trendline_color_override="red",
                              labels={'mileage_km': 'Kilometraj (km)', 'price': 'Preț Cerut (€)', 'year': 'An', 'Trim': 'Echipare'},
                              opacity=0.7, color_continuous_scale='Viridis')

            fig1.update_traces(line=dict(dash="dash"), selector=dict(mode="lines"))
            fig1.add_trace(go.Scatter(
                x=[km_tinta], y=[pret_tinta],
                mode='markers', marker=dict(color='red', symbol='star', size=25, line=dict(width=2, color='black')),
                name='Mașina Analizată',
                hovertemplate=f"<b>MAȘINA TA</b><br>Preț: {pret_tinta:,.0f} €<br>Km: {km_tinta:,.0f}<extra></extra>"
            ))
            st.plotly_chart(fig1, use_container_width=True)

            # --- TABELUL INTERACTIV PENTRU LINK-URI ---
            with st.expander("🔗 Vezi lista completă a mașinilor din grafic"):
                st.dataframe(
                    df_piata_vizual[['title', 'year', 'mileage_km', 'price', 'Trim', 'url']].sort_values('price'),
                    column_config={
                        "title": "Titlu Anunț",
                        "year": "An",
                        "mileage_km": st.column_config.NumberColumn("Rulaj", format="%d km"),
                        "price": st.column_config.NumberColumn("Preț", format="%d €"),
                        "Trim": "Echipare",
                        "url": st.column_config.LinkColumn("Link Anunț", display_text="👉 Deschide Site-ul")
                    },
                    hide_index=True, use_container_width=True
                )

            # --- SISTEMUL DE RECOMANDARI INTELIGENTE ---
            st.markdown("### 🤖 Alternative Recomandate din Piață")
            alternative = df_piata_vizual[
                (df_piata_vizual['price'] < pret_tinta) &
                (df_piata_vizual['mileage_km'] < km_tinta) &
                (df_piata_vizual['url'] != masina_tinta['url'])
            ]

            if not alternative.empty:
                st.success(f"Am găsit **{len(alternative)}** oferte pe piață care par mai bune decât cea selectată de tine (mai ieftine + rulaj mai mic). Iată Top 3:")
                top_3_alternative = alternative.sort_values(by=['price', 'mileage_km']).head(3)

                c_alt1, c_alt2, c_alt3 = st.columns(3)
                cols_alt = [c_alt1, c_alt2, c_alt3]

                for idx, row in enumerate(top_3_alternative.itertuples()):
                    with cols_alt[idx]:
                        st.info(f"**{row.title}**")
                        st.write(f"💰 {row.price:,.0f} € (Economisești {pret_tinta - row.price:,.0f} €)")
                        st.write(f"🛣️ {row.mileage_km:,.0f} km (Cu {km_tinta - row.mileage_km:,.0f} km mai puțin)")
                        st.write(f"✨ Echipare: {row.Trim}")
                        st.markdown(f"[Vezi Anunțul Aici]({row.url})")
            else:
                st.warning("Bravo! Nu am găsit în piață nicio altă mașină de acest tip care să fie ȘI mai ieftină ȘI cu mai puțini kilometri. Pare o alegere solidă.")

            col_graf_A, col_graf_B = st.columns(2)
            with col_graf_A:
                st.markdown("### 2. Distribuția Prețurilor")
                fig2 = px.histogram(df_piata_vizual, x='price', nbins=30,
                                    labels={'price': 'Preț (€)'},
                                    color_discrete_sequence=['#636EFA'])
                fig2.add_vline(x=pret_tinta, line_width=4, line_dash="dash", line_color="red",
                               annotation_text="Prețul Tău", annotation_position="top right")
                st.plotly_chart(fig2, use_container_width=True)

            with col_graf_B:
                st.markdown("### 3. Deprecierea Modelului")
                df_piata_sortat = df_piata_vizual.sort_values(by='year', ascending=True)
                fig3 = px.box(df_piata_sortat, x='year', y='price',
                              labels={'year': 'An Fabricație', 'price': 'Preț (€)'},
                              color_discrete_sequence=['#00CC96'])
                fig3.add_trace(go.Scatter(
                    x=[an_tinta], y=[pret_tinta],
                    mode='markers', marker=dict(color='red', symbol='star', size=20, line=dict(width=1, color='black')),
                    name='Mașina Ta'
                ))
                fig3.update_xaxes(type='category')
                st.plotly_chart(fig3, use_container_width=True)