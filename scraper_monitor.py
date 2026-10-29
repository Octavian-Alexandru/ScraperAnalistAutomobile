# FILE: scraper_monitor.py
"""
Sistem de monitorizare și sănătate a scraperelor (Scraper Health & Monitoring).
Urmărește fiecare rulare de scraper:
- Timestamp execuție și durată
- Număr de anunțuri colectate
- Detectare automată dacă un scraper a extras 0 anunțuri de mai multe ori (posibil selector CSS modificat)
- Alertă de sistem
"""

import sys
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from db_helper import get_connection, DB_PATH

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def init_health_table(db_path: str = DB_PATH):
    """Inițializează tabela scraper_health în SQLite."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraper_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_sec REAL,
                items_scraped INTEGER DEFAULT 0,
                new_items INTEGER DEFAULT 0,
                status TEXT, -- SUCCESS, WARNING, FAILED
                error_message TEXT
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_health_source ON scraper_health(source_name);")
        conn.commit()


def log_scraper_run(
    source_name: str,
    started_at: str,
    items_scraped: int,
    new_items: int = 0,
    status: str = "SUCCESS",
    error_message: Optional[str] = None,
    db_path: str = DB_PATH
) -> int:
    """Înregistrează rezultatul rulării unui scraper."""
    init_health_table(db_path)
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    duration = 0.0
    try:
        dt_start = datetime.datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
        dt_end = datetime.datetime.strptime(now_ts, "%Y-%m-%d %H:%M:%S")
        duration = round((dt_end - dt_start).total_seconds(), 1)
    except Exception:
        pass

    if items_scraped == 0 and status == "SUCCESS":
        status = "WARNING"
        if not error_message:
            error_message = "0 anunțuri extrase (posibil blocaj sau selector modificat)"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scraper_health (
                source_name, started_at, finished_at, duration_sec,
                items_scraped, new_items, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_name, started_at, now_ts, duration, items_scraped, new_items, status, error_message))
        conn.commit()
        return cursor.lastrowid


def get_scrapers_health_dashboard(db_path: str = DB_PATH) -> pd.DataFrame:
    """Returnează starea curentă a fiecărui scraper (ultima rulare și statusul)."""
    init_health_table(db_path)
    query = """
        WITH ranked AS (
            SELECT
                source_name, started_at, finished_at, duration_sec,
                items_scraped, new_items, status, error_message,
                ROW_NUMBER() OVER (PARTITION BY source_name ORDER BY started_at DESC) as rn
            FROM scraper_health
        )
        SELECT
            source_name as "Platformă",
            status as "Stare",
            items_scraped as "Extrase Ultima Rulare",
            new_items as "Noi Inserate",
            duration_sec as "Timp (sec)",
            finished_at as "Data Ultimei Rulări",
            error_message as "Observații"
        FROM ranked
        WHERE rn = 1
        ORDER BY source_name ASC;
    """
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn)
    return df


if __name__ == "__main__":
    print("=== TEST SCRAPER MONITOR ===")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_scraper_run("autovit", ts, items_scraped=45, new_items=12, status="SUCCESS")
    log_scraper_run("olx", ts, items_scraped=38, new_items=8, status="SUCCESS")
    log_scraper_run("autouncle", ts, items_scraped=60, new_items=15, status="SUCCESS")

    dash = get_scrapers_health_dashboard()
    print("\nStare Sănătate Scrapere:")
    print(dash.to_string(index=False))
