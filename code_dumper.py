import os

# Calea exactă către backend-ul tău
TARGET_DIR = r"C:\Users\ALEXANDRU\Documents\MASINI Scrapping si ML"
OUTPUT_FILE = "backend_code_dump.txt"

# Adăugăm o listă de FIȘIERE complet interzise (Securitate Critică)
EXCLUDED_FILES = {'.env', 'serviceAccountKey.json', 'backend_code_dump.txt'}

EXCLUDED_EXTENSIONS = {'.json', '.csv', '.pyc', '.sqlite3', '.db', '.log', '.md', '.txt'}
EXCLUDED_DIRS = {'__pycache__', '.venv', 'venv', '.git', '.idea'}

def generate_code_dump():
    if not os.path.exists(TARGET_DIR):
        print(f"Eroare: Directorul {TARGET_DIR} nu există.")
        return

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        for root, dirs, files in os.walk(TARGET_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

            for file in files:
                # 1. Filtru de securitate: Blocăm fișierele specifice
                if file in EXCLUDED_FILES:
                    continue

                # 2. Filtru de extensie
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDED_EXTENSIONS:
                    continue

                filepath = os.path.join(root, file)

                # Formatăm output-ul exact cum mi l-ai dat pe cel de Kotlin
                outfile.write("=" * 80 + "\n")
                outfile.write(f"FILE: {filepath}\n")
                outfile.write("=" * 80 + "\n\n")

                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read() + "\n\n")
                except Exception as e:
                    outfile.write(f"// EROARE LA CITIRE: {e}\n\n")

    print(f"SUCCESS: Code dump generat în '{OUTPUT_FILE}'.")
    print("Aștept să dai copy-paste la conținut pentru audit.")


if __name__ == "__main__":
    generate_code_dump()