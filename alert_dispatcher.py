# FILE: alert_dispatcher.py
"""
Dispecer Multi-Canal de Alertare cu Fallback și Coadă Persistentă (Fail-Safe Alert Dispatcher).
Asigură că nicio alertă de oportunitate (Arbitraj, Scădere de preț, Raport) nu se pierde:

Lanț de Transmitere:
Canal 1: Telegram Bot API (Notificare instantanee mobilă)
Canal 2: Discord Webhook (Notificare canal comercial)
Canal 3: Email SMTP (Trimitere digest HTML)
Canal 4 (Fail-Safe Garantat): Coadă Persistentă pe Disc (data/alerts_outbox.jsonl)
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional
import requests

from logger_config import logger
from fallback_engine import AlertOutboxManager

outbox_manager = AlertOutboxManager()


def send_telegram_alert(message: str, token: Optional[str] = None, chat_id: Optional[str] = None) -> bool:
    """Trimite mesaj pe Telegram cu timeout strict."""
    tg_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not tg_token or not tg_chat:
        return False

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": tg_chat,
        "text": message[:4000],
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=8)
        if resp.status_code == 200:
            return True
        logger.warning(f"[Alert] Telegram a returnat codul {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        logger.error(f"[Alert] Eroare trimitere Telegram: {e}")
    return False


def send_discord_alert(message: str, webhook_url: Optional[str] = None) -> bool:
    """Trimite mesaj pe Discord Webhook cu timeout strict."""
    wh_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not wh_url:
        return False

    payload = {"content": message[:1950]}
    try:
        resp = requests.post(wh_url, json=payload, timeout=8)
        if resp.status_code in (200, 204):
            return True
        logger.warning(f"[Alert] Discord Webhook a returnat codul {resp.status_code}")
    except Exception as e:
        logger.error(f"[Alert] Eroare trimitere Discord: {e}")
    return False


def send_email_alert(subject: str, message: str, to_email: Optional[str] = None) -> bool:
    """Trimite notificare prin email prin modulul email_digest."""
    try:
        from email_digest import send_email
        target = to_email or os.getenv("ALERT_EMAIL_TARGET") or os.getenv("SMTP_USER")
        if not target:
            return False
        html = f"<div style='font-family: Arial, sans-serif; padding: 15px;'><h3>{subject}</h3><p style='white-space: pre-wrap;'>{message}</p></div>"
        return send_email(to_email=target, subject=subject, html_content=html)
    except Exception as e:
        logger.error(f"[Alert] Eroare trimitere Email: {e}")
    return False


def dispatch_alert_with_fallback(
    subject: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
    preferred_channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Distribuie o alertă traversând lanțul de fallback:
    1. Telegram
    2. Discord
    3. Email
    4. Dacă toate canalele eșuează sau lipsesc credențialele, salvează în outbox-ul de pe disc.
    """
    channels = preferred_channels or ["telegram", "discord", "email"]
    results = {}
    any_success = False

    for ch in channels:
        ch_clean = ch.lower().strip()
        success = False

        if ch_clean == "telegram":
            success = send_telegram_alert(message)
        elif ch_clean == "discord":
            success = send_discord_alert(message)
        elif ch_clean == "email":
            success = send_email_alert(subject, message)

        results[ch_clean] = success
        if success:
            any_success = True
            logger.info(f"[AlertDispatcher] Alerta expediată cu succes prin canalul '{ch_clean}'.")
            break

    # Dacă toate canalele de rețea au eșuat, salvăm garantat în coada persistentă pe disc
    if not any_success:
        logger.warning("[AlertDispatcher] Toate canalele de alertare au eșuat. Salvăm în coada offline pe disc...")
        outbox_manager.enqueue_alert(
            channel="all_failed",
            message=f"{subject}\n\n{message}",
            metadata=metadata
        )
        results["queued_to_outbox"] = True
    else:
        results["queued_to_outbox"] = False

    return {
        "dispatched": any_success,
        "results": results
    }


def retry_outbox_alerts() -> int:
    """
    Încearcă re-trimiterea tuturor alertelor salvate în outbox.
    Apelat automat la pornirea oricărui job de pipeline.
    """
    pending = outbox_manager.get_pending_alerts()
    if not pending:
        return 0

    logger.info(f"[AlertDispatcher] Găsite {len(pending)} alerte restante în outbox. Reîncercăm expedierea...")
    replayed = 0

    for item in pending:
        msg = item.get("message", "")
        # Încercăm Telegram sau Discord
        sent = send_telegram_alert(msg) or send_discord_alert(msg)
        if sent:
            replayed += 1

    if replayed == len(pending):
        outbox_manager.clear_outbox()
        logger.info(f"[AlertDispatcher] Toate cele {replayed} alerte restante au fost livrate și outbox-ul a fost curățat.")
    elif replayed > 0:
        logger.info(f"[AlertDispatcher] Livrate {replayed}/{len(pending)} alerte restante.")

    return replayed
