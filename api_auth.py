# FILE: api_auth.py
"""
Sistem de Autentificare și Rate Limiting pentru API-ul REST.
Implementează:
1. Generare și validare API Keys cu stocare în SQLite
2. Rate Limiting per plan (Free: 10 req/zi, Pro: 1000 req/zi, Business: nelimitat)
3. Middleware FastAPI cu Dependency Injection
4. Dashboard admin pentru managementul key-urilor
5. Tracking usage per API key (contor zilnic)
"""

import os
import sys
import time
import hashlib
import secrets
import sqlite3
import datetime
from typing import Dict, Any, Optional, Tuple
from functools import wraps

from fastapi import Header, HTTPException, Request, Depends
from fastapi.security import APIKeyHeader

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from db_helper import DB_PATH
from logger_config import logger

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Limite per plan
RATE_LIMITS = {
    "free": 10,        # 10 req/zi
    "pro": 1000,       # 1000 req/zi
    "business": 100000 # practic nelimitat
}


def get_auth_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Conexiune SQLite optimizată pentru tabelele de autentificare."""
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_tables(db_path: str = DB_PATH):
    """Crează tabelele de autentificare dacă nu există."""
    with get_auth_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                owner_email TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                total_requests INTEGER DEFAULT 0,
                notes TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                request_date TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                UNIQUE(key_hash, endpoint, request_date)
            );
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_date ON api_usage(request_date);")
        conn.commit()


def generate_api_key(
    owner_name: str,
    owner_email: str = "",
    plan: str = "free",
    notes: str = "",
    db_path: str = DB_PATH
) -> Dict[str, str]:
    """
    Generează un API key nou, securizat criptografic.
    Returnează key-ul în clar (singura dată când e vizibil!) și prefixul.
    """
    init_auth_tables(db_path)

    raw_key = f"rca_{secrets.token_urlsafe(32)}"  # rca = Radar Comercial Auto
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12] + "..."  # primele 12 caractere pentru identificare

    with get_auth_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO api_keys (key_hash, key_prefix, owner_name, owner_email, plan, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key_hash, key_prefix, owner_name, owner_email, plan.lower(),
             datetime.datetime.now().isoformat(), notes)
        )
        conn.commit()

    logger.info(f"[API Auth] Key generat pentru '{owner_name}' (plan: {plan}). Prefix: {key_prefix}")

    return {
        "api_key": raw_key,
        "prefix": key_prefix,
        "plan": plan,
        "owner": owner_name,
        "daily_limit": RATE_LIMITS.get(plan.lower(), 10),
        "message": "SALVEAZĂ ACEST KEY! Nu va mai fi afișat niciodată."
    }


def validate_api_key(api_key: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Validează un API key și returnează profilul utilizatorului."""
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    init_auth_tables(db_path)

    with get_auth_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
            (key_hash,)
        ).fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "key_hash": row["key_hash"],
            "key_prefix": row["key_prefix"],
            "owner_name": row["owner_name"],
            "owner_email": row["owner_email"],
            "plan": row["plan"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "total_requests": row["total_requests"]
        }


def check_rate_limit(key_hash: str, endpoint: str = "general", db_path: str = DB_PATH) -> Tuple[bool, int, int]:
    """
    Verifică și incrementează contorul de rate limit.
    Returnează: (allowed, current_count, daily_limit)
    """
    today = datetime.date.today().isoformat()

    with get_auth_connection(db_path) as conn:
        # Obținem planul utilizatorului
        key_row = conn.execute(
            "SELECT plan FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()

        if not key_row:
            return False, 0, 0

        plan = key_row["plan"]
        daily_limit = RATE_LIMITS.get(plan, 10)

        # Obținem/creăm contorul zilnic
        usage = conn.execute(
            "SELECT request_count FROM api_usage WHERE key_hash = ? AND request_date = ? AND endpoint = ?",
            (key_hash, today, endpoint)
        ).fetchone()

        current = usage["request_count"] if usage else 0

        if current >= daily_limit:
            return False, current, daily_limit

        # Incrementăm contorul
        conn.execute(
            """INSERT INTO api_usage (key_hash, endpoint, request_date, request_count)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(key_hash, endpoint, request_date)
               DO UPDATE SET request_count = request_count + 1""",
            (key_hash, endpoint, today)
        )

        # Actualizăm totalul și last_used
        conn.execute(
            "UPDATE api_keys SET total_requests = total_requests + 1, last_used_at = ? WHERE key_hash = ?",
            (datetime.datetime.now().isoformat(), key_hash)
        )
        conn.commit()

        return True, current + 1, daily_limit


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Depends(API_KEY_HEADER)
) -> Dict[str, Any]:
    """
    Dependency FastAPI pentru verificarea API key-ului.
    Endpoint-urile publice (/health, /) nu necesită key.
    """
    # Endpoint-uri publice (fără autentificare)
    public_paths = {"/", "/health", "/docs", "/redoc", "/openapi.json"}
    if request.url.path in public_paths:
        return {"plan": "public", "owner_name": "anonymous"}

    # Dacă nu e furnizat niciun key, permitem acces limitat (free implicit)
    if not api_key:
        # Mod "anonymous free" - 10 req/zi per IP
        client_ip = request.client.host if request.client else "unknown"
        anon_hash = hashlib.sha256(f"anon_{client_ip}".encode()).hexdigest()

        # Creăm/verificăm rate limit anonim
        init_auth_tables()
        with get_auth_connection() as conn:
            today = datetime.date.today().isoformat()
            usage = conn.execute(
                "SELECT request_count FROM api_usage WHERE key_hash = ? AND request_date = ? AND endpoint = ?",
                (anon_hash, today, "anonymous")
            ).fetchone()
            current = usage["request_count"] if usage else 0

            if current >= RATE_LIMITS["free"]:
                raise HTTPException(
                    status_code=429,
                    detail=f"Limita zilnică de {RATE_LIMITS['free']} cereri gratuite a fost atinsă. "
                           f"Obțineți un API key pentru acces extins."
                )

            conn.execute(
                """INSERT INTO api_usage (key_hash, endpoint, request_date, request_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(key_hash, endpoint, request_date)
                   DO UPDATE SET request_count = request_count + 1""",
                (anon_hash, "anonymous", today)
            )
            conn.commit()

        return {"plan": "free", "owner_name": "anonymous", "key_hash": anon_hash}

    # Validare key furnizat
    user_profile = validate_api_key(api_key)
    if not user_profile:
        raise HTTPException(status_code=401, detail="API key invalid sau dezactivat.")

    # Verificare rate limit
    allowed, current, limit = check_rate_limit(
        user_profile["key_hash"],
        endpoint=request.url.path
    )

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Limita zilnică de {limit} cereri (plan '{user_profile['plan']}') a fost atinsă. "
                   f"Upgrade la un plan superior pentru acces nelimitat."
        )

    return user_profile


def get_all_api_keys(db_path: str = DB_PATH) -> list:
    """Returnează toate API key-urile (pentru admin dashboard)."""
    init_auth_tables(db_path)
    with get_auth_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, key_prefix, owner_name, owner_email, plan, is_active, created_at, last_used_at, total_requests FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def deactivate_api_key(key_id: int, db_path: str = DB_PATH) -> bool:
    """Dezactivează un API key."""
    with get_auth_connection(db_path) as conn:
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
        conn.commit()
    return True


def get_usage_stats(days: int = 7, db_path: str = DB_PATH) -> list:
    """Returnează statistici de utilizare pe ultimele N zile."""
    init_auth_tables(db_path)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with get_auth_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT k.key_prefix, k.owner_name, k.plan, u.request_date,
                      SUM(u.request_count) as total_reqs
               FROM api_usage u
               JOIN api_keys k ON u.key_hash = k.key_hash
               WHERE u.request_date >= ?
               GROUP BY k.key_prefix, u.request_date
               ORDER BY u.request_date DESC""",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    print("=== TEST API AUTH ===")
    init_auth_tables()

    # Generăm un key de test
    result = generate_api_key("Test User", "test@example.com", plan="pro")
    print(f"Key generat: {result}")

    # Validăm key-ul
    profile = validate_api_key(result["api_key"])
    print(f"Profil validat: {profile}")

    # Rate limit test
    allowed, count, limit = check_rate_limit(profile["key_hash"])
    print(f"Rate limit: allowed={allowed}, count={count}, limit={limit}")

    # Stats
    keys = get_all_api_keys()
    print(f"Total API keys: {len(keys)}")
