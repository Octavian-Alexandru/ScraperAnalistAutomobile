import os
import streamlit as st
import pandas as pd
from watchlist_manager import add_watchlist_rule, get_all_watchlists
from cross_platform_matcher import find_cross_platform_duplicates

st.set_page_config(page_title="Watchlist & Arbitraj Cross-Platform", layout="wide", page_icon="🎯")

st.title("🎯 Watchlist Personalizat & Arbitraj Cross-Platform")
st.markdown(
    "Setează **alerte personalizate** pentru modelele dorite și descoperă instant mașinile listate pe platforme multiple cu **diferențe mari de preț**."
)

tab_cross, tab_watch, tab_report = st.tabs([
    "⚡ Arbitraj Cross-Platform (Same Car, Different Price)",
    "🔔 Manager Watchlist (Alerte Personalizate)",
    "📑 Raport Zilnic de Piață (Market Intelligence)"
])

# =====================================================================
# TAB 1: ARBITRAJ CROSS-PLATFORM
# =====================================================================
with tab_cross:
    st.subheader("🔍 Aceeași mașină listată la prețuri diferite pe site-uri concurente")
    st.markdown(
        "Algoritmul de fuzzy matching scanează simultan Autovit, OLX, PlusAuto, BestAuto, CautiMasina și CarZZ "
        "pentru a găsi autoturisme identice unde vânzătorul a postat un preț mai mic pe o altă platformă."
    )

    min_diff = st.slider("Diferență minimă de preț (EUR):", min_value=200, max_value=5000, value=500, step=100)

    with st.spinner("Căutăm mașini identice pe platforme diferite..."):
        duplicates = find_cross_platform_duplicates(min_price_diff_eur=float(min_diff))

    if not duplicates.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Mașini Identice Găsite", f"{len(duplicates)} oferte")
        max_diff_val = duplicates['price_diff_eur'].max()
        c2.metric("Cea mai mare discrepanță", f"+ {max_diff_val:,.0f} €")
        c3.metric("Economie Medie Posibilă", f"+ {duplicates['price_diff_eur'].mean():,.0f} €")

        st.markdown("### 📋 Oportunități Active de Arbitraj Cross-Platform")

        cols_display = [
            'title', 'cheapest_source', 'cheapest_price_eur',
            'expensive_source', 'expensive_price_eur', 'price_diff_eur', 'savings_pct',
            'cheapest_url', 'expensive_url'
        ]

        st.dataframe(
            duplicates[cols_display],
            column_config={
                "title": "Model Autoturism",
                "cheapest_source": "Platformă Ieftină",
                "cheapest_price_eur": st.column_config.NumberColumn("Preț Minim", format="%d €"),
                "expensive_source": "Platformă Scumpă",
                "expensive_price_eur": st.column_config.NumberColumn("Preț Maxim", format="%d €"),
                "price_diff_eur": st.column_config.NumberColumn("Economie Directă", format="🟢 +%d €"),
                "savings_pct": st.column_config.NumberColumn("Reducere %", format="-%.1f%%"),
                "cheapest_url": st.column_config.LinkColumn("Link Preț Minim", display_text="🛒 Cumpără Ieftin"),
                "expensive_url": st.column_config.LinkColumn("Link Preț Mare", display_text="📈 Vezi Ofertă Scumpă")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info(f"Nu s-au găsit discrepanțe de preț mai mari de {min_diff} € în această selecție.")

# =====================================================================
# TAB 2: MANAGER WATCHLIST
# =====================================================================
with tab_watch:
    st.subheader("🔔 Creează o Alertă Personalizată de Achiziție")
    st.markdown("Vei fi notificat automat de către pipeline când apare o mașină care respectă cerințele tale exacte.")

    with st.form("form_add_watchlist"):
        w_c1, w_c2, w_c3 = st.columns(3)

        with w_c1:
            u_name = st.text_input("Numele tău / Dealer:", value="Alexandru")
            w_brand = st.text_input("Marca dorită (sau 'Toate'):", value="BMW")
            w_model = st.text_input("Modelul (sau 'Toate'):", value="X3")

        with w_c2:
            min_y = st.number_input("An fabricație minim:", min_value=2010, max_value=2026, value=2018)
            max_y = st.number_input("An fabricație maxim:", min_value=2010, max_value=2026, value=2024)
            w_fuel = st.selectbox("Combustibil:", ["Toate", "Diesel", "Benzina", "Hibrid", "Electric"])

        with w_c3:
            max_p = st.number_input("Buget Maxim (EUR):", min_value=1000, max_value=100000, value=22000, step=1000)
            max_k = st.number_input("Kilometraj Maxim:", min_value=10000, max_value=400000, value=160000, step=10000)
            min_score = st.slider("Deal Score Minim (0-100):", min_value=50, max_value=95, value=75)

        w_contact = st.text_input("Canal Notificare / Contact (Telegram @handle, Webhook sau Email):", value="@dealeralex")

        submitted = st.form_submit_button("➕ Salvează Regula în Watchlist", type="primary")
        if submitted:
            rule_id = add_watchlist_rule(
                user_name=u_name,
                brand=w_brand if w_brand != 'Toate' else None,
                model=w_model if w_model != 'Toate' else None,
                min_year=int(min_y),
                max_year=int(max_y),
                max_price_eur=float(max_p),
                max_mileage_km=int(max_k),
                fuel_type=w_fuel if w_fuel != 'Toate' else None,
                min_deal_score=int(min_score),
                contact_channel="telegram",
                contact_target=w_contact
            )
            st.success(f"Regula de alertă a fost adăugată cu succes! (ID: {rule_id})")

    st.divider()
    st.markdown("### 📋 Alerte Active în Sistem")
    watchlists_list = get_all_watchlists(active_only=True)
    if watchlists_list:
        df_w = pd.DataFrame(watchlists_list)
        st.dataframe(
            df_w[['id', 'user_name', 'brand', 'model', 'min_year', 'max_year', 'max_price_eur', 'max_mileage_km', 'min_deal_score', 'contact_target', 'created_at']],
            column_config={
                "id": "ID",
                "user_name": "Utilizator",
                "brand": "Marcă",
                "model": "Model",
                "min_year": "An Min",
                "max_year": "An Max",
                "max_price_eur": st.column_config.NumberColumn("Buget Max", format="%d €"),
                "max_mileage_km": st.column_config.NumberColumn("Km Max", format="%d km"),
                "min_deal_score": "Scor Min",
                "contact_target": "Contact",
                "created_at": "Data Creării"
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("Nu există alerte active configurate.")

# =====================================================================
# TAB 3: RAPORT ZILNIC DE PIAȚĂ
# =====================================================================
with tab_report:
    st.subheader("📑 Raportul Oficial de Piață (Market Intelligence)")
    st.markdown("Vizualizează și descarcă ultimul raport generat automat de pipeline.")

    report_dir = "results"
    report_files = [f for f in os.listdir(report_dir) if f.startswith("daily_market_report_") and f.endswith(".md")] if os.path.exists(report_dir) else []

    if report_files:
        report_files.sort(reverse=True)
        sel_rep = st.selectbox("Alege Raportul:", report_files)
        rep_full_path = os.path.join(report_dir, sel_rep)

        with open(rep_full_path, "r", encoding="utf-8") as f:
            content = f.read()

        st.download_button(
            label="📥 Descarcă Raportul (Markdown)",
            data=content,
            file_name=sel_rep,
            mime="text/markdown"
        )

        st.markdown(content)
    else:
        st.info("Nu s-au găsit rapoarte generate încă. Rulează pipeline-ul zilnic.")
