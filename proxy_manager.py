# FILE: proxy_manager.py
"""
Manager Inteligent de Proxy-uri cu Rotire Automată.
Implementează:
1. Pool de proxy-uri cu scor de sănătate (latență, rata de succes)
2. Fetch automat de proxy-uri gratuite din surse publice
3. Fallback chain: direct → proxy → cloudscraper → None
4. Blacklist automat a proxy-urilor moarte
5. Integrare cu ScraperAPI / Bright Data prin env vars (opțional)
"""

import os
import sys
import time
import random
import threading
from typing import Dict, Any, List, Optional, Tuple
import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from logger_config import logger


class ProxyHealth:
    """Urmărește starea de sănătate a unui proxy individual."""
    def __init__(self, address: str):
        self.address = address
        self.success_count = 0
        self.fail_count = 0
        self.avg_latency_ms = 0.0
        self.last_used = 0.0
        self.is_alive = True

    @property
    def score(self) -> float:
        """Scor 0-100 bazat pe rata de succes și latență."""
        total = self.success_count + self.fail_count
        if total == 0:
            return 50.0  # proxy neîncercat = scor neutru
        success_rate = self.success_count / total
        latency_penalty = min(self.avg_latency_ms / 5000.0, 1.0)  # penalizare dacă > 5s
        return round((success_rate * 70) + ((1 - latency_penalty) * 30), 1)

    def record_success(self, latency_ms: float):
        self.success_count += 1
        alpha = 0.3  # exponential moving average
        self.avg_latency_ms = (alpha * latency_ms) + ((1 - alpha) * self.avg_latency_ms)
        self.last_used = time.time()
        self.is_alive = True

    def record_failure(self):
        self.fail_count += 1
        self.last_used = time.time()
        if self.fail_count >= 3 and self.success_count == 0:
            self.is_alive = False


# Surse gratuite de proxy-uri
FREE_PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]


class ProxyManager:
    """
    Manager central de proxy-uri cu rotire inteligentă și health tracking.
    Poate funcționa fără proxy-uri (mod direct) sau cu pool dinamic.
    """

    def __init__(
        self,
        custom_proxies: Optional[List[str]] = None,
        fetch_free: bool = True,
        max_pool_size: int = 30,
        scraper_api_key: Optional[str] = None
    ):
        self.pool: Dict[str, ProxyHealth] = {}
        self.max_pool_size = max_pool_size
        self._lock = threading.Lock()

        # ScraperAPI / Bright Data key din env sau parametru
        self.scraper_api_key = scraper_api_key or os.getenv("SCRAPER_API_KEY", "")
        self.bright_data_proxy = os.getenv("BRIGHT_DATA_PROXY", "")

        # Încarcă proxy-urile custom
        if custom_proxies:
            for p in custom_proxies[:max_pool_size]:
                self.pool[p] = ProxyHealth(p)

        # Fetch proxy-uri gratuite
        if fetch_free and len(self.pool) < max_pool_size:
            self._fetch_free_proxies()

        logger.info(f"[ProxyManager] Pool inițializat cu {len(self.pool)} proxy-uri. "
                    f"ScraperAPI: {'DA' if self.scraper_api_key else 'NU'}.")

    def _fetch_free_proxies(self):
        """Descarcă proxy-uri gratuite din surse publice."""
        collected = []
        for source_url in FREE_PROXY_SOURCES:
            try:
                resp = requests.get(source_url, timeout=10)
                if resp.status_code == 200:
                    lines = resp.text.strip().split('\n')
                    for line in lines:
                        proxy = line.strip()
                        if proxy and ':' in proxy:
                            collected.append(f"http://{proxy}")
            except Exception as e:
                logger.debug(f"[ProxyManager] Nu am putut descărca proxy-uri din {source_url}: {e}")

        if collected:
            random.shuffle(collected)
            added = 0
            for p in collected[:self.max_pool_size - len(self.pool)]:
                if p not in self.pool:
                    self.pool[p] = ProxyHealth(p)
                    added += 1
            logger.info(f"[ProxyManager] Am adăugat {added} proxy-uri gratuite din surse publice.")

    def get_best_proxy(self) -> Optional[str]:
        """Returnează cel mai bun proxy disponibil (scor maxim) sau None dacă pool gol."""
        with self._lock:
            alive = {addr: ph for addr, ph in self.pool.items() if ph.is_alive}
            if not alive:
                return None

            # Sortare după scor descrescător, cu un pic de randomizare (top 5)
            sorted_proxies = sorted(alive.values(), key=lambda ph: ph.score, reverse=True)
            top_n = sorted_proxies[:min(5, len(sorted_proxies))]
            chosen = random.choice(top_n)
            return chosen.address

    def get_random_proxy(self) -> Optional[str]:
        """Returnează un proxy aleatoriu viu."""
        with self._lock:
            alive = [addr for addr, ph in self.pool.items() if ph.is_alive]
            return random.choice(alive) if alive else None

    def get_scraper_api_url(self, target_url: str) -> Optional[str]:
        """Generează URL ScraperAPI dacă e configurat."""
        if self.scraper_api_key:
            return f"http://api.scraperapi.com/?api_key={self.scraper_api_key}&url={target_url}"
        return None

    def record_result(self, proxy_address: str, success: bool, latency_ms: float = 0.0):
        """Înregistrează rezultatul folosirii unui proxy."""
        with self._lock:
            if proxy_address in self.pool:
                if success:
                    self.pool[proxy_address].record_success(latency_ms)
                else:
                    self.pool[proxy_address].record_failure()

    def remove_dead_proxies(self):
        """Elimină proxy-urile cu scor sub 10 sau marcate ca moarte."""
        with self._lock:
            dead = [addr for addr, ph in self.pool.items() if not ph.is_alive or ph.score < 10]
            for addr in dead:
                del self.pool[addr]
            if dead:
                logger.info(f"[ProxyManager] Am eliminat {len(dead)} proxy-uri moarte din pool.")

    def refresh_pool(self):
        """Reîmprospătează pool-ul: elimină moartele și descarcă proxy-uri noi."""
        self.remove_dead_proxies()
        if len(self.pool) < self.max_pool_size // 2:
            self._fetch_free_proxies()

    def fetch_with_fallback(
        self,
        url: str,
        session: Optional[requests.Session] = None,
        timeout: int = 15,
        max_retries: int = 2
    ) -> Optional[requests.Response]:
        """
        Lanț de fallback inteligent:
        1. Cerere directă (fără proxy)
        2. Cu proxy din pool (cel mai bun scor)
        3. ScraperAPI (dacă e configurat)
        """
        sess = session or requests.Session()

        # --- Pasul 1: Cerere directă ---
        try:
            t0 = time.time()
            resp = sess.get(url, timeout=timeout)
            latency = (time.time() - t0) * 1000
            if resp.status_code == 200:
                return resp
            elif resp.status_code not in [403, 429, 503]:
                return resp  # alte coduri non-blocare → le returnăm
        except requests.RequestException:
            pass

        # --- Pasul 2: Proxy din pool ---
        for attempt in range(max_retries):
            proxy_addr = self.get_best_proxy()
            if not proxy_addr:
                break

            try:
                t0 = time.time()
                resp = sess.get(url, proxies={"http": proxy_addr, "https": proxy_addr}, timeout=timeout)
                latency = (time.time() - t0) * 1000
                if resp.status_code == 200:
                    self.record_result(proxy_addr, True, latency)
                    return resp
                else:
                    self.record_result(proxy_addr, False)
            except requests.RequestException:
                self.record_result(proxy_addr, False)

        # --- Pasul 3: ScraperAPI (dacă e configurat) ---
        api_url = self.get_scraper_api_url(url)
        if api_url:
            try:
                resp = sess.get(api_url, timeout=timeout + 10)
                if resp.status_code == 200:
                    return resp
            except requests.RequestException:
                pass

        return None

    def get_pool_stats(self) -> Dict[str, Any]:
        """Returnează statistici despre pool-ul de proxy-uri."""
        alive = sum(1 for ph in self.pool.values() if ph.is_alive)
        avg_score = sum(ph.score for ph in self.pool.values()) / max(1, len(self.pool))
        return {
            "total_proxies": len(self.pool),
            "alive_proxies": alive,
            "dead_proxies": len(self.pool) - alive,
            "average_score": round(avg_score, 1),
            "scraper_api_configured": bool(self.scraper_api_key),
            "bright_data_configured": bool(self.bright_data_proxy)
        }


# Instanță singleton globală (lazy init)
_global_proxy_manager: Optional[ProxyManager] = None


def get_proxy_manager(fetch_free: bool = True) -> ProxyManager:
    """Returnează instanța globală singleton a ProxyManager."""
    global _global_proxy_manager
    if _global_proxy_manager is None:
        custom = os.getenv("PROXY_LIST", "").split(",") if os.getenv("PROXY_LIST") else None
        _global_proxy_manager = ProxyManager(custom_proxies=custom, fetch_free=fetch_free)
    return _global_proxy_manager


if __name__ == "__main__":
    print("=== TEST PROXY MANAGER ===")
    pm = ProxyManager(fetch_free=True, max_pool_size=10)
    stats = pm.get_pool_stats()
    print(f"Pool stats: {stats}")
    best = pm.get_best_proxy()
    print(f"Best proxy: {best}")
