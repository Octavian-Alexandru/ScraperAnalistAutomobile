# FILE: run_daily_pipeline.py
"""
Orchestrator central pentru pipeline-ul zilnic al pietei auto.
Ruleaza automat:
1. Scraperele zilnice in mod incremental (AutoUncle, Autovit, OLX etc.)
2. Salvarea si detectarea modificarilor de pret in SQLite (cars.db)
3. Marcarea masinilor inactive / vandute (care nu au mai aparut la scraping)
4. Curatarea datelor si exportul in format Parquet ultra-rapid
5. Antrenarea si actualizarea modelului ML (models/price_model.joblib)
6. Raportul de oportunitati si caderi de pret de astazi.
"""

import os
import sys
import time
import argparse
import datetime
import requests
import pandas as pd

from db_helper import (
    get_db_stats,
    mark_inactive_listings,
    get_price_drops,
    DB_PATH
)
from scraper_autoUncle import scrape_autouncle


def send_price_drop_alerts(drops_df: pd.DataFrame, min_drop_alert_eur: float = 500.0):
    """
    Trimite alerte automate pe Discord sau Telegram daca sunt configurate
    variabilele de mediu:
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

    lines = [f"[ALERTA BURSA AUTO] S-au detectat {len(significant)} scaderi majore de pret (>= {min_drop_alert_eur:,.0f} EUR):\n"]
    for idx, r in significant.head(8).iterrows():
        title = str(r['title'])[:38]
        old_p = r['old_price']
        new_p = r['new_price']
        drop_eur = r['drop_eur']
        drop_pct = r['drop_pct']
        url = r.get('url', '')
        link_str = f" - [Link Anunt]({url})" if url else ""
        lines.append(f"* **{title}**: {old_p:,.0f} -> {new_p:,.0f} EUR (-{drop_eur:,.0f} EUR / -{drop_pct}%){link_str}")

    msg = "\n".join(lines)

    # Discord Webhook
    if discord_url:
        try:
            res = requests.post(discord_url, json={"content": msg[:2000]}, timeout=10)
            if res.status_code in (200, 204):
                print("    [OK] Alerte trimise cu succes pe Discord.")
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
                print("    [OK] Alerte trimise cu succes pe Telegram.")
            else:
                print(f"    [!] Telegram a returnat codul {res.status_code}")
        except Exception as e:
            print(f"    [!] Eroare trimitere Telegram: {e}")


def run_pipeline(
    daily_mode: bool = True,
    max_pages: int = 5,
    parallel: bool = True,
    run_all: bool = False,
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
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 65)
    print(f"[*] PORNIRE PIPELINE ZILNIC AUTO - {now_str}")
    print(f"    Mod: {'ZILNIC (Incremental)' if daily_mode else 'COMPLET (Full Backfill)'}")
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
        inactive_marked = mark_inactive_listings(days_threshold=30)
    except Exception as e:
        print(f"[!] Eroare la marcarea inactivelor: {e}")

    stats = get_db_stats(DB_PATH)
    print(f"    Total anunturi in SQLite:   {stats['total_listings']:,}")
    print(f"    Anunturi active (in piata): {stats['active_listings']:,}")
    print(f"    Istoric puncte de pret:     {stats['total_price_records']:,}")

    # -------------------------------------------------------------
    # ETAPA 3: PREPROCESARE & RE-ANTRENARE MODEL ML
    # -------------------------------------------------------------
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
    # ETAPA 4: RAPORT OPORTUNITATI & SCADERI DE PRET
    # -------------------------------------------------------------
    print("\n[ETAPA 4/4] Scanare Oportunitati & Scaderi de Pret Recente...")
    try:
        drops = get_price_drops(days=1, min_drop_eur=100)
        if not drops.empty:
            print(f"\n[!] S-au detectat {len(drops)} SCADERI DE PRET in ultimele 24 de ore:")
            print("-" * 80)
            for idx, r in drops.head(10).iterrows():
                title = str(r['title']).encode('ascii', 'ignore').decode()[:38]
                old_p = r['old_price']
                new_p = r['new_price']
                drop_eur = r['drop_eur']
                drop_pct = r['drop_pct']
                print(f"  * {title:<40} | {old_p:,.0f} -> {new_p:,.0f} EUR | Reducere: -{drop_eur:,.0f} EUR (-{drop_pct}%)")
            print("-" * 80)
            if len(drops) > 10:
                print(f"  ... si inca {len(drops) - 10} alte oferte cu pret scazut.")

            # Webhook Alert (daca este configurat Discord sau Telegram)
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
    parser.add_argument("--full", action="store_true", help="Ruleaza in mod exhaustiv complet (nu incremental)")
    parser.add_argument("--pages", type=int, default=5, help="Numar pagini scanate per scraper (default 5)")
    parser.add_argument("--sequential", action="store_true", help="Ruleaza scraperele secvential (default este in paralel)")
    parser.add_argument("--all-scrapers", action="store_true", help="Include toate cele 7 scrapere disponibile")
    parser.add_argument("--autovit", action="store_true", help="Include scraperul Autovit")
    parser.add_argument("--olx", action="store_true", help="Include scraperul OLX")
    parser.add_argument("--cautimasina", action="store_true", help="Include scraperul CautiMasina")
    parser.add_argument("--bestauto", action="store_true", help="Include scraperul BestAuto")
    parser.add_argument("--plusauto", action="store_true", help="Include scraperul PlusAuto")
    parser.add_argument("--carzz", action="store_true", help="Include scraperul CarZZ")
    parser.add_argument("--skip-scraping", action="store_true", help="Sari peste etapa de scraping")
    parser.add_argument("--skip-ml", action="store_true", help="Sari peste etapa de antrenare ML")
    args = parser.parse_args()

    run_pipeline(
        daily_mode=not args.full,
        max_pages=args.pages,
        parallel=not args.sequential,
        run_all=args.all_scrapers,
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

