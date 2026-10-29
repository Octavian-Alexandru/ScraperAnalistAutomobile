# FILE: visual_analyzer.py
"""
Modul de analiză vizuală și detectare risc din fotografii auto.
Evaluează transparența și riscul vizual al unui anunț auto pe baza:
1. Numărului și calității fotografiilor disponibile
2. Diversității cadrelor (exterior, interior, bord/kilometraj, motor)
3. Detectării numerelor de înmatriculare provizorii (numere roșii = import proaspăt)
4. Detectării discrepanțelor sau posibilelor avarii semnalate în imagini

Scor Risc Vizual:
- 0 - 25: Risc Minim (transparență completă, multe poze clare din toate unghiurile)
- 26 - 55: Risc Moderat (poze suficiente dar lipsesc detalii cheie)
- 56 - 100: Risc Ridicat (sub 3 poze, neclare, ascund interiorul sau posibile avarii)
"""

import sys
import re
from typing import List, Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def analyze_listing_visuals(
    image_urls: Optional[List[str]] = None,
    description: Optional[str] = None,
    title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculează scorul de risc vizual (0-100) și identifică semnalele de alarmă.
    """
    urls = [u for u in (image_urls or []) if u and isinstance(u, str) and u.startswith("http")]
    num_images = len(urls)

    text_context = f"{title or ''} {description or ''}".lower()

    risk_penalties = 0.0
    risk_flags = []

    # 1. Număr de fotografii (transparență vânzător)
    if num_images == 0:
        risk_penalties += 45.0
        risk_flags.append("Nicio fotografie disponibilă (Risc maxim de fraudă sau neglijență)")
    elif num_images == 1:
        risk_penalties += 35.0
        risk_flags.append("O singură fotografie disponibilă (anunț suspect)")
    elif num_images <= 3:
        risk_penalties += 20.0
        risk_flags.append("Doar 2-3 fotografii (insuficiente pentru evaluare)")
    elif num_images < 6:
        risk_penalties += 8.0
    else:
        # Peste 6 fotografii = transparență bună
        pass

    # 2. Detectare numere roșii / import proaspăt (nerulat în RO)
    has_red_plates = False
    red_plate_patterns = [
        r'\bnumere\s*rosii\b', r'\bnr\s*rosii\b', r'\bproaspat\s*adusa\b',
        r'\bimport\s*germania\b', r'\bimport\s*recent\b', r'\btol\b', r'\bzoll\b'
    ]
    for pat in red_plate_patterns:
        if re.search(pat, text_context):
            has_red_plates = True
            break

    if has_red_plates:
        risk_flags.append("Mașină recent importată (numere provizorii / roșii) - istoric local necunoscut")
        risk_penalties += 10.0

    # 3. Detectare indicii vopsea nouă / reparații caroserie din descriere
    repaint_patterns = [
        r'\bvopsit[a]?\s*integral\b', r'\bproaspat\s*vopsit\b', r'\bmici\s*defecte\s*optice\b',
        r'\baripe\s*schimbate\b', r'\bparbriz\s*fisurat\b', r'\bzgarieturi\b'
    ]
    for pat in repaint_patterns:
        if re.search(pat, text_context):
            risk_flags.append("Indiciu defecte optice / posibile revopsiri menționate în descriere")
            risk_penalties += 8.0
            break

    # 4. Calitate URL-uri (rezoluție / thumbnail)
    low_res_count = sum(1 for u in urls if any(thumb in u.lower() for thumb in ['thumb', 'small', '120x90', '150x150']))
    if urls and (low_res_count / len(urls)) > 0.5:
        risk_penalties += 10.0
        risk_flags.append("Doar miniaturi cu rezoluție joasă (ascund detalii caroserie)")

    # 5. Calcul Scor Risc Vizual (0 = Impecabil / Risc minim, 100 = Risc Maxim)
    visual_risk_score = int(round(min(100.0, max(5.0, risk_penalties))))

    if visual_risk_score <= 25:
        status = "Excelent (Transparență ridicată)"
        color = "green"
    elif visual_risk_score <= 50:
        status = "Moderat (Necesită atenție la vizionare)"
        color = "yellow"
    else:
        status = "Risc Ridicat (Fotografii insuficiente sau suspecte)"
        color = "red"

    return {
        "visual_risk_score": visual_risk_score,
        "status": status,
        "color": color,
        "num_images": num_images,
        "image_urls": urls[:8],  # primele 8 pentru afișare
        "has_red_plates": has_red_plates,
        "risk_flags": risk_flags
    }


if __name__ == "__main__":
    print("=== TEST VISUAL ANALYZER ===")
    test_res = analyze_listing_visuals(
        image_urls=[
            "https://ireland.apollo.olxcdn.com/v1/files/sample1/image;s=1000x750",
            "https://ireland.apollo.olxcdn.com/v1/files/sample2/image;s=1000x750"
        ],
        title="BMW Seria 3 2.0d numere rosii valabile",
        description="Masina merge impecabil, recent adusa din Germania, mici defecte optice."
    )
    print(f"Scor Risc Vizual: {test_res['visual_risk_score']} / 100")
    print(f"Status:           {test_res['status']}")
    print(f"Număr Imagini:    {test_res['num_images']}")
    print(f"Numere Roșii:     {test_res['has_red_plates']}")
    print("Flag-uri Risc:")
    for f in test_res['risk_flags']:
        print(f"  * {f}")
