# FILE: negotiation_generator.py
"""
Generator Automat de Scripturi și Mesaje Profesionale de Negociere Auto
în Limba Germană și Limba Engleză pentru Dealeri și Vânzători din Europa de Vest.

Funcționalități cheie:
1. Generare email / mesaj în limba Germană (specific pentru Mobile.de, AutoScout24.de, Willhaben.at)
2. Generare mesaj în limba Engleză (pentru Olanda, Belgia, dealeri internaționali)
3. Întrebări tehnice decisive (Scheckheftgepflegt, Unfallfrei, TÜV, stare anvelope/frâne)
4. Solicitare oficială de achiziție NETTO (fără TVA) pentru firme din România (SRL cu VIES)
5. Ofertă de cumpărare fermă și calculată psihologic (cash / transfer rapid cu ridicare în 48h)
"""

import sys
from typing import Dict, Any, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def calculate_target_negotiation_price(
    asked_price_eur: float,
    seller_type: str = "Dealer",
    is_netto_eligible: bool = False,
    vat_rate: float = 0.19
) -> Dict[str, Any]:
    """
    Calculează o ofertă de pornire și o ofertă țintă pentru negociere:
    - Pentru dealeri: marjă de 4-7% negociere (plus deducere TVA dacă e Netto)
    - Pentru privați: marjă de 8-12% negociere
    """
    st_lower = str(seller_type).lower()
    is_private = "partic" in st_lower or "privat" in st_lower

    if is_private:
        discount_aggressive_pct = 0.12
        discount_target_pct = 0.08
    else:
        discount_aggressive_pct = 0.08
        discount_target_pct = 0.05

    base_calc_price = asked_price_eur
    if is_netto_eligible:
        base_calc_price = asked_price_eur / (1.0 + vat_rate)

    opening_offer = round(base_calc_price * (1.0 - discount_aggressive_pct), -1)  # rotunjit la zeci
    target_buy_price = round(base_calc_price * (1.0 - discount_target_pct), -1)

    return {
        "asked_price_eur": asked_price_eur,
        "base_calc_price_eur": round(base_calc_price, 2),
        "opening_offer_eur": opening_offer,
        "target_buy_price_eur": target_buy_price,
        "is_netto_applied": is_netto_eligible
    }


def generate_german_negotiation_message(
    car_title: str,
    asked_price_eur: float,
    offer_price_eur: Optional[float] = None,
    seller_name: Optional[str] = None,
    seller_type: str = "Dealer",
    buyer_name: str = "Alexandru Popescu",
    buyer_phone: str = "+40 700 000 000",
    is_company_buyer: bool = False,
    company_name: Optional[str] = None,
    vat_id_vies: Optional[str] = None
) -> str:
    """
    Generează un mesaj profesional în limba Germană pentru vânzători din Germania și Austria.
    """
    salutation = f"Guten Tag {seller_name}," if seller_name and len(seller_name) < 25 else "Guten Tag Sehr geehrte Damen und Herren,"
    
    if offer_price_eur is None:
        calc = calculate_target_negotiation_price(asked_price_eur, seller_type, is_netto_eligible=is_company_buyer)
        offer_price_eur = calc["opening_offer_eur"]

    # Secțiune specifică pentru achiziție Netto pe firmă
    vat_section = ""
    if is_company_buyer:
        comp_str = company_name or "unsere rumänische Gesellschaft"
        vies_str = f"USt-IdNr.: {vat_id_vies}" if vat_id_vies else "gültiger USt-IdNr. (VIES)"
        vat_section = (
            f"\nDa wir als EU-Unternehmen ({comp_str}, {vies_str}) kaufen, "
            f"möchten wir das Fahrzeug im Rahmen einer steuerfreien innergemeinschaftlichen Lieferung (Export Netto) erwerben. "
            f"Alle erforderlichen Dokumente und die Gelangensbestätigung stellen wir selbstverständlich umgehend zur Verfügung.\n"
        )

    msg = f"""{salutation}

ich interessiere mich sehr für Ihr Inserat:
🚗 {car_title}
Angebotspreis: {asked_price_eur:,.0f} EUR

Um den Zustand vorab kurz zu klären, hätte ich vorab vier kurze Fragen:
1. Ist das Fahrzeug unfall- und nachlackierungsfrei?
2. Ist das Scheckheft lückenlos gepflegt (letzte Inspektion wann/bei wie viel km)?
3. Wie ist der aktuelle Zustand von Reifen und Bremsen?
4. Gibt es optische oder technische Mängel, die im Inserat nicht erwähnt wurden?
{vat_section}
Wenn der Wagen den Angaben entspricht, sind wir an einer schnellen und unkomplizierten Abwicklung interessiert.
Unser verbindliches Kaufangebot liegt bei:
👉 **{offer_price_eur:,.0f} EUR** {'(Netto-Export)' if is_company_buyer else '(Barzahlung / Sofortüberweisung)'}

Bei Einigung können wir den Kaufvertrag noch heute unterzeichnen, den Betrag per Echtzeit-Banküberweisung begleichen und die Abholung durch unsere Spedition innerhalb von 48-72 Stunden organisieren.

Über eine kurze Rückmeldung würde ich mich sehr freuen.

Mit freundlichen Grüßen,
{buyer_name}
Tel / WhatsApp: {buyer_phone}
"""
    return msg.strip()


def generate_english_negotiation_message(
    car_title: str,
    asked_price_eur: float,
    offer_price_eur: Optional[float] = None,
    seller_name: Optional[str] = None,
    seller_type: str = "Dealer",
    buyer_name: str = "Alexandru Popescu",
    buyer_phone: str = "+40 700 000 000",
    is_company_buyer: bool = False,
    company_name: Optional[str] = None,
    vat_id_vies: Optional[str] = None
) -> str:
    """
    Generează un mesaj profesional în limba Engleză pentru dealeri din Olanda, Belgia și piețe internaționale.
    """
    salutation = f"Dear {seller_name}," if seller_name and len(seller_name) < 25 else "Dear Sales Team,"

    if offer_price_eur is None:
        calc = calculate_target_negotiation_price(asked_price_eur, seller_type, is_netto_eligible=is_company_buyer)
        offer_price_eur = calc["opening_offer_eur"]

    vat_section = ""
    if is_company_buyer:
        comp_str = company_name or "our Romanian company"
        vies_str = f"VAT ID: {vat_id_vies}" if vat_id_vies else "valid European VIES VAT ID"
        vat_section = (
            f"\nAs we are purchasing as an EU registered company ({comp_str}, {vies_str}), "
            f"we would like to proceed under the intra-Community supply rules (zero-rated intra-EU B2B invoice). "
            f"We will provide the confirmation of arrival (Gelangensbestätigung / CMR consignment note) immediately upon delivery.\n"
        )

    msg = f"""{salutation}

I am writing regarding your vehicle listing:
🚗 {car_title}
Listed price: {asked_price_eur:,.0f} EUR

Before proceeding, could you please confirm the following details:
1. Is the car 100% accident-free and with original paint?
2. Is the service history complete (last service date & mileage)?
3. What is the current wear level of the tires and brakes?
4. Are there any known cosmetic or mechanical defects not visible in the photos?
{vat_section}
If everything matches your description, we are ready to purchase immediately without delays.
Our firm purchase offer is:
👉 **{offer_price_eur:,.0f} EUR** {'(Net export)' if is_company_buyer else '(Wire transfer / Cash)'}

Upon agreement, we can sign the purchase agreement today, initiate wire payment, and arrange pickup via our professional car transporter within 48 to 72 hours.

Looking forward to your prompt response.

Best regards,
{buyer_name}
Phone / WhatsApp: {buyer_phone}
"""
    return msg.strip()


def generate_negotiation_pack(
    car_title: str,
    asking_price_eur: float,
    country: str = "DE",
    seller_name: Optional[str] = None,
    seller_type: str = "Dealer",
    buyer_type: str = "persoana_fizica",
    buyer_name: str = "Alexandru Popescu",
    buyer_phone: str = "+40 700 000 000",
    company_name: Optional[str] = None,
    vat_id_vies: Optional[str] = None,
    mileage_km: Optional[int] = None,
    year: Optional[int] = None
) -> Dict[str, Any]:
    """Generează un pachet complet de negociere (prețuri țintă + scripturi în Germană și Engleză)."""
    is_company = buyer_type == "srl_platitor_tva_vies"
    pricing = calculate_target_negotiation_price(
        asked_price_eur=asking_price_eur,
        seller_type=seller_type,
        is_netto_eligible=is_company
    )

    german_msg = generate_german_negotiation_message(
        car_title=car_title,
        asked_price_eur=asking_price_eur,
        offer_price_eur=pricing["opening_offer_eur"],
        seller_name=seller_name,
        seller_type=seller_type,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        is_company_buyer=is_company,
        company_name=company_name,
        vat_id_vies=vat_id_vies
    )

    english_msg = generate_english_negotiation_message(
        car_title=car_title,
        asked_price_eur=asking_price_eur,
        offer_price_eur=pricing["opening_offer_eur"],
        seller_name=seller_name,
        seller_type=seller_type,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        is_company_buyer=is_company,
        company_name=company_name,
        vat_id_vies=vat_id_vies
    )

    return {
        "pricing": {
            "asking_price_eur": asking_price_eur,
            "opening_offer_eur": pricing["opening_offer_eur"],
            "target_offer_eur": pricing["target_buy_price_eur"],
            "base_calc_price_eur": pricing["base_calc_price_eur"],
            "is_netto_applied": is_company
        },
        "german_scripts": {
            "full_message": german_msg,
            "technical_inquiry": "Scheckheftgepflegt, Unfallfrei, TÜV",
            "netto_vat_inquiry": "Netto-Kauf (steuerfreie innergemeinschaftliche Lieferung MwSt)",
            "firm_purchase_offer": f"Unser verbindliches Kaufangebot liegt bei {pricing['opening_offer_eur']:,.0f} EUR"
        },
        "english_scripts": {
            "full_message": english_msg
        }
    }


if __name__ == "__main__":
    print("=== TEST GENERATOR MESAJE NEGOCIERE ===")
    sample_de = generate_german_negotiation_message(
        car_title="BMW 320d Touring xDrive M Sport",
        asked_price_eur=18500,
        seller_name="Autohaus Müller",
        seller_type="Dealer",
        is_company_buyer=True,
        company_name="Auto Trading SRL",
        vat_id_vies="RO12345678"
    )
    print("--- MESAJ GERMANĂ ---")
    print(sample_de)
