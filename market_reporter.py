# FILE: market_reporter.py
"""
Generator Automat de Rapoarte Zilnice de Piață (Market Intelligence Report).
Compilează zilnic o sinteză completă a pieței auto din România:
1. Statistici agregate (volum, anunțuri noi, scăderi de preț, lichiditate)
2. Top Oportunități de Arbitraj (cu Deal Score compozit și marjă netă după recondiționare)
3. Top Scăderi Recente de Preț
4. Cele mai lichide modele din piață (viteză maximă de rotație a capitalului)
5. Discrepanțe Cross-Platform (aceeași mașină la preț mai mic pe alt site)

Salvează raportul în format Markdown & HTML în `results/` și îl poate expedia automat
pe Discord, Telegram sau prin API.
"""

import os
import sys
import datetime
import requests
import pandas as pd
from typing import Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_db_stats, get_price_drops, DB_PATH
from liquidity_tracker import get_top_liquid_models
from cross_platform_matcher import find_cross_platform_duplicates
from deal_scorer import compute_deal_score


def generate_daily_market_report(
    db_path: str = DB_PATH,
    output_dir: str = "results",
    send_discord: bool = True,
    send_telegram: bool = True
) -> str:
    """
    Generează raportul complet de piață și îl salvează pe disc.
    """
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    today_display = datetime.datetime.now().strftime("%d %B %Y, %H:%M")
    os.makedirs(output_dir, exist_ok=True)

    stats = get_db_stats(db_path)
    drops_df = get_price_drops(days=3, min_drop_eur=200, db_path=db_path)
    top_liquid = get_top_liquid_models(limit=5, db_path=db_path)
    cross_matches = find_cross_platform_duplicates(min_price_diff_eur=300, db_path=db_path)

    # Colectăm cele mai bune oportunități de arbitraj
    from db_helper import get_new_listings_today
    new_cars = get_new_listings_today(db_path=db_path)

    arbitrage_deals = []
    if not new_cars.empty:
        # Evaluăm primele mașini compatibile
        model_path = "models/price_model.joblib"
        if os.path.exists(model_path):
            import joblib
            try:
                payload = joblib.load(model_path)
                ml_model = payload['model']
                features = payload.get('features', ['Brand', 'Model', 'Trim', 'year', 'mileage_km', 'fuel_type', 'engine_size'])

                from main import parse_car_title, infer_fuel_type, infer_engine_size
                df_eval = new_cars.copy().head(50)
                df_eval[['Brand', 'Model', 'Trim']] = df_eval['title'].apply(parse_car_title)
                df_eval['Trim'] = df_eval['Trim'].fillna('Standard')
                df_eval['fuel_type'] = df_eval.apply(infer_fuel_type, axis=1)
                df_eval['engine_size'] = df_eval.apply(infer_engine_size, axis=1).fillna(2.0)

                valid_mask = (
                    df_eval['Brand'].notna() & df_eval['Model'].notna() &
                    df_eval['year'].notna() & (df_eval['year'] >= 2010) &
                    df_eval['mileage_km'].notna() & (df_eval['mileage_km'] >= 100) &
                    df_eval['price_eur'].notna() & (df_eval['price_eur'] >= 1000)
                )
                candidates = df_eval[valid_mask].copy()
                if not candidates.empty:
                    candidates['pred_price'] = ml_model.predict(candidates[features])
                    for _, r in candidates.iterrows():
                        ds = compute_deal_score(
                            predicted_market_price=r['pred_price'],
                            asked_price=r['price_eur'],
                            brand=r['Brand'],
                            model=r['Model'],
                            year=int(r['year']),
                            mileage_km=int(r['mileage_km']),
                            fuel_type=r.get('fuel_type'),
                            seller_type=r.get('seller_type')
                        )
                        arbitrage_deals.append({
                            "title": str(r['title'])[:45],
                            "price": r['price_eur'],
                            "pred_price": r['pred_price'],
                            "deal_score": ds['deal_score'],
                            "badge": ds['badge'],
                            "net_profit": ds['financials']['net_profit_margin'],
                            "roi_pct": ds['financials']['net_roi_pct'],
                            "url": r.get('url', '')
                        })
            except Exception as e:
                print(f"[!] Eroare la evaluarea arbitrajului pentru raport: {e}")

    arbitrage_deals = sorted(arbitrage_deals, key=lambda x: x['deal_score'], reverse=True)[:5]

    # CONSTRUIRE RAPORT MARKDOWN
    md_lines = [
        f"# 📊 RAPORT ZILNIC DE PIAȚĂ AUTO (Market Intelligence)",
        f"> **Data Generării:** {today_display}  ",
        f"> **Univers Analizat:** {stats['total_listings']:,} anunțuri ({stats['active_listings']:,} active)  ",
        f"> **Platforme Monitorizate:** {', '.join(stats['sources'].keys())}",
        f"\n---\n",
        f"## 1. 📈 Tablou de Bord Global (Sinteză)",
        f"- **Anunțuri Active în Piață:** `{stats['active_listings']:,}`",
        f"- **Total Înregistrări Istorice de Preț:** `{stats['total_price_records']:,}`",
        f"- **Mașini cu Ieftiniri Înregistrate:** `{stats['cars_with_price_drops']:,}`",
        f"- **Ieftiniri Majore (Ultimele 3 zile >= 200€):** `{len(drops_df):,}`",
        f"\n---\n",
        f"## 2. 💎 Top 5 Oportunități de Arbitraj ale Zilei (Deal Score 0-100)"
    ]

    if arbitrage_deals:
        md_lines.append("| Mașină | Preț Vânzător | Valoare ML | Deal Score | Profit Net Estimat | ROI % |")
        md_lines.append("|---|---|---|---|---|---|")
        for d in arbitrage_deals:
            link = f"[{d['title']}]({d['url']})" if d['url'] else d['title']
            md_lines.append(
                f"| {link} | {d['price']:,.0f} € | {d['pred_price']:,.0f} € | **{d['deal_score']}/100** | +{d['net_profit']:,.0f} € | {d['roi_pct']}% |"
            )
    else:
        md_lines.append("*Nu s-au înregistrat oportunități noi de arbitraj peste pragul critic în acest interval.*")

    md_lines.append(f"\n---\n")
    md_lines.append(f"## 3. 🔻 Top Scăderi Majore de Preț (Recente)")
    if not drops_df.empty:
        md_lines.append("| Anunț | Platformă | Preț Vechi | Preț Nou | Ieftinire | Reducere % |")
        md_lines.append("|---|---|---|---|---|---|")
        for _, r in drops_df.head(5).iterrows():
            title = str(r['title'])[:38]
            link = f"[{title}]({r['url']})" if r.get('url') else title
            md_lines.append(
                f"| {link} | {str(r['source']).upper()} | {r['old_price']:,.0f} € | {r['new_price']:,.0f} € | **-{r['drop_eur']:,.0f} €** | -{r['drop_pct']}% |"
            )
    else:
        md_lines.append("*Nu s-au înregistrat scăderi recente peste 200 €.*")

    md_lines.append(f"\n---\n")
    md_lines.append(f"## 4. 🚀 Top Modele cu Cea Mai Mare Lichiditate (Viteză Vânzare)")
    if not top_liquid.empty:
        md_lines.append("| Marcă | Model | Segment An | Zile Mediane Vânzare | Cerere / Status | Scor Lichiditate |")
        md_lines.append("|---|---|---|---|---|---|")
        for _, r in top_liquid.iterrows():
            md_lines.append(
                f"| {r['brand']} | {r['model']} | {r['year_range']} | **{r['median_days_to_sell']:.0f} zile** | {r['liquidity_tier']} | {r['liquidity_score']}/100 |"
            )
    else:
        md_lines.append("*Date lichiditate în curs de calcul.*")

    if not cross_matches.empty:
        md_lines.append(f"\n---\n")
        md_lines.append(f"## 5. 🎯 Oportunități Cross-Platform (Aceeași Mașină la Prețuri Diferite)")
        md_lines.append("| Mașină | Sursă Ieftină | Preț Minim | Sursă Scumpă | Preț Maxim | Diferență Profitabilă |")
        md_lines.append("|---|---|---|---|---|---|")
        for _, r in cross_matches.head(5).iterrows():
            t = str(r['title'])[:35]
            md_lines.append(
                f"| {t} | [{r['cheapest_source']}]({r['cheapest_url']}) | **{r['cheapest_price_eur']:,.0f} €** | [{r['expensive_source']}]({r['expensive_url']}) | {r['expensive_price_eur']:,.0f} € | **+{r['price_diff_eur']:,.0f} € (-{r['savings_pct']}%)** |"
            )

    # 6. Oportunități de Import Vest -> România
    try:
        from cross_border_arbitrage import find_top_import_arbitrage_deals
        df_import = find_top_import_arbitrage_deals(db_path=db_path, min_profit_eur=1200.0, min_roi_pct=10.0, limit=5)
        if not df_import.empty:
            md_lines.append(f"\n---\n")
            md_lines.append(f"## 6. 🚢 Top Oportunități de Import Vest -> România (Germania, Austria, Olanda)")
            md_lines.append("| Țară | Model | Preț Extern | Piață România | Cost Import | Profit NET | ROI % | Link |")
            md_lines.append("|---|---|---|---|---|---|---|---|")
            for _, r in df_import.iterrows():
                t = str(r['title'])[:30]
                url_str = f"[Vezi Oferta]({r['url']})" if r.get('url') else "N/A"
                md_lines.append(
                    f"| **{r['origin_country']}** | {t} | {r['foreign_price_eur']:,.0f} € | {r['estimated_ro_price_eur']:,.0f} € | {r['import_expenses_eur']:,.0f} € | **+{r['net_profit_eur']:,.0f} €** | **+{r['roi_pct']:.1f}%** | {url_str} |"
                )
    except Exception:
        pass

    md_lines.append(f"\n---\n")
    md_lines.append(f"*Raport generat de motorul ScraperAnalistAutomobile. Utilizați pentru decizii informate de flipping și arbitraj auto.*")

    report_content = "\n".join(md_lines)
    report_filename = os.path.join(output_dir, f"daily_market_report_{today_str}.md")
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"[+] Raport zilnic salvat cu succes: {report_filename}")

    # Transmitere alerte sumare Discord / Telegram dacă sunt configurate
    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    summary_text = (
        f"📊 **RAPORT ZILNIC BURSA AUTO ({today_str})**\n"
        f"🚗 **Anunțuri Active:** {stats['active_listings']:,} | 🔻 **Ieftiniri Recente:** {len(drops_df)}\n"
        f"💎 **Top Chilipiruri:** {len(arbitrage_deals)} oportunități cu Deal Score ridicat\n"
        f"🎯 **Discrepanțe Cross-Platform:** {len(cross_matches)} mașini cu diferențe de preț"
    )

    if send_discord and discord_url:
        try:
            requests.post(discord_url, json={"content": summary_text}, timeout=10)
            print("    [OK Discord] Sumar raport zilnic expediat.")
        except Exception:
            pass

    if send_telegram and tg_token and tg_chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": tg_chat_id, "text": summary_text, "parse_mode": "Markdown"},
                timeout=10
            )
            print("    [OK Telegram] Sumar raport zilnic expediat.")
        except Exception:
            pass

    return report_filename


if __name__ == "__main__":
    print("=== TEST DAILY MARKET REPORTER ===")
    path = generate_daily_market_report(send_discord=False, send_telegram=False)
    print(f"Raport salvat la: {path}")
