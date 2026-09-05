# analysis_olx.py
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import re
import os

INPUT_FILE = "unused/raw_listings_old.xlsx"
OUTPUT_DIR = "analysis"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Load data ---
df = pd.read_excel(INPUT_FILE)

# --- Preprocessing ---
# Convert numeric columns
for col in ['price', 'mileage_km', 'year']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

# Extract brand and model from title
def extract_brand_model(title):
    if pd.isna(title):
        return pd.NA, pd.NA
    parts = title.split()
    brand = parts[0] if len(parts) > 0 else pd.NA
    model = parts[1] if len(parts) > 1 else pd.NA
    return brand, model

df[['brand', 'model']] = df['title'].apply(lambda x: pd.Series(extract_brand_model(x)))

# Extract city from location (before comma)
df['city'] = df['location'].apply(lambda x: str(x).split(',')[0] if pd.notna(x) else pd.NA)

# --- Summary statistics ---
summary_stats = df[['price','mileage_km','year']].describe()
summary_stats.to_excel(os.path.join(OUTPUT_DIR, "summary_stats.xlsx"))
print("Summary statistics saved to summary_stats.xlsx")

# --- Listings per seller type ---
seller_counts = df['seller_type'].value_counts()
print("\nListings per seller type:")
print(seller_counts)

# --- Average price per brand ---
avg_price_brand = df.groupby('brand')['price'].mean().sort_values(ascending=False)
avg_price_brand.to_excel(os.path.join(OUTPUT_DIR, "avg_price_per_brand.xlsx"))
print("\nAverage price per brand saved to avg_price_per_brand.xlsx")

# --- Average price per city ---
avg_price_city = df.groupby('city')['price'].mean().sort_values(ascending=False)
avg_price_city.to_excel(os.path.join(OUTPUT_DIR, "avg_price_per_city.xlsx"))
print("\nAverage price per city saved to avg_price_per_city.xlsx")

# --- Plots ---
sns.set_style("whitegrid")

# Price distribution
plt.figure(figsize=(8,6))
sns.histplot(df['price'].dropna(), bins=30, kde=True)
plt.title("Distribution of Prices")
plt.xlabel("Price (EUR)")
plt.ylabel("Count")
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, "price_distribution.png"))
plt.close()

# Mileage distribution
plt.figure(figsize=(8,6))
sns.histplot(df['mileage_km'].dropna(), bins=30, kde=True)
plt.title("Distribution of Mileage (km)")
plt.xlabel("Mileage (km)")
plt.ylabel("Count")
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, "mileage_distribution.png"))
plt.close()

# Year distribution
plt.figure(figsize=(8,6))
sns.histplot(df['year'].dropna(), bins=range(1990,2026), kde=False)
plt.title("Distribution of Car Years")
plt.xlabel("Year")
plt.ylabel("Count")
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, "year_distribution.png"))
plt.close()

# Average price per brand (top 10)
top_brands = avg_price_brand.head(10)
plt.figure(figsize=(10,6))
sns.barplot(x=top_brands.values, y=top_brands.index, palette="viridis")
plt.xlabel("Average Price (EUR)")
plt.ylabel("Brand")
plt.title("Top 10 Brands by Average Price")
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, "top10_brands_avg_price.png"))
plt.close()

print("\nAnalysis complete. All plots saved to the 'analysis' folder.")
