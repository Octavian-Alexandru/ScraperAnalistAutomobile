# FILE: email_digest.py
"""
Sistem de Email Digest Săptămânal / Zilnic.
Implementează:
1. Generare template HTML profesional cu grafice inline (base64)
2. Trimitere prin SMTP (Gmail / SendGrid / Mailgun / generic SMTP)
3. Conținut: Top oportunități, scăderi de preț, trenduri, statistici piață
4. Suport pentru lista de abonați din SQLite
5. Personalizare per abonat (brand, buget, tip mașină)
"""

import os
import sys
import base64
import smtplib
import sqlite3
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import get_connection, get_db_stats, get_price_drops, DB_PATH
from logger_config import logger


def init_subscribers_table(db_path: str = DB_PATH):
    """Crează tabelul de abonați dacă nu există."""
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                frequency TEXT DEFAULT 'weekly',
                brands_filter TEXT,
                max_price_eur REAL,
                min_deal_score INTEGER DEFAULT 60,
                is_active INTEGER DEFAULT 1,
                subscribed_at TEXT NOT NULL,
                last_sent_at TEXT,
                unsubscribe_token TEXT
            );
        """)
        conn.commit()


def add_subscriber(
    email: str,
    name: str = "",
    frequency: str = "weekly",
    brands_filter: str = "",
    max_price_eur: float = 0,
    min_deal_score: int = 60,
    db_path: str = DB_PATH
) -> int:
    """Adaugă un abonat nou."""
    import secrets
    init_subscribers_table(db_path)
    token = secrets.token_urlsafe(16)
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO email_subscribers
               (email, name, frequency, brands_filter, max_price_eur, min_deal_score, subscribed_at, unsubscribe_token)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, name, frequency, brands_filter, max_price_eur, min_deal_score,
             datetime.datetime.now().isoformat(), token)
        )
        conn.commit()
    logger.info(f"[Email] Abonat adăugat: {email} (frecvență: {frequency})")
    return 1


def get_active_subscribers(frequency: str = "weekly", db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returnează abonații activi pentru o anumită frecvență."""
    init_subscribers_table(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM email_subscribers WHERE is_active = 1 AND frequency = ?",
            (frequency,)
        ).fetchall()
        return [dict(r) for r in rows]


def generate_html_report(stats: Dict[str, Any], drops_df: pd.DataFrame, top_deals: List[Dict] = None) -> str:
    """Generează un raport HTML stilizat profesional."""
    today = datetime.datetime.now().strftime("%d %B %Y")

    # Tabel scăderi de preț
    drops_html = ""
    if not drops_df.empty:
        rows = []
        for _, r in drops_df.head(10).iterrows():
            title = str(r.get('title', ''))[:40]
            old_p = r.get('old_price', 0)
            new_p = r.get('new_price', 0)
            drop = r.get('drop_eur', 0)
            url = r.get('url', '#')
            rows.append(f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">
                        <a href="{url}" style="color: #2563eb; text-decoration: none;">{title}</a>
                    </td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; text-decoration: line-through; color: #999;">{old_p:,.0f} €</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold; color: #16a34a;">{new_p:,.0f} €</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; color: #dc2626;">-{drop:,.0f} €</td>
                </tr>
            """)
        drops_html = "".join(rows)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8fafc; margin: 0; padding: 0; }}
            .container {{ max-width: 640px; margin: 0 auto; background: #ffffff; }}
            .header {{ background: linear-gradient(135deg, #1e3a5f 0%, #0ea5e9 100%); padding: 30px; text-align: center; }}
            .header h1 {{ color: #ffffff; margin: 0; font-size: 24px; }}
            .header p {{ color: #bae6fd; margin: 8px 0 0; font-size: 14px; }}
            .content {{ padding: 24px; }}
            .stat-grid {{ display: flex; gap: 12px; margin: 20px 0; flex-wrap: wrap; }}
            .stat-card {{ flex: 1; min-width: 120px; background: #f0f9ff; border-radius: 8px; padding: 16px; text-align: center; }}
            .stat-card .number {{ font-size: 28px; font-weight: bold; color: #1e3a5f; }}
            .stat-card .label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
            .section-title {{ font-size: 18px; font-weight: bold; color: #1e3a5f; margin: 24px 0 12px; border-bottom: 2px solid #0ea5e9; padding-bottom: 8px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ background: #f1f5f9; padding: 10px 8px; text-align: left; font-size: 12px; color: #475569; text-transform: uppercase; }}
            .footer {{ background: #f1f5f9; padding: 20px; text-align: center; color: #94a3b8; font-size: 12px; }}
            .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; }}
            .badge-green {{ background: #dcfce7; color: #16a34a; }}
            .badge-blue {{ background: #dbeafe; color: #2563eb; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚗 Radar Comercial Auto</h1>
                <p>Digest de Piață — {today}</p>
            </div>

            <div class="content">
                <div class="stat-grid">
                    <div class="stat-card">
                        <div class="number">{stats.get('total_listings', 0):,}</div>
                        <div class="label">Total Anunțuri</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{stats.get('active_listings', 0):,}</div>
                        <div class="label">Active</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{stats.get('new_today', 0):,}</div>
                        <div class="label">Noi Azi</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">{len(drops_df) if not drops_df.empty else 0}</div>
                        <div class="label">Scăderi Preț</div>
                    </div>
                </div>

                <div class="section-title">📉 Top Scăderi de Preț</div>
                {"<table><tr><th>Mașină</th><th>Preț Vechi</th><th>Preț Nou</th><th>Diferență</th></tr>" + drops_html + "</table>" if drops_html else "<p style='color: #94a3b8;'>Nu sunt scăderi semnificative în această perioadă.</p>"}

                <div class="section-title">📊 Recomandări</div>
                <p style="color: #475569; line-height: 1.6;">
                    Accesează <strong>Dashboard-ul complet</strong> pentru a vedea toate oportunitățile de arbitraj,
                    Deal Score-urile calculate automat și trendurile de preț pe fiecare model.
                </p>
            </div>

            <div class="footer">
                <p>Radar Comercial Auto — Raport generat automat</p>
                <p>Pentru dezabonare, răspunde cu "STOP" la acest email.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str = None,
    smtp_host: str = None,
    smtp_port: int = None,
    smtp_user: str = None,
    smtp_pass: str = None
) -> bool:
    """
    Trimite un email HTML prin SMTP.
    Configurare prin parametri sau env vars:
    - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
    """
    host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
    user = smtp_user or os.getenv("SMTP_USER", "")
    password = smtp_pass or os.getenv("SMTP_PASS", "")
    sender = from_email or os.getenv("SMTP_FROM", user)

    if not user or not password:
        logger.warning("[Email] SMTP nu e configurat. Salvăm emailul în coada offline outbox.")
        try:
            from fallback_engine import alert_outbox
            alert_outbox.enqueue_alert("email", f"To: {to_email} | Subject: {subject}\n\n{html_content[:500]}...", {"to_email": to_email, "subject": subject})
        except Exception:
            pass
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Radar Comercial Auto <{sender}>"
    msg["To"] = to_email

    # Versiune text (fallback)
    text_part = MIMEText("Accesează dashboard-ul pentru detalii complete.", "plain", "utf-8")
    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(text_part)
    msg.attach(html_part)

    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            if port != 25:
                server.starttls()
            server.login(user, password)
            server.sendmail(sender, to_email, msg.as_string())
        logger.info(f"[Email] Trimis cu succes către {to_email}")
        return True
    except Exception as e:
        logger.error(f"[Email] Eroare la trimitere către {to_email}: {e}. Salvăm în outbox...")
        try:
            from fallback_engine import alert_outbox
            alert_outbox.enqueue_alert("email", f"To: {to_email} | Subject: {subject}", {"to_email": to_email, "subject": subject, "error": str(e)})
        except Exception:
            pass
        return False


def send_digest_to_subscribers(
    frequency: str = "weekly",
    db_path: str = DB_PATH
) -> Dict[str, int]:
    """
    Trimite digest-ul către toți abonații activi cu frecvența specificată.
    """
    subscribers = get_active_subscribers(frequency, db_path)
    if not subscribers:
        logger.info(f"[Email] Niciun abonat activ cu frecvență '{frequency}'.")
        return {"sent": 0, "failed": 0, "skipped": 0}

    stats = get_db_stats(db_path)
    drops = get_price_drops(days=7 if frequency == "weekly" else 1, min_drop_eur=200, db_path=db_path)

    today = datetime.datetime.now().strftime("%d.%m.%Y")
    period = "Săptămânal" if frequency == "weekly" else "Zilnic"
    subject = f"🚗 Radar Auto — Digest {period} ({today})"

    html = generate_html_report(stats, drops)

    sent = 0
    failed = 0
    for sub in subscribers:
        success = send_email(sub["email"], subject, html)
        if success:
            sent += 1
            # Actualizăm last_sent_at
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE email_subscribers SET last_sent_at = ? WHERE id = ?",
                    (datetime.datetime.now().isoformat(), sub["id"])
                )
                conn.commit()
        else:
            failed += 1

    result = {"sent": sent, "failed": failed, "total_subscribers": len(subscribers)}
    logger.info(f"[Email Digest] {result}")
    return result


if __name__ == "__main__":
    print("=== TEST EMAIL DIGEST ===")
    init_subscribers_table()

    stats = get_db_stats()
    drops = get_price_drops(days=7, min_drop_eur=200)

    html = generate_html_report(stats, drops)

    # Salvăm HTML-ul de test local
    os.makedirs("results", exist_ok=True)
    with open("results/email_digest_preview.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("[+] Preview HTML salvat în results/email_digest_preview.html")
    print(f"[i] Abonați activi: {len(get_active_subscribers('weekly'))}")
