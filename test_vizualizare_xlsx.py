import pandas as pd

# Specifică Calea către Fișierul tău XLSX
cale_fisier = 'data/raw_listings_old.xlsx'

try:
    # Încărcarea datelor în DataFrame
    df = pd.read_excel(cale_fisier)

    # ----------------------------------------------------
    # LOCUL CRUCIAL: Adaugă un Breakpoint AICI!
    # ----------------------------------------------------
    print("DataFrame-ul a fost încărcat.")  # <-- Click în stânga, pe acest rând

    # Poți continua cu prelucrarea datelor
    # print(df.head())

except FileNotFoundError:
    print(f"Eroare: Fișierul '{cale_fisier}' nu a fost găsit.")