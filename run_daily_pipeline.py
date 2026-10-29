# FILE: run_daily_pipeline.py
"""
Orchestrator central pentru pipeline-ul zilnic al pietei auto.
Ruleaza automat:
1. Scraperele in mod incremental (ziua cu Early Stopping) sau complet (noaptea deep scrape)
2. Salvarea si detectarea modificarilor de pret in SQLite (cars.db)
3. Marcarea masinilor inactive / vandute (care nu au mai aparut la scraping)
4. Curatarea datelor si exportul in format Parquet ultra-rapid
5. Antrenarea si actualizarea modelului ML (models/price_model.joblib)
6. Alerte Instantanee de Arbitraj (anunturi noi subevaluate de modelul ML)
7. Raportul de caderi de pret de astazi.
"""

import os
import sys
import time
import argparse
import datetime
import requests
import joblib
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import (
    get_db_stats,
    mark_inactive_listings,
    get_price_drops,
    get_new_listings_today,
    DB_PATH
)
from scraper_autoUncle import scrape_autouncle


def send_price_drop_alerts(drops_df: pd.DataFrame, min_drop_alert_eur: float = 500.0):
    """
    Trimite alerte automate pentru scaderi majore de pret folosind dispecerul
    rezilient de alertare (Telegram -> Discord -> Email -> Coada disc).
    """
    if drops_df.empty:
        return

    significant = drops_df[drops_df['drop_eur'] >= min_drop_alert_eur]
    if significant.empty:
        return

    lines = [f"📉 **[ALERTA BURSA AUTO]** S-au detectat {len(significant)} scăderi majore de preț (>= {min_drop_alert_eur:,.0f} EUR):\n"]
    for idx, r in significant.head(8).iterrows():
        title = str(r['title'])[:38]
        old_p = r['old_price']
        new_p = r['new_price']
        drop_eur = r['drop_eur']
        drop_pct = r['drop_pct']
        url = r.get('url', '')
        link_str = f" - [🔗 Link Anunt]({url})" if url else ""
        lines.append(f"* **{title}**: {old_p:,.0f} -> {new_p:,.0f} EUR (-{drop_eur:,.0f} EUR / -{drop_pct}%){link_str}")

    msg = "\n".join(lines)
    try:
        from alert_dispatcher import dispatch_alert_with_fallback
        res = dispatch_alert_with_fallback(subject="📉 ALERTA BURSA AUTO: Scăderi Majore de Preț", message=msg)
        print(f"    [Alert] Rezultat expediere alerte scăderi preț: {res['results']}")
    except Exception as e:
        print(f"    [!] Eroare expediere alerte prin dispecer: {e}")


def send_arbitrage_alerts(
    since_timestamp: str = None,
    min_profit_safety_margin: float = 500.0,
    min_discount_pct: float = 20.0,
    max_discount_pct: float = 50.0,
    model_path: str = "models/price_model_xgboost.joblib",
    db_path: str = DB_PATH
):
    """
    Extrage masinile noi inserate astazi in SQLite, le trece prin modelul ML (XGBoost / RF),
    calculeaza costul de reconditionare si Deal Score-ul (0-100),
    iar daca oportunitatea este rentabila trimite alerte imbogatite pe Discord si Telegram.
    """
    # Prioritizam XGBoost, fallback la RF, fallback la ValuationEngine
    chosen_path = model_path if os.path.exists(model_path) else "models/price_model.joblib"
    model = None
    mae = 1500.0
    features = []

    if os.path.exists(chosen_path):
        try:
            payload = joblib.load(chosen_path)
            model = payload.get('model')
            mae = float(payload.get('mae', 1500.0))
            features = payload.get('features', ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size'])
        except Exception as e:
            print(f"    [!] Eroare incarcare model ML ({chosen_path}): {e}. Folosim motorul de evaluare fallback...")
    else:
        print(f"    [*] Modelul ML ({chosen_path}) nu exista. Folosim motorul de evaluare fallback...")

    new_cars = get_new_listings_today(since_timestamp=since_timestamp, db_path=db_path)
    if new_cars.empty:
        new_cars = get_new_listings_today(since_timestamp=None, db_path=db_path)

    if new_cars.empty:
        print("    Nu s-au gasit anunturi noi inserate astazi pentru analiza de arbitraj.")
        return

    print(f"    [*] Evaluam {len(new_cars)} masini noi inserate astazi pentru oportunitati de arbitraj...")

    try:
        from main import parse_car_title, infer_fuel_type, infer_engine_size
        from ml_engine_upgrade import apply_advanced_features
        from deal_scorer import compute_deal_score
    except ImportError as e:
        print(f"    [!] Nu s-au putut importa modulele avansate: {e}")
        return

    # Extragere trasaturi pentru model
    new_cars[['Brand', 'Model', 'Trim']] = new_cars['title'].apply(parse_car_title)
    new_cars['Trim'] = new_cars['Trim'].fillna('Standard')
    new_cars['fuel_type'] = new_cars.apply(infer_fuel_type, axis=1)
    new_cars['engine_size'] = new_cars.apply(infer_engine_size, axis=1).fillna(2.0)

    # Corectie rulaj concatenat
    def correct_km(row):
        km = row.get('mileage_km')
        yr = row.get('year')
        if pd.notna(km) and pd.notna(yr) and km > 500000:
            s_km = str(int(km))
            s_yr = str(int(yr))
            if s_km.startswith(s_yr) and len(s_km) > len(s_yr):
                try:
                    val = int(s_km[len(s_yr):])
                    if 100 <= val <= 500000:
                        return val
                except Exception:
                    pass
        return km

    new_cars['mileage_km'] = new_cars.apply(correct_km, axis=1)

    # Daca modelul are feature-uri extinse, le aplicam
    if 'car_age' in features:
        new_cars = apply_advanced_features(new_cars)

    mask_valid = (
        new_cars['Brand'].notna() &
        new_cars['Model'].notna() &
        new_cars['year'].notna() &
        (new_cars['year'] >= 2010) &
        (new_cars['year'] <= 2026) &
        new_cars['mileage_km'].notna() &
        (new_cars['mileage_km'] >= 100) &
        (new_cars['mileage_km'] <= 500000) &
        new_cars['price_eur'].notna() &
        (new_cars['price_eur'] >= 1000) &
        (new_cars['price_eur'] <= 150000)
    )
    candidates = new_cars[mask_valid].copy()

    if candidates.empty:
        print("    Nicio masina noua nu indeplineste criteriile complete de compatibilitate ML.")
        return

    pred_success = False
    if model is not None:
        try:
            avail_features = [f for f in features if f in candidates.columns]
            candidates['predicted_price'] = model.predict(candidates[avail_features])
            pred_success = True
        except Exception as e:
            print(f"    [!] Predictia ML a esuat ({e}). Trecem pe fallback valuation_engine...")

    if not pred_success:
        from valuation_engine import valuation_engine
        pred_list = []
        for _, row in candidates.iterrows():
            ve = valuation_engine.estimate_price(
                brand=row['Brand'],
                model=row['Model'],
                year=int(row['year']),
                mileage_km=int(row['mileage_km']),
                fuel_type=row.get('fuel_type')
            )
            pred_list.append(ve["predicted_price_eur"])
        candidates['predicted_price'] = pred_list

    candidates['profit_margin'] = candidates['predicted_price'] - candidates['price_eur']
    candidates['discount_pct'] = (candidates['profit_margin'] / candidates['predicted_price']) * 100

    threshold_margin = mae + min_profit_safety_margin
    opportunities = candidates[
        (candidates['profit_margin'] >= threshold_margin) &
        (candidates['discount_pct'] >= min_discount_pct) &
        (candidates['discount_pct'] <= max_discount_pct)
    ].sort_values(by='profit_margin', ascending=False)

    if opportunities.empty:
        print(f"    Nu s-au detectat chilipiruri noi subevaluate peste pragul de arbitraj (MAE + {min_profit_safety_margin:.0f} EUR si reducere >= {min_discount_pct}%).")
        return

    # Calculam Deal Score compozit pentru fiecare chilipir
    enhanced_deals = []
    for _, r in opportunities.iterrows():
        ds = compute_deal_score(
            predicted_market_price=r['predicted_price'],
            asked_price=r['price_eur'],
            brand=r['Brand'],
            model=r['Model'],
            year=int(r['year']),
            mileage_km=int(r['mileage_km']),
            fuel_type=r.get('fuel_type'),
            seller_type=r.get('seller_type')
        )
        r_dict = dict(r)
        r_dict['deal_score'] = ds['deal_score']
        r_dict['badge'] = ds['badge']
        r_dict['net_profit'] = ds['financials']['net_profit_margin']
        r_dict['maint_cost'] = ds['financials']['maintenance_cost']
        r_dict['roi_pct'] = ds['financials']['net_roi_pct']
        r_dict['target_buy_offer'] = ds['target_buy_offer_eur']
        enhanced_deals.append(r_dict)

    df_enhanced = pd.DataFrame(enhanced_deals).sort_values(by='deal_score', ascending=False)

    print(f"\n[🔥] S-AU DETECTAT {len(df_enhanced)} OPORTUNITATI NOI DE ARBITRAJ (Clasate dupa Deal Score):")
    print("-" * 95)
    for _, r in df_enhanced.head(8).iterrows():
        title = str(r['title'])[:34]
        p = r['price_eur']
        pred = r['predicted_price']
        score = r['deal_score']
        net_p = r['net_profit']
        badge = r['badge']
        print(f"  * {title:<34} | Pret: {p:,.0f} € | Estimat: {pred:,.0f} € | Scor: {score}/100 | Profit NET: {net_p:+,.0f} €")
    print("-" * 95)

    try:
        from alert_dispatcher import dispatch_alert_with_fallback
        for _, r in df_enhanced.head(6).iterrows():
            title = str(r['title']).strip()
            p = r['price_eur']
            pred = r['predicted_price']
            profit = r['profit_margin']
            net_p = r['net_profit']
            maint = r['maint_cost']
            score = r['deal_score']
            badge = r['badge']
            disc = r['discount_pct']
            target_offer = r['target_buy_offer']
            year = int(r['year']) if pd.notna(r['year']) else 'N/A'
            km = int(r['mileage_km']) if pd.notna(r['mileage_km']) else 0
            fuel = r.get('fuel_type', 'N/A')
            engine = r.get('engine_size', 2.0)
            source = str(r.get('source', 'Web')).upper()
            url = r.get('url', '')
            link_str = f"\n🔗 **Link Anunt:** [Deschide Oferta]({url})" if url else ""

            discord_content = (
                f"🚨 **CHILIPIR DETECTAT: {title}**\n"
                f"🎯 **Deal Score:** `{score}/100` | {badge}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Preț Vânzător:** {p:,.0f} €\n"
                f"📈 **Valoare Reală ML:** {pred:,.0f} € *(-{disc:.1f}% discount)*\n"
                f"🔧 **Cost Estimat Recondiționare:** {maint:,.0f} €\n"
                f"🟢 **Profit NET Real (după piese):** +{net_p:,.0f} €\n"
                f"💡 **Ofertă Recomandată Vânzător:** **{target_offer:,.0f} €**\n"
                f"🚗 **Specificații:** An {year} | {km:,.0f} km | {engine:.1f}L {fuel}\n"
                f"🌐 **Sursă:** {source}{link_str}"
            )

            res = dispatch_alert_with_fallback(
                subject=f"🚨 CHILIPIR: {title}",
                message=discord_content,
                metadata=r
            )
            print(f"    [Alert] Expediere alerta pentru {title[:30]}: {res['results']}")
            time.sleep(0.3)
    except Exception as e:
        print(f"    [!] Eroare expediere alerte arbitraj: {e}")


def run_pipeline(
    daily_mode: bool = True,
    max_pages: int = 5,
    parallel: bool = True,
    run_all: bool = True,
    run_autovit: bool = False,
    run_olx: bool = False,
    run_cautimasina: bool = False,
    run_bestauto: bool = False,
    run_plusauto: bool = False,
    run_carzz: bool = False,
    run_mobile_de: bool = False,
    run_lajumate: bool = False,
    run_publi24: bool = False,
    run_tiriac: bool = False,
    use_multi_agent: bool = False,
    backup_db: bool = True,
    skip_scraping: bool = False,
    skip_ml: bool = False
):
    start_time = time.time()
    pipeline_start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 65)
    print(f"[*] PORNIRE PIPELINE AUTO - {pipeline_start_ts}")
    print(f"    Mod: {'ZILNIC (Arbitraj Rapid cu Early Stopping)' if daily_mode else 'COMPLET (Deep Scrape, Mentenanta & Retrain ML)'}")
    print(f"    Pagini scanate: {max_pages} per scraper activ | Multi-Agent: {'ACTIV (3 agenți/site)' if use_multi_agent else 'Standard'}")
    print("=" * 65)

    # Backup automat DB înainte de rulare
    if backup_db:
        try:
            from db_optimizer import backup_database
            backup_database(DB_PATH)
        except Exception as e:
            print(f"[!] Eroare la backup DB: {e}")

    # Reziliență: Golire buffer de urgență DB și reîncercare alerte restante
    try:
        from alert_dispatcher import retry_outbox_alerts
        retry_outbox_alerts()
    except Exception as e:
        print(f"[!] Eroare verificare outbox alerte: {e}")

    try:
        from fallback_engine import recovery_buffer
        from db_helper import save_scraped_data
        recovery_buffer.drain_buffer_to_sqlite(lambda df, src: save_scraped_data(df, src, DB_PATH))
    except Exception as e:
        print(f"[!] Eroare drenare buffer recuperare: {e}")

    # -------------------------------------------------------------
    # ETAPA 1: RULARE SCRAPERE (11 PLATFORME)
    # -------------------------------------------------------------
    if not skip_scraping:
        print("\n[ETAPA 1/4] Rulare Scrapere Active...")

        if use_multi_agent:
            print("[*] Rulare prin CRAWLER ENGINE MULTI-AGENT (2-3 pagini per agent, protectie Cloudflare activa)...")
            from crawler_engine import MultiAgentCrawlerEngine
            engine = MultiAgentCrawlerEngine(num_agents=3, batch_size_per_agent=2, db_path=DB_PATH)

            # AutoUncle Multi-Agent
            try:
                from scraper_autoUncle import parse_autouncle_article
                engine.crawl_site(
                    source_name="autouncle",
                    url_builder_fn=lambda p: f"https://www.autouncle.ro/ro/masini-second-hand?page={p}&s%5Border%5D=creation_date_desc",
                    card_parser_fn=parse_autouncle_article,
                    card_selector="article",
                    max_pages=max_pages,
                    early_stopping=daily_mode
                )
            except Exception as e:
                print(f"[!] Eroare AutoUncle Multi-Agent: {e}")

        else:
            tasks = []
            tasks.append(("AutoUncle", scrape_autouncle))

            if run_all or run_autovit:
                from scraper_autovit import scrape_autovit
                tasks.append(("Autovit", scrape_autovit))

            if run_all or run_olx:
                from scraper_olx import scrape_olx
                tasks.append(("OLX", scrape_olx))

            if run_all or run_cautimasina:
                from scraper_cautiMasina import scrape_cautimasina
                tasks.append(("CautiMasina", scrape_cautimasina))

            if run_all or run_bestauto:
                from scraper_bestAuto import scrape_bestauto
                tasks.append(("BestAuto", scrape_bestauto))

            if run_all or run_plusauto:
                from scraper_plusAuto import scrape_plusauto
                tasks.append(("Plus-Auto", scrape_plusauto))

            if run_all or run_carzz:
                from scraper_CarZZ import scrape_carzz
                tasks.append(("CarZZ", scrape_carzz))

            if run_all or run_mobile_de:
                from scraper_mobile_de import scrape_mobile_de
                tasks.append(("Mobile.de (Germania)", scrape_mobile_de))

            if run_all or run_lajumate:
                from scraper_lajumate import scrape_lajumate
                tasks.append(("Lajumate", scrape_lajumate))

            if run_all or run_publi24:
                from scraper_publi24 import scrape_publi24
                tasks.append(("Publi24", scrape_publi24))

            if run_all or run_tiriac:
                from scraper_tiriac_auto import scrape_tiriac_auto
                tasks.append(("Tiriac Auto", scrape_tiriac_auto))

            def execute_scraper(name, scraper_func):
                t0 = time.time()
                try:
                    print(f" -> [{name}] Pornire scraping...")
                    df_res = scraper_func(daily_mode=daily_mode, max_pages=max_pages)
                    dur = time.time() - t0
                    print(f"    [OK] {name}: {len(df_res)} anunturi procesate in {dur:.1f}s.")
                    return name, len(df_res), None
                except Exception as e:
                    dur = time.time() - t0
                    print(f"    [!] Eroare {name} dupa {dur:.1f}s: {e}")
                    return name, 0, e

            if parallel and len(tasks) > 1:
                from concurrent.futures import ThreadPoolExecutor
                workers = min(len(tasks), 4)
                print(f"[*] Rulare CONCURENTA activa ({workers} thread-uri paralele)...")
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [executor.submit(execute_scraper, name, fn) for name, fn in tasks]
                    for fut in futures:
                        fut.result()
            else:
                for name, fn in tasks:
                    execute_scraper(name, fn)

    else:
        print("\n[ETAPA 1/4] Scraping ignorat conform parametrului --skip-scraping.")

    # -------------------------------------------------------------
    # ETAPA 2: ACTUALIZARE STATISTICI, CURATARE & OPTIMIZARE DB
    # -------------------------------------------------------------
    print("\n[ETAPA 2/4] Sincronizare DB & Verificare Anunturi Active...")
    try:
        days_thresh = 14 if not daily_mode else 30
        inactive_marked = mark_inactive_listings(days_threshold=days_thresh)
        # Optimizare indexuri si WAL checkpoint
        from db_optimizer import optimize_database
        optimize_database(DB_PATH)
    except Exception as e:
        print(f"[!] Eroare la mentenanta DB: {e}")

    stats = get_db_stats(DB_PATH)
    print(f"    Total anunturi in SQLite:   {stats['total_listings']:,}")
    print(f"    Anunturi active (in piata): {stats['active_listings']:,}")
    print(f"    Istoric puncte de pret:     {stats['total_price_records']:,}")

    # -------------------------------------------------------------
    # ETAPA 3: PREPROCESARE & RE-ANTRENARE MODEL ML
    # -------------------------------------------------------------
    # In modul noapte (--full), re-antrenam intotdeauna modelul.
    # In modul zi, re-antrenam doar daca nu s-a cerut explicit --skip-ml.
    if not skip_ml:
        print("\n[ETAPA 3/4] Preprocesare Inteligenta & Actualizare Model ML...")
        try:
            from main import run_preprocessing_and_training
            df_clean, model_stats = run_preprocessing_and_training()
            print(f"    [OK] Parquet generat cu succes: {len(df_clean):,} anunturi validate.")
            print(f"    [OK] Model ML actualizat: R2 = {model_stats['r2']*100:.1f}%, MAE = +- {model_stats['mae']:.0f} EUR")
        except Exception as e:
            print(f"[!] Eroare la preprocesare/ML: {e}")
    else:
        print("\n[ETAPA 3/4] Preprocesare ML ignorata conform parametrului --skip-ml.")

    # -------------------------------------------------------------
    # ETAPA 4: ALERTE DE ARBITRAJ SI SCADERI DE PRET
    # -------------------------------------------------------------
    print("\n[ETAPA 4/4] Scanare Oportunitati de Arbitraj & Scaderi de Pret...")

    # 4.1 Alerte Oportunitati Noi de Arbitraj (Instant Push)
    try:
        print("\n[*] Verificare oportunitati noi de arbitraj (masini noi vs ML)...")
        send_arbitrage_alerts(
            since_timestamp=pipeline_start_ts,
            min_profit_safety_margin=500.0,
            min_discount_pct=20.0
        )
    except Exception as e:
        print(f"[!] Eroare la detectia alertelor de arbitraj: {e}")

    # 4.2 Alerte Scaderi de Pret Recente
    try:
        print("\n[*] Verificare scaderi recente de pret...")
        drops = get_price_drops(days=1, min_drop_eur=100)
        if not drops.empty:
            print(f"    S-au detectat {len(drops)} SCADERI DE PRET in ultimele 24 de ore:")
            for idx, r in drops.head(6).iterrows():
                title = str(r['title']).encode('ascii', 'ignore').decode()[:35]
                old_p = r['old_price']
                new_p = r['new_price']
                drop_eur = r['drop_eur']
                drop_pct = r['drop_pct']
                print(f"    * {title:<35} | {old_p:,.0f} -> {new_p:,.0f} EUR | Reducere: -{drop_eur:,.0f} EUR (-{drop_pct}%)")

            # Notificare webhook discord/telegram
            send_price_drop_alerts(drops, min_drop_alert_eur=500.0)
        else:
            print("    Nu s-au inregistrat modificari de pret noi in aceasta sesiune.")
    except Exception as e:
        print(f"[!] Eroare la raportul de preturi: {e}")

    # 4.3 Actualizare Indicatori de Lichiditate (Days-to-Sell)
    try:
        print("\n[*] Actualizare automata tracker de lichiditate (Days-to-Sell)...")
        from liquidity_tracker import compute_and_update_liquidity
        num_seg = compute_and_update_liquidity(DB_PATH)
        print(f"    [OK] Actualizate {num_seg} segmente de piata in tabela model_liquidity.")
    except Exception as e:
        print(f"[!] Eroare la actualizarea lichiditatii: {e}")

    # 4.4 Verificare Alerte Personalizate (Watchlists)
    try:
        print("\n[*] Verificare reguli de Watchlist personalizate...")
        from watchlist_manager import check_listings_against_watchlists
        new_cars_df = get_new_listings_today(since_timestamp=pipeline_start_ts, db_path=DB_PATH)
        if not new_cars_df.empty:
            matches = check_listings_against_watchlists(new_cars_df, db_path=DB_PATH)
            if matches:
                print(f"    [🎯] S-au gasit {len(matches)} potriviri cu alertele utilizatorilor din Watchlist!")
                for m in matches[:5]:
                    print(f"    * Notificare pentru [{m['user_name']}]: {m['car_title']} ({m['price_eur']:,.0f} €)")
            else:
                print("    Nicio potrivire noua cu regulile active de Watchlist.")
    except Exception as e:
        print(f"[!] Eroare la verificarea watchlist-urilor: {e}")

    # 4.5 Generare Raport Zilnic de Piata (Market Intelligence)
    try:
        print("\n[*] Compilare Raport Zilnic Automat de Piata...")
        from market_reporter import generate_daily_market_report
        rep_path = generate_daily_market_report(db_path=DB_PATH, send_discord=True, send_telegram=True)
        print(f"    [OK] Raport generat si salvat la: {rep_path}")
    except Exception as e:
        print(f"[!] Eroare la generarea raportului de piata: {e}")

    total_elapsed = time.time() - start_time
    print("\n" + "=" * 65)
    print(f"[SUCCESS] PIPELINE FINALIZAT IN {total_elapsed:.1f} SECUNDE ({total_elapsed/60:.2f} MINUTE)")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Daily Car Market Pipeline Orchestrator (11 Platforme)")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul nocturn complet (fara early stopping, sincronizare DB, retrain ML)")
    parser.add_argument("--pages", type=int, default=5, help="Numar pagini scanate per scraper (implicit 5 pentru zi, 25 pentru full)")
    parser.add_argument("--sequential", action="store_true", help="Ruleaza scraperele secvential (default este in paralel)")
    parser.add_argument("--all-scrapers", action="store_true", default=True, help="Include toate cele 11 scrapere disponibile (default: True)")
    parser.add_argument("--single-scraper", action="store_true", help="Ruleaza doar AutoUncle")
    parser.add_argument("--multi-agent", action="store_true", help="Ruleaza motorul de crawling multi-agent (2-3 pagini per agent, protectie Cloudflare)")
    parser.add_argument("--autovit", action="store_true", help="Include scraperul Autovit")
    parser.add_argument("--olx", action="store_true", help="Include scraperul OLX")
    parser.add_argument("--cautimasina", action="store_true", help="Include scraperul CautiMasina")
    parser.add_argument("--bestauto", action="store_true", help="Include scraperul BestAuto")
    parser.add_argument("--plusauto", action="store_true", help="Include scraperul PlusAuto")
    parser.add_argument("--carzz", action="store_true", help="Include scraperul CarZZ")
    parser.add_argument("--mobile-de", action="store_true", help="Include scraperul Mobile.de (Germania)")
    parser.add_argument("--lajumate", action="store_true", help="Include scraperul Lajumate")
    parser.add_argument("--publi24", action="store_true", help="Include scraperul Publi24")
    parser.add_argument("--tiriac", action="store_true", help="Include scraperul Tiriac Auto Rulate")
    parser.add_argument("--no-backup", action="store_true", help="Dezactiveaza backup-ul automat al bazei de date")
    parser.add_argument("--skip-scraping", action="store_true", help="Sari peste etapa de scraping")
    parser.add_argument("--skip-ml", action="store_true", help="Sari peste etapa de antrenare ML")
    args = parser.parse_args()

    # Daca se alege --full si utilizatorul nu a setat manual alt numar de pagini, scanam 25 pagini
    if args.full and args.pages == 5:
        max_pages = 25
    else:
        max_pages = args.pages

    run_all = not (
        args.single_scraper or args.autovit or args.olx or args.cautimasina or
        args.bestauto or args.plusauto or args.carzz or args.mobile_de or
        args.lajumate or args.publi24 or args.tiriac
    )

    run_pipeline(
        daily_mode=not args.full,
        max_pages=max_pages,
        parallel=not args.sequential,
        run_all=run_all,
        run_autovit=args.autovit,
        run_olx=args.olx,
        run_cautimasina=args.cautimasina,
        run_bestauto=args.bestauto,
        run_plusauto=args.plusauto,
        run_carzz=args.carzz,
        run_mobile_de=args.mobile_de,
        run_lajumate=args.lajumate,
        run_publi24=args.publi24,
        run_tiriac=args.tiriac,
        use_multi_agent=args.multi_agent,
        backup_db=not args.no_backup,
        skip_scraping=args.skip_scraping,
        skip_ml=args.skip_ml
    )


if __name__ == "__main__":
    main()
