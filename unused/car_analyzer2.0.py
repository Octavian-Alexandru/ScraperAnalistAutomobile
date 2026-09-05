import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import numpy as np
import os

# === Încărcare fișier ===
file_path = "raw_listings_old.xlsx"

if not os.path.exists(file_path):
    print(f"[EROARE] Fișierul {file_path} nu există!")
    exit()

df = pd.read_excel(file_path)

print("Date încărcate. Primele 5 intrări:")
print(df.head())

# === Curățare date ===
print("\n[INFO] Curățare set de date...")

# Eliminăm kilometri imposibili (>1 milion)
if "mileage_km" in df.columns:
    df = df[df["mileage_km"] < 1_000_000]

# Înlocuim valorile lipsă cu mediane
for col in ["mileage_km", "year", "price"]:
    if col in df.columns:
        if df[col].isnull().any():
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            print(f"[INFO] Coloana {col} - NaN înlocuite cu mediana {median_val}")

# Pregătim datele pentru model
df_model = df[["price", "mileage_km", "year"]].dropna()

print(f"[INFO] Set pregătit pentru ML: {df_model.shape[0]} rânduri, {df_model.shape[1]} coloane")
print(df_model.head())

# === Verificare dimensiune ===
if df_model.shape[0] < 10:
    print("\n[AVERTISMENT] Prea puține date curate pentru ML. Se vor face doar statistici simple.")

    # Analiză simplă: medii și top deals după raport preț/an/km
    df["ratio_price_year_km"] = df["price"] / (df["year"] * (df["mileage_km"] / 1000 + 1))
    top_deals = df.sort_values("ratio_price_year_km").head(10)

    print("\n=== TOP 10 DEALS (fără ML, doar pe raport preț/an/km) ===")
    print(top_deals[["title", "price", "year", "mileage_km", "ratio_price_year_km"]])

else:
    # === Împărțire train/test ===
    X = df_model[["mileage_km", "year"]]
    y = df_model["price"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # === Model ML ===
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    # === Metrici ===
    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    rmse = mse ** 0.5
    r2 = r2_score(y_test, y_pred)

    print("\n=== Performanță model ===")
    print(f"MAE: {mae:.2f} EUR")
    print(f"RMSE: {rmse:.2f} EUR")
    print(f"R2: {r2:.3f}")

    # === Predicții pe toate datele ===
    df["predicted_price"] = model.predict(df[["mileage_km", "year"]])
    df["profit_score"] = (df["predicted_price"] - df["price"]) / df["predicted_price"]

    # === Top deals ===
    top_deals = df.sort_values("profit_score", ascending=False).head(20)
    print("\n=== Top mașini după scor de rentabilitate ===")
    print(top_deals[["title", "price", "predicted_price", "year", "mileage_km", "profit_score"]])

    # === Vizualizări ===
    plt.figure(figsize=(8, 5))
    plt.hist(df["profit_score"].dropna(), bins=20, color="blue", alpha=0.7)
    plt.title("Distribuția scorurilor de profitabilitate")
    plt.xlabel("Scor de profitabilitate")
    plt.ylabel("Frecvență")
    plt.show()

    plt.figure(figsize=(8, 5))
    plt.scatter(y_test, y_pred, alpha=0.6)
    plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], "r--")
    plt.xlabel("Preț real")
    plt.ylabel("Preț estimat")
    plt.title("Preț real vs Preț estimat")
    plt.show()

    # === Recomandări personalizate ===
    print("\n==================================================")
    print("RECOMANDĂRI PERSONALIZATE:")
    print("==================================================\n")

    for i, row in top_deals.head(5).iterrows():
        economie = row["predicted_price"] - row["price"]
        print(f"{row['title']}")
        print(f"   Preț: {row['price']} EUR vs Preț estimat: {row['predicted_price']:.0f} EUR")
        print(f"   An: {int(row['year'])}, Km: {int(row['mileage_km'])}")
        print(f"   Scor rentabilitate: {row['profit_score']:.3f}")
        print(f"   Economie estimată: {economie:.0f} EUR\n")

    # === Salvare în Excel ===
    output_file = "car_analysis_results.xlsx"
    with pd.ExcelWriter(output_file) as writer:
        df.to_excel(writer, sheet_name="All Cars + Scores", index=False)
        top_deals.to_excel(writer, sheet_name="Top Deals", index=False)
        pd.DataFrame(
            {"MAE": [mae], "RMSE": [rmse], "R2": [r2]}
        ).to_excel(writer, sheet_name="Model Performance", index=False)

    print(f"\n[INFO] Rezultatele au fost salvate în {output_file}")
