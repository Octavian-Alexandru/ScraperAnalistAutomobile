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
    Trimite alerte automate pe Discord sau Telegram pentru scaderi majore de pret
    daca sunt configurate variabilele de mediu:
    - DISCORD_WEBHOOK_URL
    - TELEGRAM_BOT_TOKEN si TELEGRAM_CHAT_ID
    """
    if drops_df.empty:
        return

    significant = drops_df[drops_df['drop_eur'] >= min_drop_alert_eur]
    if significant.empty:
        return

    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not discord_url and not (tg_token and tg_chat_id):
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

    # Discord Webhook
    if discord_url:
        try:
            res = requests.post(discord_url, json={"content": msg[:2000]}, timeout=10)
            if res.status_code in (200, 204):
                print("    [OK Discord] Alerte scaderi de pret trimise cu succes.")
            else:
                print(f"    [!] Discord Webhook a returnat codul {res.status_code}")
        except Exception as e:
            print(f"    [!] Eroare trimitere Discord: {e}")

    # Telegram Bot
    if tg_token and tg_chat_id:
        try:
            tg_endpoint = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {
                "chat_id": tg_chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            }
            res = requests.post(tg_endpoint, json=payload, timeout=10)
            if res.status_code == 200:
                print("    [OK Telegram] Alerte scaderi de pret trimise cu succes.")
            else:
                print(f"    [!] Telegram a returnat codul {res.status_code}")
        except Exception as e:
            print(f"    [!] Eroare trimitere Telegram: {e}")


def send_arbitrage_alerts(
    since_timestamp: str = None,
    min_profit_safety_margin: float = 500.0,
    min_discount_pct: float = 20.0,
    max_discount_pct: float = 50.0,
    model_path: str = "models/price_model.joblib",
    db_path: str = DB_PATH
):
    """
    Extrage masinile noi inserate astazi in SQLite, le trece prin modelul ML,
    iar daca marja de profit depaseste MAE-ul modelului + marja de siguranta (si discount >= 20%),
    trimite instantaneu alerte pe Discord cu formatul:
    🚨 OPORTUNITATE NOUĂ DE ARBITRAJ: [Titlu Mașină]
    """
    if not os.path.exists(model_path):
        print("    [!] Modelul ML nu a fost gasit pe disc (models/price_model.joblib). Sarim peste alertele de arbitraj.")
        return

    try:
        payload = joblib.load(model_path)
        model = payload['model']
        mae = float(payload.get('mae', 1500.0))
        features = payload.get('features', ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size'])
    except Exception as e:
        print(f"    [!] Eroare incarcare model ML: {e}")
        return

    new_cars = get_new_listings_today(since_timestamp=since_timestamp, db_path=db_path)
    if new_cars.empty:
        # Daca nu gasim masini de la timestamp, incercam toate masinile de astazi
        new_cars = get_new_listings_today(since_timestamp=None, db_path=db_path)

    if new_cars.empty:
        print("    Nu s-au gasit anunturi noi inserate astazi pentru analiza de arbitraj.")
        return

    print(f"    [*] Evaluam {len(new_cars)} masini noi inserate astazi prin modelul ML (MAE = +- {mae:,.0f} EUR)...")

    try:
        from main import parse_car_title, infer_fuel_type, infer_engine_size
    except ImportError as e:
        print(f"    [!] Nu s-au putut importa functiile de preprocesare din main.py: {e}")
        return

    # Extragere trasaturi pentru model
    new_cars[['Brand', 'Model', 'Trim']] = new_cars['title'].apply(parse_car_title)
    new_cars['Trim'] = new_cars['Trim'].fillna('Standard')
    new_cars['fuel_type'] = new_cars.apply(infer_fuel_type, axis=1)
    new_cars['engine_size'] = new_cars.apply(infer_engine_size, axis=1)
    new_cars['engine_size'] = new_cars['engine_size'].fillna(2.0)

    # Corectie rulaj concatenat (ex: 2016172000 -> 172000)
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

    # Filtrare compatibilitate model ML
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

    try:
        candidates['predicted_price'] = model.predict(candidates[features])
    except Exception as e:
        print(f"    [!] Eroare la executia predictiei ML: {e}")
        return

    candidates['profit_margin'] = candidates['predicted_price'] - candidates['price_eur']
    candidates['discount_pct'] = (candidates['profit_margin'] / candidates['predicted_price']) * 100

    # Prag de arbitraj: profit > MAE + prag de siguranta SI reducere procentuala >= prag (20%)
    threshold_margin = mae + min_profit_safety_margin
    opportunities = candidates[
        (candidates['profit_margin'] >= threshold_margin) &
        (candidates['discount_pct'] >= min_discount_pct) &
        (candidates['discount_pct'] <= max_discount_pct)
    ].sort_values(by='profit_margin', ascending=False)

    if opportunities.empty:
        print(f"    Nu s-au detectat chilipiruri noi subevaluate peste pragul de arbitraj (MAE + {min_profit_safety_margin:.0f} EUR si reducere >= {min_discount_pct}%).")
        return

    print(f"\n[🔥] S-AU DETECTAT {len(opportunities)} OPORTUNITATI NOI DE ARBITRAJ:")
    print("-" * 85)
    for _, r in opportunities.head(8).iterrows():
        title = str(r['title'])[:38]
        p = r['price_eur']
        pred = r['predicted_price']
        profit = r['profit_margin']
        disc = r['discount_pct']
        print(f"  * {title:<38} | Pret: {p:,.0f} € | Estimat ML: {pred:,.0f} € | Profit: +{profit:,.0f} € (-{disc:.1f}%)")
    print("-" * 85)

    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not discord_url and not (tg_token and tg_chat_id):
        print("    [!] DISCORD_WEBHOOK_URL / Telegram nu sunt configurate. Notificarile nu au fost transmise.")
        return

    # Trimitem notificarile pe Discord / Telegram
    for _, r in opportunities.head(8).iterrows():
        title = str(r['title']).strip()
        p = r['price_eur']
        pred = r['predicted_price']
        profit = r['profit_margin']
        disc = r['discount_pct']
        year = int(r['year']) if pd.notna(r['year']) else 'N/A'
        km = int(r['mileage_km']) if pd.notna(r['mileage_km']) else 0
        fuel = r.get('fuel_type', 'N/A')
        engine = r.get('engine_size', 2.0)
        source = str(r.get('source', 'Web')).upper()
        url = r.get('url', '')
        link_str = f"\n🔗 **Link Anunt:** [Deschide Oferta]({url})" if url else ""

        discord_content = (
            f"🚨 **OPORTUNITATE NOUĂ DE ARBITRAJ: {title}**\n"
            f"💰 **Preț Vânzător:** {p:,.0f} €\n"
            f"📈 **Valoare Reală Estimată (ML):** {pred:,.0f} € *(Acuratete model: ±{mae:,.0f} €)*\n"
            f"🟢 **Profit Potențial (Marjă):** +{profit:,.0f} € *(-{disc:.1f}% sub prețul pieței)*\n"
            f"🚗 **Specificații:** An {year} | {km:,.0f} km | {engine:.1f}L {fuel} | {r.get('Trim', 'Standard')}\n"
            f"🌐 **Sursă:** {source}{link_str}"
        )

        if discord_url:
            try:
                res = requests.post(discord_url, json={"content": discord_content}, timeout=10)
                if res.status_code in (200, 204):
                    print(f"    [OK Discord] Alerta trimisa: {title[:35]}")
                else:
                    print(f"    [!] Discord a returnat codul {res.status_code}")
                time.sleep(0.5)
            except Exception as e:
                print(f"    [!] Eroare trimitere Discord: {e}")

        if tg_token and tg_chat_id:
            try:
                tg_endpoint = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                payload_tg = {
                    "chat_id": tg_chat_id,
                    "text": discord_content,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False
                }
                requests.post(tg_endpoint, json=payload_tg, timeout=10)
                time.sleep(0.3)
            except Exception:
                pass


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
    skip_scraping: bool = False,
    skip_ml: bool = False
):
    start_time = time.time()
    pipeline_start_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 65)
    print(f"[*] PORNIRE PIPELINE AUTO - {pipeline_start_ts}")
    print(f"    Mod: {'ZILNIC (Arbitraj Rapid cu Early Stopping)' if daily_mode else 'COMPLET (Mentenanta, Deep Scrape & Retrain ML)'}")
    print(f"    Pagini scanate: {max_pages} per scraper activ")
    print("=" * 65)

    # -------------------------------------------------------------
    # ETAPA 1: RULARE SCRAPERE
    # -------------------------------------------------------------
    if not skip_scraping:
        print("\n[ETAPA 1/4] Rulare Scrapere Active...")

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
    # ETAPA 2: ACTUALIZARE STATISTICI & CURATARE INACTIVE
    # -------------------------------------------------------------
    print("\n[ETAPA 2/4] Sincronizare DB & Verificare Anunturi Active...")
    try:
        # In modul complet curatam masinile nevazute de mai mult de 14 zile
        days_thresh = 14 if not daily_mode else 30
        inactive_marked = mark_inactive_listings(days_threshold=days_thresh)
    except Exception as e:
        print(f"[!] Eroare la marcarea inactivelor: {e}")

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

    total_elapsed = time.time() - start_time
    print("\n" + "=" * 65)
    print(f"[SUCCESS] PIPELINE FINALIZAT IN {total_elapsed:.1f} SECUNDE ({total_elapsed/60:.2f} MINUTE)")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Daily Car Market Pipeline Orchestrator")
    parser.add_argument("--full", action="store_true", help="Ruleaza modul nocturn complet (fara early stopping, sincronizare DB, retrain ML)")
    parser.add_argument("--pages", type=int, default=5, help="Numar pagini scanate per scraper (implicit 5 pentru zi, 25 pentru full)")
    parser.add_argument("--sequential", action="store_true", help="Ruleaza scraperele secvential (default este in paralel)")
    parser.add_argument("--all-scrapers", action="store_true", default=True, help="Include toate cele 7 scrapere disponibile (default: True)")
    parser.add_argument("--single-scraper", action="store_true", help="Ruleaza doar AutoUncle")
    parser.add_argument("--autovit", action="store_true", help="Include scraperul Autovit")
    parser.add_argument("--olx", action="store_true", help="Include scraperul OLX")
    parser.add_argument("--cautimasina", action="store_true", help="Include scraperul CautiMasina")
    parser.add_argument("--bestauto", action="store_true", help="Include scraperul BestAuto")
    parser.add_argument("--plusauto", action="store_true", help="Include scraperul PlusAuto")
    parser.add_argument("--carzz", action="store_true", help="Include scraperul CarZZ")
    parser.add_argument("--skip-scraping", action="store_true", help="Sari peste etapa de scraping")
    parser.add_argument("--skip-ml", action="store_true", help="Sari peste etapa de antrenare ML")
    args = parser.parse_args()

    # Daca se alege --full si utilizatorul nu a setat manual alt numar de pagini, scanam 25 pagini
    if args.full and args.pages == 5:
        max_pages = 25
    else:
        max_pages = args.pages

    run_all = not args.single_scraper

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
        skip_scraping=args.skip_scraping,
        skip_ml=args.skip_ml
    )


if __name__ == "__main__":
    main()
