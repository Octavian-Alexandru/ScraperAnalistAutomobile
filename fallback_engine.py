# FILE: fallback_engine.py
"""
Motor Centralizat de Reziliență și Fallback pe Toate Sistemele.
Implementează mecanisme de recuperare automată (fail-safe) pentru:
1. Rețea & Descărcare: Direct HTTP -> Cloudscraper -> Proxy Pool -> Playwright
2. Parsare HTML: Selectori CSS primari -> Selectori secundari -> JSON-LD / Schema.org -> OpenGraph & Regex
3. Buffer de Urgență Date: Salvare în JSONL tampon când baza de date este blocată și re-procesare automată
4. Coadă de Alertare Outbox: Salvare notificări eșuate pe disc și re-trimitere automată
"""

import os
import re
import json
import time
import random
import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable
import requests
from bs4 import BeautifulSoup

from logger_config import logger

OUTBOX_PATH = os.path.join("data", "alerts_outbox.jsonl")
RECOVERY_BUFFER_PATH = os.path.join("data", "recovery_buffer.jsonl")


# =====================================================================
# 1. RETEA: LANȚ DE FALLBACK PENTRU DESCĂRCARE PAGINI
# =====================================================================

def fetch_with_full_fallback(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: int = 15,
    try_proxy: bool = True,
    try_playwright: bool = False
) -> Tuple[Optional[str], int, str]:
    """
    Descarcă o pagină web traversând lanțul de fallback:
    Nivel 1: requests direct cu header-e moderne
    Nivel 2: cloudscraper (bypass Cloudflare/Akamai challenge)
    Nivel 3: proxy din ProxyManager (dacă e 403, 429 sau conexiune refuzată)
    Nivel 4: Playwright Headless (dacă e instalat și activat)

    Returnează: (html_content, status_code, method_used)
    """
    sess = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8",
        "Connection": "keep-alive"
    }

    # --- Nivel 1: Cerere HTTP directă ---
    try:
        resp = sess.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.text, 200, "direct_http"
        elif resp.status_code in [403, 503] and ("cloudflare" in resp.text.lower() or "challenge" in resp.text.lower()):
            logger.info(f"[FallbackEngine] Challenge Cloudflare la {url}. Trecem la Nivelul 2 (cloudscraper)...")
        elif resp.status_code == 429:
            logger.warning(f"[FallbackEngine] Rate-limit (429) la {url}. Trecem la Nivelul 3 (proxy)...")
        else:
            logger.debug(f"[FallbackEngine] HTTP status {resp.status_code} la {url}")
    except requests.RequestException as e:
        logger.debug(f"[FallbackEngine] Nivel 1 eșuat ({e}). Trecem la Nivelul 2...")

    # --- Nivel 2: Cloudscraper ---
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        cs_resp = scraper.get(url, timeout=timeout + 5)
        if cs_resp.status_code == 200:
            return cs_resp.text, 200, "cloudscraper"
    except Exception as e:
        logger.debug(f"[FallbackEngine] Nivel 2 (cloudscraper) eșuat: {e}")

    # --- Nivel 3: Proxy din ProxyManager ---
    if try_proxy:
        try:
            from proxy_manager import get_proxy_manager
            pm = get_proxy_manager(fetch_free=False)
            proxy_addr = pm.get_best_proxy()
            if proxy_addr:
                t0 = time.time()
                p_resp = sess.get(
                    url,
                    headers=headers,
                    proxies={"http": proxy_addr, "https": proxy_addr},
                    timeout=timeout
                )
                lat = (time.time() - t0) * 1000
                if p_resp.status_code == 200:
                    pm.record_result(proxy_addr, True, lat)
                    return p_resp.text, 200, "proxy"
                else:
                    pm.record_result(proxy_addr, False)
        except Exception as e:
            logger.debug(f"[FallbackEngine] Nivel 3 (proxy) eșuat: {e}")

    # --- Nivel 4: Playwright (Headless Browser) ---
    if try_playwright:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=headers["User-Agent"])
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                content = page.content()
                browser.close()
                if content and len(content) > 500:
                    return content, 200, "playwright"
        except Exception as e:
            logger.debug(f"[FallbackEngine] Nivel 4 (playwright) eșuat: {e}")

    return None, 0, "failed_all"


# =====================================================================
# 2. PARSARE HTML: FALLBACK STRUCTURAT (JSON-LD & SCHEMA.ORG)
# =====================================================================

def extract_json_ld_car_data(html_or_soup: Any) -> List[Dict[str, Any]]:
    """
    Extrage automat obiecte de tip 'Car', 'Vehicle', 'Product', 'Offer'
    din etichetele <script type="application/ld+json">.
    Funcționează ca fallback universal când selectorii CSS din pagină sunt schimbați!
    """
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(str(html_or_soup), "html.parser")
    found_items = []

    scripts = soup.find_all("script", type=lambda t: t and "ld+json" in t.lower())
    for s in scripts:
        if not s.string:
            continue
        try:
            data = json.loads(s.string.strip())
            # Poate fi un singur obiect sau o listă sau un @graph
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "@graph" in data:
                    items = data["@graph"]
                else:
                    items = [data]

            for item in items:
                item_type = str(item.get("@type", "")).lower()
                if any(t in item_type for t in ["car", "vehicle", "product", "autovehicul"]):
                    # Extragem proprietățile standard Schema.org
                    offers = item.get("offers", {})
                    if isinstance(offers, list) and offers:
                        offers = offers[0]

                    price = None
                    currency = "EUR"
                    if isinstance(offers, dict):
                        raw_price = offers.get("price")
                        currency = offers.get("priceCurrency", "EUR")
                        if raw_price:
                            try:
                                price = float(str(raw_price).replace(",", "."))
                            except ValueError:
                                pass

                    brand = item.get("brand")
                    if isinstance(brand, dict):
                        brand = brand.get("name", "")

                    model = item.get("model")
                    if isinstance(model, dict):
                        model = model.get("name", "")

                    mileage = item.get("mileageFromOdometer")
                    if isinstance(mileage, dict):
                        mileage = mileage.get("value")

                    try:
                        mileage = int(mileage) if mileage is not None else None
                    except (ValueError, TypeError):
                        mileage = None

                    year = item.get("productionDate") or item.get("modelDate") or item.get("vehicleModelDate")
                    try:
                        if year:
                            year_int = int(str(year)[:4])
                            if 1990 <= year_int <= 2027:
                                year = year_int
                            else:
                                year = None
                    except Exception:
                        year = None

                    found_items.append({
                        "title": item.get("name") or f"{brand} {model}".strip(),
                        "brand": brand,
                        "model": model,
                        "price": price,
                        "currency": currency,
                        "year": year,
                        "mileage_km": mileage,
                        "fuel_type": item.get("fuelType"),
                        "description": item.get("description"),
                        "url": offers.get("url") if isinstance(offers, dict) else item.get("url"),
                        "source_schema": "json_ld"
                    })
        except Exception:
            continue

    return found_items


def extract_regex_card_fallback(text: str) -> Dict[str, Any]:
    """
    Extrage euristic prin expresii regulate anul, kilometrajul și prețul
    din textul brut al unui anunț/card când selectorii specifici eșuează.
    """
    if not text:
        return {}
    clean = " ".join(text.split())

    data = {}

    # 1. Căutare An (2005 - 2026)
    m_year = re.search(r'\b(20[0-2]\d)\b', clean)
    if m_year:
        data["year"] = int(m_year.group(1))

    # 2. Căutare KM (ex: "145.000 km", "145 000 km", "145000km")
    m_km = re.search(r'(\d{1,3}[\s.,]?\d{3})\s*(?:km|de\s*km)\b', clean, re.IGNORECASE)
    if m_km:
        digits = re.sub(r'\D', '', m_km.group(1))
        if digits:
            data["mileage_km"] = int(digits)

    # 3. Căutare Preț (ex: "14.500 €", "14500 EUR", "65.000 lei")
    m_price = re.search(r'(\d{1,3}[\s.,]?\d{3})\s*(?:€|eur|euro|lei|ron)\b', clean, re.IGNORECASE)
    if m_price:
        digits = re.sub(r'\D', '', m_price.group(1))
        if digits:
            data["price"] = float(digits)
            if any(c in m_price.group(0).lower() for c in ['lei', 'ron']):
                data["currency"] = "RON"
            else:
                data["currency"] = "EUR"

    # 4. Combustibil
    for f in ["diesel", "benzina", "hibrid", "hybrid", "electric", "gpl"]:
        if re.search(rf'\b{f}\b', clean, re.IGNORECASE):
            data["fuel_type"] = f.capitalize()
            break

    return data


# =====================================================================
# 3. BUFFER DE RECUPERARE DATE PENTRU BAZA DE DATE (RECOVERY BUFFER)
# =====================================================================

class DatabaseRecoveryBuffer:
    """
    Buffer persistent pe disc (data/recovery_buffer.jsonl).
    Când SQLite este blocată (OperationalError, database locked) sau eșuează,
    datele extrase sunt salvate garantat aici și re-inserate automat
    la următoarea conexiune reușită.
    """

    @staticmethod
    def append_failed_records(source_name: str, records: List[Dict[str, Any]]):
        """Salvează înregistrările eșuate în buffer-ul de urgență."""
        if not records:
            return
        os.makedirs(os.path.dirname(RECOVERY_BUFFER_PATH), exist_ok=True)
        now_iso = datetime.datetime.now().isoformat()
        try:
            with open(RECOVERY_BUFFER_PATH, "a", encoding="utf-8") as f:
                for r in records:
                    entry = {
                        "source": source_name,
                        "buffered_at": now_iso,
                        "data": r
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.warning(f"[RecoveryBuffer] Salvat {len(records)} anunțuri din '{source_name}' în buffer-ul de urgență!")
        except Exception as e:
            logger.error(f"[RecoveryBuffer] Eroare gravă la scrierea în buffer: {e}")

    @staticmethod
    def drain_buffer_to_sqlite(db_save_fn: Callable[[Any, str], Dict[str, int]]) -> int:
        """
        Drenează (re-inserează) toate înregistrările din buffer-ul de urgență în SQLite.
        Dacă inserarea reușește, golește fișierul de recuperare.
        """
        if not os.path.exists(RECOVERY_BUFFER_PATH):
            return 0

        entries_by_source: Dict[str, List[Dict[str, Any]]] = {}
        total_read = 0

        try:
            with open(RECOVERY_BUFFER_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        src = obj.get("source", "unknown")
                        d = obj.get("data", {})
                        if d:
                            entries_by_source.setdefault(src, []).append(d)
                            total_read += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[RecoveryBuffer] Nu s-a putut citi buffer-ul: {e}")
            return 0

        if not entries_by_source:
            # Fișier gol, îl curățăm
            try:
                os.remove(RECOVERY_BUFFER_PATH)
            except Exception:
                pass
            return 0

        logger.info(f"[RecoveryBuffer] Încercăm re-inserarea a {total_read} anunțuri recuperate din buffer...")
        reingested = 0
        all_success = True

        import pandas as pd
        for src, records in entries_by_source.items():
            try:
                df = pd.DataFrame(records)
                stats = db_save_fn(df, src)
                reingested += (stats.get("new", 0) + stats.get("updated", 0))
                logger.info(f"[RecoveryBuffer] Re-inserat {len(records)} anunturi din '{src}': {stats}")
            except Exception as e:
                logger.error(f"[RecoveryBuffer] Eșec la re-inserarea sursei '{src}': {e}")
                all_success = False

        if all_success:
            try:
                os.remove(RECOVERY_BUFFER_PATH)
                logger.info(f"[RecoveryBuffer] Buffer-ul a fost drenat complet ({total_read} articole procesate) și șters.")
            except Exception:
                pass

        return reingested


# =====================================================================
# 4. COADĂ DE ALERTĂRI (OUTBOX PERSISTENT)
# =====================================================================

class AlertOutboxManager:
    """
    Gestionează mesajele și alertele care nu au putut fi transmise prin rețea
    (Telegram rate limit, Discord offline, SMTP picat).
    Salvează notificările în data/alerts_outbox.jsonl și le re-trimite automat.
    """

    @staticmethod
    def enqueue_alert(channel: str, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Salvează o alertă în coada offline."""
        os.makedirs(os.path.dirname(OUTBOX_PATH), exist_ok=True)
        payload = {
            "channel": channel,
            "message": message,
            "metadata": metadata or {},
            "created_at": datetime.datetime.now().isoformat(),
            "retry_count": 0
        }
        try:
            with open(OUTBOX_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            logger.info(f"[AlertOutbox] Alerta salvată în outbox pentru canalul '{channel}'.")
        except Exception as e:
            logger.error(f"[AlertOutbox] Eroare la scrierea alertei în outbox: {e}")

    @staticmethod
    def get_pending_alerts() -> List[Dict[str, Any]]:
        """Citește alertele în așteptare."""
        if not os.path.exists(OUTBOX_PATH):
            return []
        items = []
        try:
            with open(OUTBOX_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            items.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
        return items

    @staticmethod
    def clear_outbox():
        """Șterge alertele din outbox după re-trimitere cu succes."""
        if os.path.exists(OUTBOX_PATH):
            try:
                os.remove(OUTBOX_PATH)
            except Exception:
                pass


# Instanțe singleton
recovery_buffer = DatabaseRecoveryBuffer()
alert_outbox = AlertOutboxManager()
