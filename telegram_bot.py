# FILE: telegram_bot.py
"""
Bot Telegram Interactiv pentru Radarul Comercial Auto.
Permite evaluarea instantanee de pe telefon când utilizatorul este în teren,
la o vizionare sau la un târg auto.

Comenzi acceptate:
- /start sau /help : Meniu și instrucțiuni de utilizare
- /check <marca> <model> <an> <km> [combustibil] [pret] : Evaluare ML instant + Deal Score
- /top : Cele mai profitabile oportunități de arbitraj ale zilei
- /drops : Ultimele mașini cu preț redus
- /stats : Statistici la zi despre bursa auto
- /trends : Modele cu cele mai bune trenduri de preț

Funcționează autonom prin Telegram Bot API (polling simplu și eficient).
"""

import os
import sys
import re
import time
import datetime
import requests
from typing import Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_db_stats, get_price_drops, DB_PATH
from deal_scorer import compute_deal_score
from maintenance_estimator import calculate_net_profit


def send_tg_message(token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Trimite un mesaj către un utilizator Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"[!] Eroare trimitere Telegram: {e}")
        return False


def handle_check_command(args: list) -> str:
    """
    Procesează comanda /check:
    Format: /check BMW Seria 3 2019 140000 Diesel 13500
    sau: /check VW Golf 2018 160000 9500
    """
    if len(args) < 4:
        return (
            "⚠️ **Format incorect!**\n"
            "Folosește: `/check <Brand> <Model> <An> <KM> [Combustibil] [PrețCerut]`\n\n"
            "Exemplu: `/check BMW Seria 3 2019 140000 Diesel 13500`\n"
            "sau: `/check Volkswagen Golf 2018 150000 9800`"
        )

    raw_text = " ".join(args)

    # Identificăm an, km, preț cu regex curat
    # Căutăm an (4 cifre între 2005 și 2026)
    year_match = re.search(r'\b(20[0-2]\d)\b', raw_text)
    year = int(year_match.group(1)) if year_match else 2018

    # Căutăm kilometraj (număr >= 5000)
    km_matches = re.findall(r'\b(\d{4,6})\b', raw_text)
    km = 140000
    for k in km_matches:
        val = int(k)
        if 5000 <= val <= 500000 and val != year:
            km = val
            break

    # Căutăm preț cerut (număr între 500 și 150000 diferit de an și km)
    price_matches = re.findall(r'\b(\d{3,6})\b', raw_text)
    asked_price = 12000.0
    for p in reversed(price_matches):
        val = float(p)
        if 500 <= val <= 150000 and val != year and val != km:
            asked_price = val
            break

    # Eliminăm cifrele găsite pentru a extrage marca și modelul
    clean_text = raw_text
    for n in [year, km, int(asked_price)]:
        clean_text = re.sub(rf'\b{n}\b', ' ', clean_text)

    # Detectăm combustibil
    fuel = "Diesel"
    for cand in ['diesel', 'benzina', 'hibrid', 'hybrid', 'gpl', 'electric']:
        if re.search(rf'\b{cand}\b', clean_text, re.IGNORECASE):
            fuel = cand.capitalize()
            clean_text = re.sub(rf'\b{cand}\b', ' ', clean_text, flags=re.IGNORECASE)
            break

    tokens = [t for t in clean_text.split() if t]
    brand = tokens[0].title() if tokens else "Volkswagen"
    model = " ".join(tokens[1:]).title() if len(tokens) > 1 else "Golf"

    # Evaluare folosind motorul de estimare multi-tier (XGBoost -> RF -> DB Stats -> Euristic)
    from valuation_engine import valuation_engine
    val_res = valuation_engine.estimate_price(
        brand=brand,
        model=model,
        year=year,
        mileage_km=km,
        fuel_type=fuel
    )
    pred_price = val_res["predicted_price_eur"]
    engine_details = val_res["model_details"]

    ds = compute_deal_score(
        predicted_market_price=pred_price,
        asked_price=asked_price,
        brand=brand,
        model=model,
        year=year,
        mileage_km=km,
        fuel_type=fuel
    )

    badge = ds['badge']
    fin = ds['financials']

    msg = (
        f"🚗 **EVALUARE RAPIDĂ: {brand} {model} ({year})**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Preț Vânzător:** {asked_price:,.0f} €\n"
        f"📈 **Valoare Reală ML:** {pred_price:,.0f} €\n"
        f"🔧 **Cost Recondiționare:** {fin['maintenance_cost']:,.0f} €\n"
        f"🟢 **Profit Net Real:** {fin['net_profit_margin']:+,.0f} € (ROI: {fin['net_roi_pct']}%)\n\n"
        f"🎯 **Deal Score:** `{ds['deal_score']}/100`\n"
        f"🎖️ **Verdict:** {badge}\n\n"
        f"💡 **Recomandare de Negociere:**\n"
        f"Oferă vânzătorului: **{ds['target_buy_offer_eur']:,.0f} €**\n"
        f"{ds['recommendation']}"
    )
    return msg


def handle_top_command() -> str:
    """Returnează top 5 oportunități recente de arbitraj."""
    from db_helper import get_new_listings_today
    df = get_new_listings_today()
    if df.empty:
        return "ℹ️ Nu sunt înregistrate anunțuri noi astăzi pentru arbitraj."

    lines = ["💎 **TOP OPORTUNITĂȚI DE ARBITRAJ ALE ZILEI:**\n━━━━━━━━━━━━━━━━━━━━"]
    for idx, r in df.head(5).iterrows():
        title = str(r['title'])[:35]
        p = r['price_eur']
        url = r.get('url', '')
        link = f" [🔗 Link]({url})" if url else ""
        lines.append(f"• **{title}** | {p:,.0f} €{link}")

    return "\n".join(lines)


def handle_drops_command() -> str:
    """Returnează top scăderi recente de preț."""
    drops = get_price_drops(days=3, min_drop_eur=200)
    if drops.empty:
        return "ℹ️ Nu s-au detectat scăderi de preț mai mari de 200 € în ultimele 3 zile."

    lines = ["📉 **TOP SCĂDERI RECENTE DE PREȚ (Ultimele 3 zile):**\n━━━━━━━━━━━━━━━━━━━━"]
    for idx, r in drops.head(6).iterrows():
        title = str(r['title'])[:32]
        old_p = r['old_price']
        new_p = r['new_price']
        drop = r['drop_eur']
        pct = r['drop_pct']
        lines.append(f"🔻 **{title}**: {old_p:,.0f}€ -> **{new_p:,.0f}€** (-{drop:,.0f}€ / -{pct}%)")

    return "\n".join(lines)


def handle_stats_command() -> str:
    """Returnează statistici globale despre baza de date."""
    stats = get_db_stats()
    return (
        f"📊 **STATISTICI BURSA AUTO ROMÂNIA:**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚗 **Total Anunțuri Monitorizate:** `{stats['total_listings']:,}`\n"
        f"🟢 **Anunțuri Active în Prezent:** `{stats['active_listings']:,}`\n"
        f"📉 **Total Înregistrări Istorice Preț:** `{stats['total_price_records']:,}`\n"
        f"🔻 **Mașini Ieftinite cel puțin o dată:** `{stats['cars_with_price_drops']:,}`\n"
        f"🌐 **Platforme:** {', '.join(stats['sources'].keys())}"
    )


def process_message(text: str) -> str:
    """Dispecer central de comenzi pentru botul Telegram."""
    t = text.strip()
    if t.startswith("/start") or t.startswith("/help"):
        return (
            "👋 **Bine ai venit la Radarul Comercial Auto!**\n\n"
            "Comenzi disponibile:\n"
            "• `/check <Marca> <Model> <An> <KM> [Preț]` - Evaluează instant o mașină din teren\n"
            "• `/top` - Top oportunități de arbitraj ale zilei\n"
            "• `/drops` - Ultimele scăderi mari de preț\n"
            "• `/stats` - Statistici despre piața auto\n\n"
            "Exemplu: `/check BMW Seria 3 2019 140000 13500`"
        )
    elif t.startswith("/check"):
        args = t[6:].strip().split()
        return handle_check_command(args)
    elif t.startswith("/top"):
        return handle_top_command()
    elif t.startswith("/drops"):
        return handle_drops_command()
    elif t.startswith("/stats"):
        return handle_stats_command()
    else:
        return "Comandă necunoscută. Scrie `/help` pentru lista de comenzi."


def run_telegram_polling():
    """Rulează bucla de polling Telegram dacă variabila TELEGRAM_BOT_TOKEN este configurată."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[!] TELEGRAM_BOT_TOKEN nu este setat în mediul de execuție.")
        return

    print(f"[*] Pornim botul Telegram în mod polling...")
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    msg = item.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if chat_id and text:
                        reply = process_message(text)
                        send_tg_message(token, str(chat_id), reply)
        except Exception as e:
            time.sleep(3)


if __name__ == "__main__":
    print("=== TEST TELEGRAM BOT COMMAND DISPATCHER ===")
    test_eval = process_message("/check BMW Seria 3 2019 140000 13200")
    print(test_eval)
    print("\nTest /stats:")
    print(process_message("/stats"))
