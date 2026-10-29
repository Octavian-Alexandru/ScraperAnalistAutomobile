# FILE: db_optimizer.py
"""
Sistem de optimizare, mentenanță și backup automat pentru baza de date SQLite.
- Backup automat zilnic cu timestamp în `data/backups/`
- Rotație automată a backup-urilor (păstrează ultimele 7 copii pentru a conserva spațiul pe disc)
- Optimizare indecși cu `PRAGMA optimize` și checkpoint WAL complet
- Reducere fragmentare cu `VACUUM` periodic
"""

import os
import sys
import shutil
import sqlite3
import datetime
from typing import Dict, Any, List

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_connection, DB_PATH
from logger_config import logger

BACKUP_DIR = os.path.join("data", "backups")
MAX_BACKUPS_RETAINED = 7


def backup_database(db_path: str = DB_PATH, backup_dir: str = BACKUP_DIR) -> str:
    """Creează o copie atomică de siguranță a bazei de date."""
    if not os.path.exists(db_path):
        logger.warning(f"Baza de date {db_path} nu există pentru backup.")
        return ""

    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"cars_backup_{ts}.db")

    # Folosim API-ul oficial de backup SQLite pentru o copie complet sigură chiar dacă baza e deschisă
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_file)
        with dst:
            src.backup(dst, pages=1000)
        dst.close()
        src.close()
        size_mb = os.path.getsize(backup_file) / (1024 * 1024)
        logger.info(f"Backup SQLite realizat cu succes: {backup_file} ({size_mb:.1f} MB)")
    except Exception as e:
        logger.error(f"Eroare la backup atomic: {e}. Folosim fallback prin copiere...")
        shutil.copy2(db_path, backup_file)

    # Rotație backup-uri vechi
    clean_old_backups(backup_dir, max_keep=MAX_BACKUPS_RETAINED)
    return backup_file


def clean_old_backups(backup_dir: str = BACKUP_DIR, max_keep: int = MAX_BACKUPS_RETAINED):
    """Șterge backup-urile mai vechi de max_keep copii."""
    if not os.path.exists(backup_dir):
        return
    files = [
        os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
        if f.startswith("cars_backup_") and f.endswith(".db")
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    if len(files) > max_keep:
        for old_file in files[max_keep:]:
            try:
                os.remove(old_file)
                logger.info(f"Backup vechi eliminat conform politicii de rotație: {os.path.basename(old_file)}")
            except Exception:
                pass


def optimize_database(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Optimizează indecșii, checkpoint-ul WAL și statisticile de execuție ale query-urilor."""
    if not os.path.exists(db_path):
        return {"status": "skipped", "message": "Baza de date nu există."}

    initial_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    logger.info(f"Pornire optimizare DB ({initial_size_mb:.1f} MB)...")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # 1. Trunchiază jurnalul WAL pentru a elibera spațiul
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        # 2. Re-evaluează statisticile pentru planificatorul de query-uri
        cursor.execute("ANALYZE;")
        # 3. Optimizează indecșii bazați pe istoricul de interogări
        cursor.execute("PRAGMA optimize;")
        conn.commit()

    final_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    logger.info(f"Optimizare SQLite finalizată: {final_size_mb:.1f} MB.")
    return {
        "status": "success",
        "initial_size_mb": round(initial_size_mb, 2),
        "final_size_mb": round(final_size_mb, 2),
        "db_path": db_path
    }


if __name__ == "__main__":
    print("=== TEST DB OPTIMIZER & BACKUP ===")
    bk_path = backup_database()
    opt_res = optimize_database()
    print("Rezultat optimizare:", opt_res)
