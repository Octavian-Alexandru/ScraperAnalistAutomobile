# FILE: pages/5_🚢_Import_si_Arbitraj_Vest.py
"""
Pagina de Analiză și Simulator pentru Import Auto și Arbitraj Cross-Border.
Permite utilizatorului să:
1. Exploreze cele mai profitabile oportunități de import culese live din Germania, Austria, Olanda și Belgia
2. Simuleze negru pe alb costul de oportunitate și cheltuielile reale de import (Pe roți vs Platformă)
3. Calculeze avantajul fiscal de achiziție NETTO (fără TVA) pentru firme din România (SRL cu VIES)
4. Genereze scripturi și mesaje profesionale de negociere în limba Germană și Engleză
5. Ajusteze dinamic variabilele și tarifele de transport (combustibil, trailer, RAR)
"""

import os
import sys
import datetime
import pandas as pd
import streamlit as st

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

st.set_page_config(
    page_title="Import & Arbitraj Vest | Radar Auto",
    page_icon="🚢",
    layout="wide"
)

from db_helper import DB_PATH, get_connection
from import_cost_calculator import (
    calculate_import_costs,
    load_import_config,
    save_import_config,
    DEFAULT_DISTANCES_KM
)
from cross_border_arbitrage import find_top_import_arbitrage_deals, analyze_cross_border_deal
from negotiation_generator import (
    generate_german_negotiation_message,
    generate_english_negotiation_message,
    calculate_target_negotiation_price
)

st.title("🚢 Radar Import Auto & Arbitraj Cross-Border")
st.markdown(
    "Analizează discrepanțele de preț dintre piețele din **Europa de Vest (Germania, Austria, Olanda, Belgia)** "
    "și piața din România. Calculează costul de oportunitate **negru pe alb** și profitul net real după transport și înmatriculare."
)

tab1, tab2, tab3 = st.tabs([
    "🔥 Top Oportunități Import (Live Feed)",
    "🧮 Simulator Costuri & Oportunitate (Negru pe Alb)",
    "⚙️ Configurator Variabile & Tarife"
])


# ==============================================================================
# TAB 1: TOP OPORTUNITĂȚI DE IMPORT (LIVE FEED)
# ==============================================================================
with tab1:
    st.subheader("📊 Cele Mai Profitabile Mașini de Importat în România")
    st.caption("Filtrate și clasate automat după marja netă de profit (după scăderea cheltuielilor de transport pe trailer și taxe RAR).")

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        regim_cumparator = st.selectbox(
            "Regim Fiscal Cumpărător:",
            ["Persoană Fizică (Preț Brut)", "SRL Plătitor TVA VIES (Achiziție Netto -19/20%)"],
            index=0
        )
    with col_f2:
        tara_filtru = st.selectbox(
            "Filtrare Țară Origine:",
            ["Toate Țările", "Austria (AT)", "Germania (DE)", "Olanda (NL)", "Belgia (BE)"]
        )
    with col_f3:
        min_profit_filter = st.slider("Profit Net Minim Dorit (€):", min_value=500, max_value=8000, value=1500, step=250)
    with col_f4:
        min_roi_filter = st.slider("Randament Minim (ROI %):", min_value=5, max_value=50, value=12, step=1)

    is_srl = "SRL" in regim_cumparator
    buyer_type_str = "srl_platitor_tva_vies" if is_srl else "persoana_fizica"

    with st.spinner("Interogăm baza de date pentru oportunități externe..."):
        deals_df = find_top_import_arbitrage_deals(
            db_path=DB_PATH,
            min_profit_eur=float(min_profit_filter),
            min_roi_pct=float(min_roi_filter),
            limit=25,
            buyer_type=buyer_type_str,
            vat_deductible=True
        )

    if tara_filtru != "Toate Țările" and not deals_df.empty:
        code_map = {"Austria (AT)": "AT", "Germania (DE)": "DE", "Olanda (NL)": "NL", "Belgia (BE)": "BE"}
        selected_code = code_map.get(tara_filtru)
        if selected_code:
            deals_df = deals_df[deals_df["origin_country"] == selected_code]

    if not deals_df.empty:
        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("Oportunități Calificate", len(deals_df))
        c_m2.metric("Profit Mediu Estimat", f"{deals_df['net_profit_eur'].mean():,.0f} €")
        c_m3.metric("ROI Mediu", f"{deals_df['roi_pct'].mean():.1f}%")

        for idx, row in deals_df.iterrows():
            with st.container(border=True):
                r_col1, r_col2, r_col3, r_col4 = st.columns([3, 2, 2, 2])
                with r_col1:
                    st.markdown(f"### [{row['origin_country']}] {row['title']}")
                    st.write(f"🚗 An {row['year']} | {row['mileage_km']:,} km | {row.get('fuel_type', 'N/A')}")
                    if is_srl and row.get('vat_saved_eur', 0) > 0:
                        st.badge(f"Scutire TVA Netto: -{row['vat_saved_eur']:,.0f} €", type="success")
                    if row.get('url'):
                        st.markdown(f"[🔗 Deschide Anunțul pe {row.get('source', 'Web').capitalize()}]({row['url']})")

                with r_col2:
                    st.write(f"**Preț Achiziție:** {row['foreign_price_eur']:,.0f} €")
                    st.write(f"**Cheltuieli Import (Trailer + RAR):** {row['import_expenses_eur']:,.0f} €")
                    st.write(f"**Total Investit:** {row['total_investment_eur']:,.0f} €")

                with r_col3:
                    st.write(f"**Valoare Piață România:** {row['estimated_ro_price_eur']:,.0f} €")
                    st.caption(f"Sursă evaluare: {row.get('valuation_source', 'Model ML')}")

                with r_col4:
                    st.metric(
                        "PROFIT NET ESTIMAT",
                        f"+{row['net_profit_eur']:,.0f} €",
                        f"ROI {row['roi_pct']:.1f}%"
                    )

                # Script de negociere expandabil
                with st.expander("✉️ Generează Mesaj de Negociere pentru Vânzător", expanded=False):
                    offer_calc = calculate_target_negotiation_price(
                        asked_price_eur=row['foreign_price_eur'],
                        seller_type="Dealer",
                        is_netto_eligible=is_srl
                    )
                    st.info(f"💡 Preț țintă propus pentru deschiderea negocierii: **{offer_calc['opening_offer_eur']:,.0f} €**")

                    c_lang1, c_lang2 = st.tabs(["🇩🇪 Mesaj în Germană", "🇬🇧 Mesaj în Engleză"])
                    with c_lang1:
                        de_msg = generate_german_negotiation_message(
                            car_title=row['title'],
                            asked_price_eur=row['foreign_price_eur'],
                            offer_price_eur=offer_calc['opening_offer_eur'],
                            is_company_buyer=is_srl
                        )
                        st.text_area("Copiază textul în Germană:", de_msg, height=220, key=f"de_{idx}")
                    with c_lang2:
                        en_msg = generate_english_negotiation_message(
                            car_title=row['title'],
                            asked_price_eur=row['foreign_price_eur'],
                            offer_price_eur=offer_calc['opening_offer_eur'],
                            is_company_buyer=is_srl
                        )
                        st.text_area("Copiază textul în Engleză:", en_msg, height=220, key=f"en_{idx}")
    else:
        st.info("ℹ️ Nu există oferte care să depășească pragul ales de profit cu filtrele curente. Rulează o sesiune de scraping pe Austria sau Germania pentru a colecta date proaspete.")


# ==============================================================================
# TAB 2: SIMULATOR COSTURI & OPORTUNITATE (NEGRU PE ALB)
# ==============================================================================
with tab2:
    st.subheader("🧮 Simulator Detaliat: Mers Personal (\"Pe Roți\") vs Transport pe Platformă (TIR)")
    st.markdown(
        "Află exact dacă se merită să mergi personal după mașină sau să o trimiți pe platformă, "
        "luând în calcul **combustibilul, vinietele, numerele de tranzit, cazarea, diurna și costul timpului pierdut**."
    )

    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        sim_country = st.selectbox(
            "Țară / Regiune de Proveniență:",
            ["Germania Sud (München, Stuttgart)", "Germania Centru (Frankfurt, Köln)", "Germania Nord (Berlin, Hamburg)",
             "Austria (Viena, Graz, Linz)", "Olanda (Amsterdam, Rotterdam)", "Belgia (Bruxelles, Antwerpen)",
             "Italia Nord (Milano, Verona)", "Franța Est (Strasbourg, Lyon)"],
            index=0
        )
        sim_price = st.number_input("Preț Achiziție în Vest (€):", min_value=1000, max_value=200000, value=12500, step=500)

    with s_col2:
        sim_expected_ro = st.number_input("Preț Estimat Revânzare în România (€):", min_value=1000, max_value=250000, value=15800, step=500)
        sim_regim = st.selectbox("Regim Fiscal Achiziție:", ["Persoană Fizică (Preț Brut)", "Firmă SRL VIES (Scutire TVA Netto)"])

    with s_col3:
        sim_plates = st.selectbox("Tip Numere Tranzit (dacă mergi pe roți):", ["Numere Roșii Export (15/30 zile - Oficial)", "Numere Galbene Scurtă Durată (5 zile)"])
        sim_opp_cost = st.checkbox("Include Costul de Oportunitate al Timpului (zile muncă pierdute)", value=True)

    # Mapare cod țară
    country_map = {
        "Germania Sud (München, Stuttgart)": ("DE", "München"),
        "Germania Centru (Frankfurt, Köln)": ("DE", "Frankfurt"),
        "Germania Nord (Berlin, Hamburg)": ("DE", "Berlin"),
        "Austria (Viena, Graz, Linz)": ("AT", "Wien"),
        "Olanda (Amsterdam, Rotterdam)": ("NL", "Amsterdam"),
        "Belgia (Bruxelles, Antwerpen)": ("BE", "Bruxelles"),
        "Italia Nord (Milano, Verona)": ("IT", "Milano"),
        "Franța Est (Strasbourg, Lyon)": ("FR", "Strasbourg")
    }
    c_code, c_city = country_map[sim_country]
    is_red = "Roșii" in sim_plates
    is_srl_sim = "SRL" in sim_regim

    sim_res = calculate_import_costs(
        country_code=c_code,
        city_or_zip=c_city,
        car_purchase_price_eur=float(sim_price),
        expected_romanian_selling_price_eur=float(sim_expected_ro),
        use_export_plates=is_red,
        include_opportunity_cost=sim_opp_cost,
        buyer_type="srl_platitor_tva_vies" if is_srl_sim else "persoana_fizica",
        vat_deductible=True
    )

    st.markdown("---")
    res_p = sim_res["scenarios"]["personal_trip"]
    res_t = sim_res["scenarios"]["platform_transport"]

    # Rezumat comparativ
    res_col1, res_col2 = st.columns(2)
    with res_col1:
        st.error(f"### 🚗 1. Deplasare Personală (\"Pe roți\")")
        st.metric("Total Cheltuieli Deplasare", f"{res_p['total_cost_eur']:,.0f} €", f"{res_p['km_added_to_car']} km parcurși")
        st.write(f"⏱️ **Timp pe drum:** {res_p['days_spent']} zile")
        df_p = pd.DataFrame([
            {"Post Cheltuială": "Combustibil dus-întors", "Sumă": f"{res_p['breakdown']['fuel_eur']} €"},
            {"Post Cheltuială": "Viniete & Taxe tuneluri", "Sumă": f"{res_p['breakdown']['vignettes_and_tolls_eur']} €"},
            {"Post Cheltuială": "Numere tranzit & Asigurare Zoll", "Sumă": f"{res_p['breakdown']['transit_plates_eur']} €"},
            {"Post Cheltuială": "Transport dus (Avion/Autocar/Tren)", "Sumă": f"{res_p['breakdown']['transport_dus_eur']} €"},
            {"Post Cheltuială": "Cazare & Diurnă masă", "Sumă": f"{res_p['breakdown']['hotel_and_food_eur']} €"},
            {"Post Cheltuială": "Cost Oportunitate Timp (venit pierdut)", "Sumă": f"{res_p['breakdown']['time_opportunity_cost_eur']} €"},
            {"Post Cheltuială": "Fond Risc / Neprevăzut", "Sumă": f"{res_p['breakdown']['risk_buffer_eur']} €"},
            {"Post Cheltuială": "Birocrație România (RAR + Traduceri + Plăcuțe)", "Sumă": f"{res_p['breakdown']['romania_rar_and_registration_eur']} €"}
        ])
        st.dataframe(df_p, hide_index=True, use_container_width=True)

    with res_col2:
        st.success(f"### 🚚 2. Transport pe Platformă (TIR Autorizat)")
        st.metric("Total Cheltuieli Platformă", f"{res_t['total_cost_eur']:,.0f} €", "0 km adăugați mașinii")
        st.write("⏱️ **Timp pe drum:** 0 zile pierdute")
        df_t = pd.DataFrame([
            {"Post Cheltuială": "Tarif Trailer / Platformă (grupaj)", "Sumă": f"{res_t['breakdown']['platform_transport_fee_eur']} €"},
            {"Post Cheltuială": "Raport Verificare la Distanță (CarVertical/Dekra)", "Sumă": f"{res_t['breakdown']['remote_history_check_eur']} €"},
            {"Post Cheltuială": "Birocrație România (RAR + Traduceri + Plăcuțe)", "Sumă": f"{res_t['breakdown']['romania_rar_and_registration_eur']} €"}
        ])
        st.dataframe(df_t, hide_index=True, use_container_width=True)

    st.info(f"💡 **Concluzie Economică:** {sim_res['comparison']['summary_ro']}")

    if sim_res["financials"]:
        fin = sim_res["financials"]
        st.markdown("### 📈 Bilanț Financiar și Rentabilitate")
        f_c1, f_c2 = st.columns(2)
        with f_c1:
            st.write("**Scenariul Pe Roți:**")
            st.write(f"Total Investit: **{fin['scenario_personal']['total_invested_eur']:,.0f} €**")
            st.metric("Profit Net", f"{fin['scenario_personal']['net_profit_eur']:+,.0f} €", f"ROI {fin['scenario_personal']['roi_pct']}%")

        with f_c2:
            st.write("**Scenariul Platformă:**")
            st.write(f"Total Investit: **{fin['scenario_platform']['total_invested_eur']:,.0f} €**")
            st.metric("Profit Net", f"{fin['scenario_platform']['net_profit_eur']:+,.0f} €", f"ROI {fin['scenario_platform']['roi_pct']}%")


# ==============================================================================
# TAB 3: CONFIGURATOR VARIABILE & TARIFE
# ==============================================================================
with tab3:
    st.subheader("⚙️ Configurare Dinamică a Parametrilor de Import")
    st.caption("Modificările salvate aici sunt aplicate instant în întregul sistem fără a fi nevoie de restart sau modificat cod.")

    current_cfg = load_import_config()

    with st.form("config_form"):
        st.markdown("#### ⛽ Carburant și Deplasare")
        cf_c1, cf_c2, cf_c3 = st.columns(3)
        with cf_c1:
            new_fuel_price = st.number_input("Preț Carburant UE (€/L):", value=float(current_cfg["fuel"]["fuel_price_eur_per_liter"]), step=0.05)
            new_consumption = st.number_input("Consum Mediu Traseu (L/100km):", value=float(current_cfg["fuel"]["avg_consumption_l_100km"]), step=0.1)
        with cf_c2:
            new_flight = st.number_input("Bilet Avion / Autocar (€):", value=float(current_cfg["travel_and_stay"]["flight_or_bus_ticket_eur"]), step=10.0)
            new_hotel = st.number_input("Cazare Motel/Noapte (€):", value=float(current_cfg["travel_and_stay"]["hotel_per_night_eur"]), step=5.0)
        with cf_c3:
            new_opp_day = st.number_input("Cost Timp / Zi (€/zi):", value=float(current_cfg["opportunity_cost"]["time_cost_per_day_eur"]), step=5.0)
            new_risk = st.number_input("Fond Risc Neprevăzut (€):", value=float(current_cfg["opportunity_cost"]["risk_buffer_eur"]), step=10.0)

        st.markdown("#### 🚚 Tarife Medii Platformă / Trailer Autorizat (€)")
        pf_c1, pf_c2, pf_c3, pf_c4 = st.columns(4)
        with pf_c1:
            p_de_south = st.number_input("Germania Sud (München):", value=float(current_cfg["platform_rates"]["DE_SOUTH"]), step=25.0)
            p_de_cent = st.number_input("Germania Centru (Frankfurt):", value=float(current_cfg["platform_rates"]["DE_CENTRAL"]), step=25.0)
        with pf_c2:
            p_de_north = st.number_input("Germania Nord (Berlin):", value=float(current_cfg["platform_rates"]["DE_NORTH"]), step=25.0)
            p_at = st.number_input("Austria (Viena/Linz):", value=float(current_cfg["platform_rates"]["AT"]), step=25.0)
        with pf_c3:
            p_nl = st.number_input("Olanda (Amsterdam):", value=float(current_cfg["platform_rates"]["NL"]), step=25.0)
            p_be = st.number_input("Belgia (Bruxelles):", value=float(current_cfg["platform_rates"]["BE"]), step=25.0)
        with pf_c4:
            p_it = st.number_input("Italia Nord (Milano):", value=float(current_cfg["platform_rates"]["IT_NORTH"]), step=25.0)
            p_fr = st.number_input("Franța Est (Strasbourg):", value=float(current_cfg["platform_rates"]["FR_EAST"]), step=25.0)

        st.markdown("#### 📋 Birocrație România (RAR, Traduceri, Numere)")
        r_c1, r_c2, r_c3 = st.columns(3)
        with r_c1:
            new_rar = st.number_input("RAR (CIV + ITP + Autenticitate) €:", value=float(current_cfg["romania_registration"]["rar_inspection_and_civ_eur"]), step=5.0)
        with r_c2:
            new_trans = st.number_input("Traduceri Autorizate Acte €:", value=float(current_cfg["romania_registration"]["authorized_translations_eur"]), step=5.0)
        with r_c3:
            new_plates = st.number_input("Taxe Înmatriculare + Plăcuțe €:", value=float(current_cfg["romania_registration"]["police_drpciv_plates_eur"]), step=5.0)

        submitted = st.form_submit_button("💾 Salvează Noile Parametri de Import", type="primary")
        if submitted:
            current_cfg["fuel"]["fuel_price_eur_per_liter"] = new_fuel_price
            current_cfg["fuel"]["avg_consumption_l_100km"] = new_consumption
            current_cfg["travel_and_stay"]["flight_or_bus_ticket_eur"] = new_flight
            current_cfg["travel_and_stay"]["hotel_per_night_eur"] = new_hotel
            current_cfg["opportunity_cost"]["time_cost_per_day_eur"] = new_opp_day
            current_cfg["opportunity_cost"]["risk_buffer_eur"] = new_risk

            current_cfg["platform_rates"]["DE_SOUTH"] = p_de_south
            current_cfg["platform_rates"]["DE_CENTRAL"] = p_de_cent
            current_cfg["platform_rates"]["DE_NORTH"] = p_de_north
            current_cfg["platform_rates"]["AT"] = p_at
            current_cfg["platform_rates"]["NL"] = p_nl
            current_cfg["platform_rates"]["BE"] = p_be
            current_cfg["platform_rates"]["IT_NORTH"] = p_it
            current_cfg["platform_rates"]["FR_EAST"] = p_fr

            current_cfg["romania_registration"]["rar_inspection_and_civ_eur"] = new_rar
            current_cfg["romania_registration"]["authorized_translations_eur"] = new_trans
            current_cfg["romania_registration"]["police_drpciv_plates_eur"] = new_plates

            if save_import_config(current_cfg):
                st.success("✅ Parametrii de import au fost actualizați și salvați cu succes pe disc!")
            else:
                st.error("❌ Eroare la salvarea configurației.")
