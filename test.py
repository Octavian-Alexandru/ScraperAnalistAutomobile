import pandas as pd


def analizeaza_modele():
    print("[*] Incarcam datele din ml_ready_listings.xlsx...")
    try:
        df = pd.read_excel('data/ml_ready_listings.xlsx')
    except FileNotFoundError:
        print("[!] Nu am gasit fisierul. Asigura-te ca rulezi din folderul corect.")
        return

    # Ne asiguram ca avem date curate in coloanele necesare
    df = df.dropna(subset=['Brand', 'Model'])

    # Curatam spatiile inutile de la inceput/sfarsit pentru a nu avea duplicate false
    df['Brand'] = df['Brand'].astype(str).str.strip()
    df['Model'] = df['Model'].astype(str).str.strip()

    output_file = 'modele_pe_marci.txt'

    print(f"[*] Generam raportul in {output_file}...")

    with open(output_file, 'w', encoding='utf-8') as f:
        brands = sorted(df['Brand'].unique())

        for brand in brands:
            # Extragem toate modelele unice pentru brandul curent
            modele_unice = sorted(df[df['Brand'] == brand]['Model'].unique())

            header = f"\n========================================\n"
            header += f"🚗 MARCA: {brand} ({len(modele_unice)} variante de model listate)\n"
            header += f"========================================\n"

            f.write(header)

            for model in modele_unice:
                # Numaram si cate masini au exact aceasta denumire (ne ajuta sa vedem anomaliile)
                count = len(df[(df['Brand'] == brand) & (df['Model'] == model)])
                line = f"  - {model}  ({count} anunturi)\n"
                f.write(line)

    print(f"[+] Raport generat cu succes! Deschide fisierul '{output_file}' pentru a analiza dezastrul. 😅")


if __name__ == "__main__":
    analizeaza_modele()