# FILE: base_scraper.py
"""
Clasă de bază abstractă (BaseScraper) pentru toate scraperele din sistem.
Elimină duplicarea de cod, unifică gestionarea erorilor, rotirea de User-Agent,
retry-ul cu backoff exponențial, early stopping-ul și salvarea în SQLite.
"""

import sys
import time
import random
import abc
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import requests

from db_helper import save_scraped_data, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Pool de User-Agent-uri moderne
USER_AGENTS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
]


class BaseScraper(abc.ABC):
    def __init__(self, source_name: str, db_path: str = DB_PATH):
        self.source_name = source_name.lower()
        self.db_path = db_path
        self.session = requests.Session()
        self.rotate_user_agent()

    def rotate_user_agent(self):
        """Alege un User-Agent aleatoriu."""
        ua = random.choice(USER_AGENTS_POOL)
        self.session.headers.update({
            "User-Agent": ua,
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Connection": "keep-alive"
        })

    def random_sleep(self, min_sec: float = 1.0, max_sec: float = 2.5):
        """Pauză politicoasă aleatorie cu jitter pentru a evita rate-limiting."""
        time.sleep(random.uniform(min_sec, max_sec))

    def fetch_with_retry(self, url: str, max_retries: int = 3, timeout: int = 15) -> Optional[requests.Response]:
        """Efectuează cerere HTTP cu retry exponențial și fallback automat la Cloudscraper / Proxy."""
        delay = 2.0
        for attempt in range(1, max_retries + 1):
            try:
                self.rotate_user_agent()
                resp = self.session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code in [403, 503] and ("cloudflare" in resp.text.lower() or "challenge" in resp.text.lower()):
                    print(f"[{self.source_name}] Challenge Cloudflare detectat. Declanșăm lanțul de fallback...")
                    from fallback_engine import fetch_with_full_fallback
                    html, status, method = fetch_with_full_fallback(url, session=self.session, timeout=timeout)
                    if html and status == 200:
                        # Simulăm un obiect response requests
                        mock_resp = requests.Response()
                        mock_resp.status_code = 200
                        mock_resp._content = html.encode('utf-8')
                        return mock_resp
                    time.sleep(delay)
                    delay *= 2.0
                elif resp.status_code in [429, 502, 503, 504]:
                    print(f"[{self.source_name}] Status {resp.status_code} la {url}. Reîncercare în {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    print(f"[{self.source_name}] Cod neașteptat {resp.status_code} la {url}")
                    return None
            except requests.RequestException as e:
                print(f"[{self.source_name}] Eroare rețea la încercarea {attempt}/{max_retries}: {e}")
                time.sleep(delay)
                delay *= 2.0

        # Fallback de ultimă instanță prin motorul centralizat
        try:
            from fallback_engine import fetch_with_full_fallback
            html, status, method = fetch_with_full_fallback(url, session=self.session, timeout=timeout)
            if html and status == 200:
                mock_resp = requests.Response()
                mock_resp.status_code = 200
                mock_resp._content = html.encode('utf-8')
                return mock_resp
        except Exception:
            pass

        return None

    @abc.abstractmethod
    def scrape_listings(self, max_pages: int = 5, daily_mode: bool = True) -> pd.DataFrame:
        """Metodă abstractă pe care fiecare scraper specific o implementează."""
        pass

    def save_to_db(self, df: pd.DataFrame) -> Dict[str, int]:
        """Salvează automat datele extrase în SQLite."""
        return save_scraped_data(df, self.source_name, self.db_path)
