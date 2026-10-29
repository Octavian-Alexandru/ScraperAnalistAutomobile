# FILE: logger_config.py
"""
Sistem centralizat de logging structurat pentru ScraperAnalistAutomobile.
- Scriere în consolă cu formatare curată și timestamp
- Salvare în fișiere de log rotative cu limită de dimensiune (logs/pipeline.log)
- Suport pentru niveluri: DEBUG, INFO, WARNING, ERROR, CRITICAL
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")


def setup_logger(name: str = "auto_pipeline", log_level: int = logging.INFO) -> logging.Logger:
    """Configurează și returnează un logger structurat."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger(name)

    if logger.hasHandlers():
        return logger

    logger.setLevel(log_level)

    # Formatare: [TIMESTAMP] [NIVEL] [NUME] Mesaj
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Handler Consola (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. Handler Fisier Rotativ (max 10MB per fisier, pastreaza 5 backup-uri)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[!] Nu s-a putut inițializa RotatingFileHandler: {e}")

    logger.propagate = False
    return logger


logger = setup_logger()

if __name__ == "__main__":
    logger.info("Sistemul de logging structurat a fost inițializat cu succes.")
    logger.warning("Acesta este un mesaj de avertizare de test.")
