# FILE: crawler_engine.py
"""
Motor Multi-Agent de Crawling de Mare Viteză (High-Speed Multi-Agent Crawler Engine).
Proiectat pentru:
1. Crawling adânc (Full-Site Deep Crawl) pe toate platformele auto suportate
2. Execuție coordonată cu 2-3 agenți per site/IP:
   - Fiecare agent procesează calupuri de 2-3 pagini pe rând
   - Delay inteligent cu jitter (1.2s - 2.6s) pentru a NU declanșa protecțiile Cloudflare / Akamai (WAF)
   - Rotire sesiune și User-Agent la fiecare batch
3. Colectare și procesare de mare viteză:
   - Parser C-accelerat `lxml` pentru viteză de 5-10x mai mare la parsare HTML
   - HTTP Connection Pooling cu Keep-Alive
   - Verificare instantanee O(1) a ID-urilor deja existente în SQLite
   - Salvare atomică în batch prin modul WAL
4. Cloudflare Bypass automat prin `cloudscraper` pe domenii protejate
"""

import os
import sys
import time
import random
import datetime
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from bs4 import BeautifulSoup
import requests
import cloudscraper

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import save_scraped_data, get_known_car_ids_and_prices, DB_PATH
from logger_config import logger

# Pool de User-Agent-uri browser reale
AGENT_FINGERPRINTS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.8,en-US;q=0.5,en;q=0.3"
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9"
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
        "Sec-Ch-Ua": '"Microsoft Edge";v="123", "Chromium";v="123"',
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8"
    }
]


class ScraperAgent:
    """Agent autonom de colectare pentru un număr limitat de pagini consecutive per sesiune/IP."""

    def __init__(self, agent_id: int, proxy: Optional[str] = None):
        self.agent_id = agent_id
        self.proxy = proxy
        self.session = None
        self.cloud_scraper = None
        self.init_session()

    def init_session(self):
        """Inițializează o sesiune proaspătă cu amprentă unică de browser."""
        self.session = requests.Session()
        headers = random.choice(AGENT_FINGERPRINTS)
        self.session.headers.update(headers)
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        # Sesiune Cloudflare de rezervă
        self.cloud_scraper = cloudscraper.create_scraper(
            sess=self.session,
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )

    def fetch_page_fast(self, url: str, timeout: int = 15) -> Optional[str]:
        """
        Descarcă conținutul HTML al unei pagini cu detecție Cloudflare și lanț complet de fallback.
        """
        # Delay politicoase între cereri pentru a nu declanșa rate limiter-ul WAF
        time.sleep(random.uniform(1.2, 2.6))
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in [403, 503] and ("cloudflare" in resp.text.lower() or "just a moment" in resp.text.lower()):
                logger.info(f"[Agent-{self.agent_id}] Challenge Cloudflare detectat la {url}. Aplicăm cloudscraper bypass...")
                cs_resp = self.cloud_scraper.get(url, timeout=timeout + 5)
                if cs_resp.status_code == 200:
                    return cs_resp.text
            else:
                logger.warning(f"[Agent-{self.agent_id}] Status {resp.status_code} la {url}. Declanșăm fallback centralizat...")
        except Exception as e:
            logger.error(f"[Agent-{self.agent_id}] Eroare rețea la {url}: {e}")

        # Fallback de urgență prin Fallback Engine
        try:
            from fallback_engine import fetch_with_full_fallback
            html, status, method = fetch_with_full_fallback(url, session=self.session, timeout=timeout)
            if html and status == 200:
                logger.info(f"[Agent-{self.agent_id}] Pagină recuperată cu succes prin fallback '{method}'!")
                return html
        except Exception:
            pass

        return None


class MultiAgentCrawlerEngine:
    """
    Orchestrator central de crawling multi-agent:
    Distribuie paginile de pe un site în calupuri de 2-3 pagini per agent.
    """

    def __init__(
        self,
        num_agents: int = 3,
        batch_size_per_agent: int = 3,
        db_path: str = DB_PATH
    ):
        self.num_agents = num_agents
        self.batch_size = batch_size_per_agent
        self.db_path = db_path
        self.agents = [ScraperAgent(i + 1) for i in range(num_agents)]

    def crawl_site(
        self,
        source_name: str,
        url_builder_fn: Callable[[int], str],
        card_parser_fn: Callable[[Any], Dict[str, Any]],
        card_selector: str,
        start_page: int = 1,
        max_pages: int = 30,
        early_stopping: bool = True
    ) -> pd.DataFrame:
        """
        Execută crawling distribuit cu 2-3 agenți pe rând.
        Fiecare agent preia un lot de 2-3 pagini, extrage datele ultra-rapid cu lxml
        și salvează atomic în SQLite.
        """
        logger.info(f"[*] [MultiAgent:{source_name}] Pornim crawling cu {self.num_agents} agenți ({self.batch_size} pagini/agent/val)...")
        known_cars = get_known_car_ids_and_prices(source=source_name, db_path=self.db_path) if early_stopping else {}

        all_results = []
        page_queue = list(range(start_page, start_page + max_pages))
        consecutive_known = 0

        # Rulăm pe valuri (waves) de câte num_agents agenți
        wave_size = self.num_agents * self.batch_size

        for wave_start in range(0, len(page_queue), wave_size):
            wave_pages = page_queue[wave_start: wave_start + wave_size]
            logger.info(f"[*] [MultiAgent:{source_name}] Val nou pagini {wave_pages[0]} -> {wave_pages[-1]}...")

            # Împărțim paginile pe agenți (câte 2-3 per agent)
            agent_tasks = []
            for i in range(self.num_agents):
                agent = self.agents[i]
                agent.init_session()  # reîmprospătare sesiune la fiecare val
                chunk = wave_pages[i * self.batch_size: (i + 1) * self.batch_size]
                if chunk:
                    agent_tasks.append((agent, chunk))

            # Execuție paralelă pe cei 2-3 agenți
            wave_results = []
            with ThreadPoolExecutor(max_workers=self.num_agents) as executor:
                futures = []
                for agent, pages in agent_tasks:
                    futures.append(executor.submit(
                        self._agent_worker,
                        agent, pages, url_builder_fn, card_parser_fn, card_selector
                    ))

                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                        wave_results.extend(res)
                    except Exception as e:
                        logger.error(f"[!] Eroare worker agent: {e}")

            # Verificare O(1) a ID-urilor deja cunoscute
            for car in wave_results:
                cid = f"{source_name}_{car.get('car_id')}"
                if early_stopping and cid in known_cars:
                    consecutive_known += 1
                else:
                    consecutive_known = 0
                all_results.append(car)

            logger.info(f"[+] [MultiAgent:{source_name}] Val finalizat: {len(wave_results)} anunțuri extrase în acest val.")

            # Dacă găsim peste 15 mașini deja cunoscute consecutiv, oprim early
            if early_stopping and consecutive_known >= 15:
                logger.info(f"[!] [MultiAgent:{source_name}] Early stopping declanșat ({consecutive_known} anunțuri neschimbate).")
                break

        # Salvare unificată în batch
        df = pd.DataFrame(all_results)
        if not df.empty:
            df = df.drop_duplicates(subset=['car_id'])
            stats = save_scraped_data(df, source_name=source_name, db_path=self.db_path)
            logger.info(
                f"[SUCCESS] [MultiAgent:{source_name}] Crawling finalizat: {len(df)} mașini totale "
                f"({stats.get('new', 0)} noi, {stats.get('updated', 0)} actualizate, {stats.get('price_drops', 0)} ieftiniri)."
            )
        else:
            logger.warning(f"[!] [MultiAgent:{source_name}] Nu s-au extras date.")

        return df

    def _agent_worker(
        self,
        agent: ScraperAgent,
        pages: List[int],
        url_builder_fn: Callable[[int], str],
        card_parser_fn: Callable[[Any], Dict[str, Any]],
        card_selector: str
    ) -> List[Dict[str, Any]]:
        """Execută colectarea paginilor atribuite unui singur agent."""
        agent_items = []
        for p in pages:
            url = url_builder_fn(p)
            html = agent.fetch_page_fast(url)
            if not html:
                continue

            # Parsare ultra-rapidă cu lxml
            soup = BeautifulSoup(html, 'lxml' if 'lxml' in sys.modules else 'html.parser')
            cards = soup.select(card_selector) if card_selector.startswith('.') or card_selector.startswith('#') else soup.find_all(card_selector)

            extracted_before = len(agent_items)
            for c in cards:
                try:
                    data = card_parser_fn(c)
                    if data and data.get('title') and data.get('price'):
                        agent_items.append(data)
                except Exception:
                    pass

            # Fallback Schema.org JSON-LD dacă selectorul CSS nu a extras nimic
            if len(agent_items) == extracted_before:
                try:
                    from fallback_engine import extract_json_ld_car_data
                    ld_items = extract_json_ld_car_data(soup)
                    for item in ld_items:
                        if item and item.get('title') and item.get('price'):
                            agent_items.append(item)
                except Exception:
                    pass

        return agent_items


if __name__ == "__main__":
    print("=== TEST MULTI-AGENT CRAWLER ENGINE ===")
    engine = MultiAgentCrawlerEngine(num_agents=3, batch_size_per_agent=2)

    # Test pe AutoUncle cu 3 agenți x 2 pagini (6 pagini în total)
    from scraper_autoUncle import parse_autouncle_article
    url_fn = lambda p: f"https://www.autouncle.ro/ro/masini-second-hand?page={p}&s%5Border%5D=creation_date_desc"

    res_df = engine.crawl_site(
        source_name="autouncle",
        url_builder_fn=url_fn,
        card_parser_fn=parse_autouncle_article,
        card_selector="article",
        max_pages=4,
        early_stopping=True
    )
    print(f"Total mașini colectate prin multi-agent: {len(res_df)}")
