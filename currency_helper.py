# FILE: currency_helper.py
"""
Modul de Gestionare Curs Valutar cu Fallback Multi-Nivel.
Nivel 1: Preluare curs oficial live BNR (Banca Națională a României) / Open API
Nivel 2: Curs salvat în cache local (data/fx_cache.json) dacă e recent (< 48h)
Nivel 3: Curs de rezervă (Hardcoded Default: 1 EUR = 5.09 RON, 1 USD = 4.75 RON)
"""

import os
import json
import time
import datetime
from typing import Dict, Any, Optional
import requests

from logger_config import logger

FX_CACHE_PATH = os.path.join("data", "fx_cache.json")
DEFAULT_RATES = {
    "EUR": 5.09,
    "USD": 4.75,
    "GBP": 5.95,
    "RON": 1.0
}


def fetch_live_bnr_rate(currency: str = "EUR") -> Optional[float]:
    """Încearcă preluarea cursului valutar dintr-un API public deschis BNR / Exchange."""
    currency = currency.upper().strip()
    if currency == "RON":
        return 1.0

    # API 1: bnr.ro xml feed sau open.er-api.com (gratuit, fără cheie, actualizat zilnic)
    urls = [
        f"https://open.er-api.com/v6/latest/{currency}",
        f"https://api.exchangerate-api.com/v4/latest/{currency}"
    ]

    for url in urls:
        try:
            resp = requests.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                ron_rate = data.get("rates", {}).get("RON")
                if ron_rate and 3.5 <= ron_rate <= 7.0:
                    return round(float(ron_rate), 4)
        except Exception as e:
            logger.debug(f"[FX] Eroare fetch live {currency} din {url}: {e}")

    return None


def get_cached_rate(currency: str) -> Optional[float]:
    """Citește rata din cache-ul local dacă fișierul există și e valid."""
    if not os.path.exists(FX_CACHE_PATH):
        return None
    try:
        with open(FX_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
            rates = cache.get("rates", {})
            return rates.get(currency)
    except Exception:
        return None


def save_to_cache(rates: Dict[str, float]):
    """Salvează ratele în cache-ul local."""
    os.makedirs(os.path.dirname(FX_CACHE_PATH), exist_ok=True)
    try:
        cache_data = {
            "rates": rates,
            "updated_at": datetime.datetime.now().isoformat(),
            "timestamp": time.time()
        }
        with open(FX_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        logger.debug(f"[FX] Nu s-a putut salva cache-ul FX: {e}")


def get_exchange_rate(currency: str = "EUR") -> Dict[str, Any]:
    """
    Returnează cursul valutar în RON pentru o monedă străină dată,
    folosind lanțul de fallback:
    1. Live API
    2. Cache disc
    3. Valoare prestabilită garantată
    """
    curr = currency.upper().strip()
    if curr in ["RON", "LEI"]:
        return {"rate": 1.0, "source": "identity", "currency": "RON"}

    # Nivel 1: Live API
    live_rate = fetch_live_bnr_rate(curr)
    if live_rate:
        # Actualizăm cache-ul
        current_cache = {}
        if os.path.exists(FX_CACHE_PATH):
            try:
                with open(FX_CACHE_PATH, "r", encoding="utf-8") as f:
                    current_cache = json.load(f).get("rates", {})
            except Exception:
                pass
        current_cache[curr] = live_rate
        save_to_cache(current_cache)
        return {"rate": live_rate, "source": "live_api", "currency": curr}

    # Nivel 2: Cache disc
    cached_rate = get_cached_rate(curr)
    if cached_rate:
        return {"rate": cached_rate, "source": "disk_cache", "currency": curr}

    # Nivel 3: Valoare prestabilită (Hardcoded Fallback)
    fallback_rate = DEFAULT_RATES.get(curr, 5.09)
    return {"rate": fallback_rate, "source": "hardcoded_fallback", "currency": curr}


def convert_to_eur(price: float, currency: str) -> float:
    """Convertește orice sumă în EUR folosind mecanismul de fallback."""
    if not price or price <= 0:
        return 0.0
    curr = str(currency).upper().strip()
    if curr == "EUR":
        return round(float(price), 2)
    elif curr in ["RON", "LEI"]:
        rate_info = get_exchange_rate("EUR")
        eur_ron_rate = rate_info["rate"]
        return round(float(price) / eur_ron_rate, 2)
    elif curr == "USD":
        usd_info = get_exchange_rate("USD")
        eur_info = get_exchange_rate("EUR")
        # USD -> RON -> EUR
        ron_val = float(price) * usd_info["rate"]
        return round(ron_val / eur_info["rate"], 2)
    return round(float(price), 2)
