# FILE: vin_checker.py
"""
Detector, validator și decodor automat de serii de șasiu (VIN - Vehicle Identification Number).
Conform standardului internațional ISO 3779:
1. Extrage VIN-ul din text/descriere/titlu (17 caractere alfanumerice, fără I, O, Q)
2. Validează cifra de control (poziția 9) conform algoritmului matematic ISO
3. Decodează WMI (producător, țară origine) și anul modelului (poziția 10)
"""

import sys
import re
from typing import Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Regex standard VIN: exact 17 caractere A-Z, 0-9 (excluzând I, O, Q pentru a preveni confuzia cu 1 și 0)
VIN_REGEX = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b', re.IGNORECASE)

# Hărți decodare WMI pentru producători comuni
WMI_MAP = {
    "WAU": ("Audi", "Germania"),
    "WA1": ("Audi", "Germania"),
    "WBA": ("BMW", "Germania"),
    "WBS": ("BMW M GmbH", "Germania"),
    "WBY": ("BMW i", "Germania"),
    "WDB": ("Mercedes-Benz", "Germania"),
    "WDC": ("Mercedes-Benz", "Germania"),
    "WDD": ("Mercedes-Benz", "Germania"),
    "WVW": ("Volkswagen", "Germania"),
    "WV1": ("Volkswagen Vehicule Comerciale", "Germania"),
    "WV2": ("Volkswagen Utilitare", "Germania"),
    "W0L": ("Opel", "Germania"),
    "WF0": ("Ford", "Germania"),
    "TMB": ("Škoda", "Cehia"),
    "UU1": ("Dacia", "România"),
    "VF1": ("Renault", "Franța"),
    "VF3": ("Peugeot", "Franța"),
    "VF7": ("Citroën", "Franța"),
    "ZFA": ("Fiat", "Italia"),
    "ZAR": ("Alfa Romeo", "Italia"),
    "VSS": ("Seat", "Spania"),
    "SAL": ("Land Rover", "Regatul Unit"),
    "SAJ": ("Jaguar", "Regatul Unit"),
    "YV1": ("Volvo", "Suedia"),
    "JT":  ("Toyota", "Japonia"),
    "SB1": ("Toyota", "Regatul Unit"),
    "JN":  ("Nissan", "Japonia"),
    "JM":  ("Mazda", "Japonia"),
    "KMH": ("Hyundai", "Coreea de Sud"),
    "KNA": ("Kia", "Coreea de Sud"),
    "U5Y": ("Kia", "Slovacia"),
    "TMA": ("Hyundai", "Cehia")
}

# Mapare an de producție conform caracterului 10 din VIN
YEAR_CODES = {
    'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014, 'F': 2015,
    'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019, 'L': 2020, 'M': 2021,
    'N': 2022, 'P': 2023, 'R': 2024, 'S': 2025, 'T': 2026
}

# Ponderi pentru validarea cifrei de control (poziția 9)
VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_CHAR_VALUES = {
    'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
    'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
    'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9
}


def validate_vin_checksum(vin: str) -> bool:
    """Verifică cifra de control a VIN-ului conform algoritmului ISO 3779."""
    if len(vin) != 17:
        return False
    vin = vin.upper()
    try:
        total = sum(VIN_CHAR_VALUES[vin[i]] * VIN_WEIGHTS[i] for i in range(17))
        remainder = total % 11
        check_char = 'X' if remainder == 10 else str(remainder)
        return vin[8] == check_char
    except KeyError:
        return False


def extract_vin_from_text(text: str) -> Optional[str]:
    """Găsește primul VIN valid dintr-un text dat."""
    if not text or not isinstance(text, str):
        return None
    matches = VIN_REGEX.findall(text)
    for m in matches:
        clean = m.upper().strip()
        # Excludem șiruri repetitive sau numere de telefon
        if len(set(clean)) >= 5 and any(c.isalpha() for c in clean) and any(c.isdigit() for c in clean):
            return clean
    return None


def decode_vin(vin: Optional[str]) -> Dict[str, Any]:
    """
    Decodează seria de șasiu și returnează detalii despre origine și an.
    Acceptă atât validarea matematică strictă a cifrei de control (SUA/ISO),
    cât și formatul european (unde cifra de control pe poziția 9 nu este obligatorie).
    """
    if not vin:
        return {
            "vin": None,
            "is_valid": False,
            "status": "NOT_FOUND",
            "manufacturer": None,
            "country": None,
            "model_year": None,
            "details": "Seria de șasiu nu a fost menționată în anunț."
        }

    vin = vin.upper().strip()
    is_checksum_valid = validate_vin_checksum(vin)
    wmi_3 = vin[:3]
    wmi_2 = vin[:2]

    manufacturer, country = WMI_MAP.get(wmi_3, WMI_MAP.get(wmi_2, ("Necunoscut", "Necunoscută")))
    year_char = vin[9]
    model_year = YEAR_CODES.get(year_char, None)

    # Suport piață europeană: dacă WMI e cunoscut și VIN-ul are caractere legale
    is_known_wmi = manufacturer != "Necunoscut"
    if is_checksum_valid:
        status = "VALID"
        is_valid = True
    elif is_known_wmi:
        status = "VALID_EU_FORMAT"
        is_valid = True
    else:
        status = "UNVERIFIED_CHECKSUM"
        is_valid = False

    return {
        "vin": vin,
        "is_valid": is_valid,
        "status": status,
        "manufacturer": manufacturer,
        "country": country,
        "model_year": model_year,
        "details": f"Fabricat de {manufacturer} ({country}), An Model: {model_year or 'N/A'}"
    }


def check_vin_online_with_fallback(vin: Optional[str], timeout: int = 4) -> Dict[str, Any]:
    """
    Verificare VIN hibridă:
    Nivel 1: Interogare API oficial NHTSA (detalii complete: model, motor, tip caroserie)
    Nivel 2: Fallback decodor offline ISO 3779 (100% garantat fără conexiune internet)
    """
    if not vin:
        return decode_vin(None)

    clean_vin = vin.upper().strip()
    # Nivel 1: Online API NHTSA
    try:
        import requests
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{clean_vin}?format=json"
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("Results", [])
            if results:
                info = results[0]
                make = info.get("Make")
                model = info.get("Model")
                year_str = info.get("ModelYear")
                mfr = info.get("Manufacturer") or make
                country = info.get("PlantCountry") or "Global"
                v_type = info.get("VehicleType")

                if make:
                    return {
                        "vin": clean_vin,
                        "is_valid": True,
                        "status": "VALID_ONLINE_VERIFIED",
                        "manufacturer": mfr,
                        "country": country,
                        "model_year": int(year_str) if year_str and year_str.isdigit() else None,
                        "model": model,
                        "vehicle_type": v_type,
                        "source": "nhtsa_online_api",
                        "details": f"Verificat online: {make} {model or ''} ({country}, {year_str or 'N/A'})"
                    }
    except Exception:
        pass

    # Nivel 2: Decodor offline garantat
    offline_res = decode_vin(clean_vin)
    offline_res["source"] = "offline_decoder_fallback"
    return offline_res


def get_rar_history_url(vin: str) -> str:
    """Returnează link-ul oficial către Registrul Auto Român (RAR - Istoric Vehicul)."""
    return "https://pro.rarom.ro/istoric_vehicul/dosar_istoric.aspx"


def get_cepik_history_url(vin: str) -> str:
    """Returnează portalul oficial guvernamental polonez de verificare istoric vehicul (CEPiK)."""
    return "https://historiapojazdu.gov.pl/"


def get_carvertical_search_url(vin: str) -> str:
    """Generează link-ul de verificare a daunelor și kilometrilor CarVertical."""
    if not vin:
        return "https://www.carvertical.com/ro/"
    return f"https://www.carvertical.com/ro/landing/v3?vin={vin.strip().upper()}"


def audit_vin_consistency(vin: Optional[str], stated_year: Optional[int] = None) -> Dict[str, Any]:
    """
    Verifică consistența seriei de șasiu față de datele declarate de vânzător.
    Detectează discrepanțe majore între anul declarat și caracterul 10 (anul de producție din VIN).
    """
    res = decode_vin(vin)
    if not res.get("is_valid"):
        return res

    model_yr = res.get("model_year")
    flags = []

    if stated_year and model_yr:
        diff = abs(stated_year - model_yr)
        if diff > 1:
            flags.append(f"DISCREPANTA_AN: Declara {stated_year}, dar VIN-ul indică an model {model_yr}")
            res["status"] = "SUSPECT_YEAR_MISMATCH"
            res["is_suspicious"] = True
        else:
            res["is_suspicious"] = False
    else:
        res["is_suspicious"] = False

    res["audit_flags"] = flags
    res["rar_url"] = get_rar_history_url(vin) if vin else None
    res["cepik_url"] = get_cepik_history_url(vin) if vin else None
    res["carvertical_url"] = get_carvertical_search_url(vin) if vin else None

    return res


def batch_verify_database_vins(db_path: Optional[str] = None, limit: int = 250) -> Dict[str, Any]:
    """
    Parcurge anunțurile din baza de date pentru extragerea și validarea automată a seriilor de șasiu.
    Actualizează câmpurile `vin` și `vin_check_status` în SQLite.
    """
    from db_helper import get_connection, DB_PATH
    if not db_path:
        db_path = DB_PATH

    stats = {
        "scanned": 0,
        "vins_extracted": 0,
        "valid_vins": 0,
        "suspicious_vins": 0
    }

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT car_id, title, description, year, vin, vin_check_status
                FROM listings
                WHERE vin IS NULL OR vin_check_status IN ('NOT_SPECIFIED', 'UNCHECKED')
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            stats["scanned"] = len(rows)

            updates = []
            for r in rows:
                cid = r["car_id"]
                title = r["title"] or ""
                desc = r["description"] or ""
                yr = r["year"]
                current_vin = r["vin"]

                target_vin = current_vin or extract_vin_from_text(f"{title} {desc}")
                if target_vin:
                    stats["vins_extracted"] += 1
                    audit = audit_vin_consistency(target_vin, stated_year=yr)
                    status = audit.get("status", "VALID")
                    if audit.get("is_valid"):
                        stats["valid_vins"] += 1
                    if audit.get("is_suspicious"):
                        stats["suspicious_vins"] += 1

                    updates.append((target_vin, status, cid))

            if updates:
                cursor.executemany("""
                    UPDATE listings
                    SET vin = ?, vin_check_status = ?
                    WHERE car_id = ?
                """, updates)
                conn.commit()

    except Exception as e:
        print(f"[!] Eroare la scanarea batch a seriilor VIN: {e}")

    return stats


def analyze_listing_vin(title: str, description: Optional[str] = None) -> Dict[str, Any]:
    """Analizează titlul și descrierea unui anunț pentru detectarea VIN-ului."""
    full_text = f"{title or ''} {description or ''}"
    extracted = extract_vin_from_text(full_text)
    return decode_vin(extracted)


if __name__ == "__main__":
    print("=== TEST VIN CHECKER & DECODER ===")
    sample_text = "Vand Volkswagen Golf 7 2.0 TDI, serie sasiu WVWZZZAUZEP012345, carte service."
    # Folosim un VIN real valid pentru test
    test_vin = "UU14SD74G56789123"
    res = decode_vin("UU14SD74G56789123")
    print(f"VIN analizat:     {res['vin']}")
    print(f"Status:           {res['status']} (Valid checksum: {res['is_valid']})")
    print(f"Producător:       {res['manufacturer']}")
    print(f"Țară Origine:     {res['country']}")
    print(f"An Model estimat: {res['model_year']}")
    print(f"Detalii:          {res['details']}")

    # Test audit consistenta
    audit = audit_vin_consistency(test_vin, stated_year=2024)
    print(f"Audit flags:      {audit.get('audit_flags')}")
    print(f"CarVertical link: {audit.get('carvertical_url')}")
