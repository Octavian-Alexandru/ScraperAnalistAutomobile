import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import mean_absolute_error
import requests
from textblob import TextBlob
import warnings
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime

warnings.filterwarnings('ignore')


class PartPriceScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def search_part_prices(self, brand, model, year, part_name):
        """Caută prețurile pieselor pe multiple site-uri"""
        search_queries = self._generate_search_queries(brand, model, year, part_name)
        prices = []

        for query in search_queries:
            try:
                # Autovit
                autovit_prices = self._scrape_autovit(query)
                prices.extend(autovit_prices)

                # OLX
                olx_prices = self._scrape_olx(query)
                prices.extend(olx_prices)

                time.sleep(1)  # Respectful delay between requests

            except Exception as e:
                print(f"Eroare la scraping pentru {query}: {e}")

        return self._analyze_prices(prices)

    def _generate_search_queries(self, brand, model, year, part_name):
        """Generează query-uri de căutare relevante"""
        queries = [
            f"{brand} {model} {year} {part_name}",
            f"{brand} {model} {part_name}",
            f"{part_name} {brand} {model}",
            f"{part_name} auto {brand}"
        ]
        return queries

    def _scrape_autovit(self, query):
        """Scrape Autovit pentru piese"""
        prices = []
        try:
            url = f"https://www.autovit.ro/auto-piese/?search%5Bfilter_enum_condition%5D=used&search%5Bkeywords%5D={requests.utils.quote(query)}"
            response = self.session.get(url, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Actualizează selectorul bazat pe structura site-ului
            price_elements = soup.find_all('span', class_=lambda x: x and 'price' in x.lower())
            for elem in price_elements[:10]:
                price_text = elem.text.strip()
                price = self._extract_price(price_text)
                if price and 10 <= price <= 10000:  # Filtru realist pentru piese auto
                    prices.append(price)

        except Exception as e:
            print(f"Eroare Autovit scraping: {e}")

        return prices

    def _scrape_olx(self, query):
        """Scrape OLX pentru piese"""
        prices = []
        try:
            url = f"https://www.olx.ro/auto-piese-accessorii/auto-piese/q-{query.replace(' ', '-')}/"
            response = self.session.get(url, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Caută prețurile în OLX
            price_elements = soup.find_all('p', class_=lambda x: x and 'price' in x.lower())
            for elem in price_elements[:10]:
                price_text = elem.text.strip()
                price = self._extract_price(price_text)
                if price and 10 <= price <= 10000:
                    prices.append(price)

        except Exception as e:
            print(f"Eroare OLX scraping: {e}")

        return prices

    def _extract_price(self, text):
        """Extrage prețul din text"""
        try:
            # Curăță textul și extrage numerele
            clean_text = re.sub(r'[^\d\s]', '', text)
            matches = re.findall(r'\d+', clean_text)
            if matches:
                price = int(matches[0])
                return price
        except:
            return None

    def _analyze_prices(self, prices):
        """Analizează prețurile găsite"""
        if not prices:
            return None

        valid_prices = [p for p in prices if p is not None]
        if not valid_prices:
            return None

        # Folosește media trunchiată pentru a elimina outlier-ele
        sorted_prices = sorted(valid_prices)
        n = len(sorted_prices)
        if n <= 2:
            avg_price = sum(sorted_prices) / n
        else:
            # Elimină 20% din extreme
            trim_count = max(1, n // 5)
            trimmed_prices = sorted_prices[trim_count:-trim_count]
            avg_price = sum(trimmed_prices) / len(trimmed_prices)

        return {
            'min': min(valid_prices),
            'max': max(valid_prices),
            'avg': avg_price,
            'count': len(valid_prices)
        }


class PartPriceAPI:
    def __init__(self):
        self.cache = {}

    def get_part_prices(self, brand, model, year, part_type):
        """Obține prețuri estimate pentru piese"""
        cache_key = f"{brand}_{model}_{year}_{part_type}"

        if cache_key in self.cache:
            return self.cache[cache_key]

        # Simulare prețuri bazate pe brand și tipul piesei
        price_ranges = {
            'revizie': {'volkswagen': (200, 400), 'bmw': (400, 600), 'audi': (350, 550), 'default': (250, 450)},
            'distributie': {'volkswagen': (500, 800), 'bmw': (800, 1200), 'audi': (700, 1000), 'default': (600, 900)},
            'ambreiaj': {'volkswagen': (700, 1000), 'bmw': (1000, 1500), 'audi': (900, 1300), 'default': (800, 1100)},
            'frane': {'volkswagen': (300, 500), 'bmw': (500, 800), 'audi': (400, 600), 'default': (350, 550)},
            'suspensie': {'volkswagen': (600, 900), 'bmw': (900, 1400), 'audi': (800, 1200), 'default': (700, 1000)}
        }

        brand_lower = brand.lower()
        if brand_lower in price_ranges[part_type]:
            price_range = price_ranges[part_type][brand_lower]
        else:
            price_range = price_ranges[part_type]['default']

        # Simulează câteva prețuri în interval
        simulated_prices = [
            np.random.uniform(price_range[0], price_range[1])
            for _ in range(5)
        ]

        result = {
            'estimated_price': sum(simulated_prices) / len(simulated_prices),
            'price_range': price_range,
            'sources_count': len(simulated_prices)
        }

        self.cache[cache_key] = result
        return result


class PriceCache:
    def __init__(self, max_size=1000, ttl_hours=24):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl_hours * 3600  # seconds

    def get(self, key):
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['data']
            else:
                del self.cache[key]
        return None

    def set(self, key, data):
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k]['timestamp'])
            del self.cache[oldest_key]

        self.cache[key] = {
            'data': data,
            'timestamp': time.time()
        }


class AdvancedCarProfitabilityAnalyzer:
    def __init__(self):
        # Inițializare modele și encodere
        self.price_model = None
        self.maintenance_model = None
        self.encoders = {}
        self.scaler = StandardScaler()
        self.feature_columns = []

        # Inițializare scrapers și API-uri
        self.part_scraper = PartPriceScraper()
        self.part_api = PartPriceAPI()
        self.price_cache = PriceCache()

        # Baza de date redusă cu costuri default
        self.maintenance_costs_db = {
            'default': {
                'revizie': {'piese': 300, 'manoperă': 200},
                'ambreiaj': {'piese': 800, 'manoperă': 500},
                'distributie': {'piese': 600, 'manoperă': 400},
                'frane': {'piese': 400, 'manoperă': 300},
                'suspensie': {'piese': 800, 'manoperă': 600},
            }
        }

        # Date despre cerere și ofertă pe piață
        self.market_demand = {
            'volkswagen': 0.8, 'bmw': 0.7, 'audi': 0.75, 'opel': 0.6,
            'ford': 0.65, 'renault': 0.55, 'dacia': 0.7, 'skoda': 0.68,
            'default': 0.5
        }

    def load_and_preprocess_data(self, file_path):
        """Încarcă și prelucrează datele din Excel"""
        df = pd.read_excel(file_path)
        df = self._clean_data(df)
        df = self._create_features(df)
        df['sentiment_score'] = df['description'].apply(self._analyze_sentiment)
        return df

    def _clean_data(self, df):
        """Curățare și pregătire date"""
        df = df.dropna(subset=['price'])
        df['price'] = df['price'].astype(str).str.replace(r'[^\d.]', '', regex=True)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df = df.dropna(subset=['price'])

        Q1 = df['price'].quantile(0.05)
        Q3 = df['price'].quantile(0.95)
        IQR = Q3 - Q1
        df = df[~((df['price'] < (Q1 - 1.5 * IQR)) | (df['price'] > (Q3 + 1.5 * IQR)))]
        return df

    def _create_features(self, df):
        """Creează feature-uri noi din datele existente"""
        df['brand'] = df['title'].str.split().str[0].str.lower()
        current_year = pd.Timestamp.now().year
        df['age'] = current_year - df['year']
        df['price_per_km'] = df['price'] / (df['mileage_km'].replace(0, 1))

        df['mileage_category'] = pd.cut(df['mileage_km'],
                                        bins=[0, 50000, 100000, 150000, 200000, float('inf')],
                                        labels=['foarte_putini', 'putini', 'mediu', 'multi', 'foarte_multi'])
        return df

    def _analyze_sentiment(self, text):
        """Analizează sentimentul din descrierea mașinii"""
        if pd.isna(text):
            return 0.5
        try:
            analysis = TextBlob(str(text))
            return (analysis.sentiment.polarity + 1) / 2
        except:
            return 0.5

    def get_average_price_from_api(self, brand, model, year):
        """Obține prețul mediu de piață prin web scraping"""
        try:
            # Cache pentru a evita căutări duplicate
            cache_key = f"{brand}_{model}_{year}_price"
            cached_price = self.price_cache.get(cache_key)
            if cached_price:
                return cached_price

            # Generează query-uri de căutare
            queries = [
                f"{brand} {model} {year}",
                f"{brand} {model} an {year}",
                f"{brand} {model} second hand {year}"
            ]

            all_prices = []

            for query in queries:
                try:
                    # Caută pe Autovit
                    autovit_prices = self._scrape_autovit_car_prices(query, year)
                    all_prices.extend(autovit_prices)

                    # Caută pe OLX
                    olx_prices = self._scrape_olx_car_prices(query)
                    all_prices.extend(olx_prices)

                    time.sleep(1)  # Respect rate limiting

                except Exception as e:
                    print(f"Eroare la căutarea pentru '{query}': {e}")
                    continue

            # Analizează prețurile găsite
            if all_prices:
                valid_prices = [p for p in all_prices if 1000 <= p <= 100000]  # Filtru realist
                if valid_prices:
                    # Media trunchiată pentru a elimina outlier-ele
                    sorted_prices = sorted(valid_prices)
                    n = len(sorted_prices)
                    trim_count = max(1, n // 4)  # Elimină 25% din extreme

                    if n > 2 * trim_count:
                        trimmed_prices = sorted_prices[trim_count:-trim_count]
                        avg_price = sum(trimmed_prices) / len(trimmed_prices)
                    else:
                        avg_price = sum(sorted_prices) / n

                    # Salvează în cache
                    self.price_cache.set(cache_key, avg_price)
                    return avg_price

            # Fallback la estimare bazată pe vârstă dacă nu găsim prețuri
            base_price = self._estimate_base_price(brand, model)
            current_year = pd.Timestamp.now().year
            age = current_year - year
            estimated_price = base_price * (0.85 ** age)  # Depreciere de 15% pe an

            self.price_cache.set(cache_key, estimated_price)
            return estimated_price

        except Exception as e:
            print(f"Eroare la obținerea prețului mediu: {e}")
            return self._estimate_fallback_price(brand, model, year)

    def _scrape_autovit_car_prices(self, query, year):
        """Scrape prețuri mașini de pe Autovit"""
        prices = []
        try:
            url = f"https://www.autovit.ro/autoturisme/?search%5Bkeywords%5D={requests.utils.quote(query)}"

            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, timeout=15)

            soup = BeautifulSoup(response.text, 'html.parser')

            # Caută toate elementele care conțin prețuri
            price_elements = soup.find_all(['span', 'div', 'p'],
                                           class_=lambda x: x and 'price' in str(x).lower(),
                                           string=re.compile(r'\d'))

            for elem in price_elements[:25]:  # Limitează la primele 25
                price_text = elem.text.strip()
                price = self._extract_numeric_price(price_text)
                if price and 1000 <= price <= 100000:
                    prices.append(price)

        except Exception as e:
            print(f"Eroare Autovit car scraping: {e}")

        return prices

    def _scrape_olx_car_prices(self, query):
        """Scrape prețuri mașini de pe OLX"""
        prices = []
        try:
            formatted_query = query.replace(' ', '-')
            url = f"https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/q-{formatted_query}/"

            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, timeout=15)

            soup = BeautifulSoup(response.text, 'html.parser')

            # Caută prețuri în OLX
            price_elements = soup.find_all('p',
                                           class_=lambda x: x and 'price' in str(x).lower(),
                                           string=re.compile(r'\d'))

            for elem in price_elements[:25]:
                price_text = elem.text.strip()
                price = self._extract_numeric_price(price_text)
                if price and 1000 <= price <= 100000:
                    prices.append(price)

        except Exception as e:
            print(f"Eroare OLX car scraping: {e}")

        return prices

    def _extract_numeric_price(self, text):
        """Extrage prețul numeric din text"""
        try:
            # Curăță textul și extrage numerele
            clean_text = re.sub(r'[^\d\s]', '', text)
            numbers = re.findall(r'\d+', clean_text)

            if numbers:
                # Dacă sunt mai multe numere, ia-l pe cel mai mare (presupunând că e prețul)
                price = int(max(numbers, key=len))

                # Verifică dacă prețul are sens (între 1.000 și 100.000 EUR)
                if 1000 <= price <= 100000:
                    return price

        except:
            pass

        return None

    def _estimate_base_price(self, brand, model):
        """Estimează prețul de bază pentru o marcă/model"""
        brand_prices = {
            'volkswagen': 12000, 'bmw': 20000, 'audi': 18000, 'mercedes': 22000,
            'opel': 9000, 'ford': 10000, 'renault': 8000, 'dacia': 6000,
            'skoda': 9500, 'seat': 8500, 'fiat': 7000, 'peugeot': 8000,
            'citroen': 7500, 'toyota': 11000, 'honda': 10500, 'nissan': 9500,
            'hyundai': 8500, 'kia': 8000, 'default': 10000
        }

        brand_lower = brand.lower()
        return brand_prices.get(brand_lower, brand_prices['default'])

    def _estimate_fallback_price(self, brand, model, year):
        """Estimare fallback bazată pe brand și vârstă"""
        base_price = self._estimate_base_price(brand, model)
        current_year = pd.Timestamp.now().year
        age = current_year - year

        # Depreciere mai realistă
        if age == 0:
            depreciation = 0.8  # -20% imediat
        elif age == 1:
            depreciation = 0.7  # -30% după 1 an
        else:
            depreciation = 0.65 * (0.9 ** (age - 1))  # -10% pe an ulterior

        return base_price * depreciation

    def estimate_maintenance_costs(self, brand, model, year, mileage, age):
        """Estimează costurile de întreținere bazate pe prețuri reale"""
        cache_key = f"{brand}_{model}_{year}_maint"
        cached_costs = self.price_cache.get(cache_key)

        if cached_costs:
            return self._calculate_total_costs(cached_costs, mileage, age)

        # Obține prețuri reale de pe internet
        part_costs = {}

        for part_type in ['revizie', 'distributie', 'ambreiaj', 'frane', 'suspensie']:
            # Încearcă mai întâi scraping-ul
            scraped_prices = self.part_scraper.search_part_prices(brand, model, year, part_type)

            if scraped_prices:
                part_costs[part_type] = scraped_prices['avg']
            else:
                # Fallback la API simulated
                api_prices = self.part_api.get_part_prices(brand, model, year, part_type)
                part_costs[part_type] = api_prices['estimated_price']

        # Salvează în cache
        self.price_cache.set(cache_key, part_costs)

        return self._calculate_total_costs(part_costs, mileage, age)

    def _calculate_total_costs(self, part_costs, mileage, age):
        """Calculează costurile totale bazate pe uzură"""
        total_cost = 0

        # Cost de bază pentru revizie (piese + manoperă)
        total_cost += part_costs['revizie'] * 1.3  # +30% pentru manoperă

        # Costuri suplimentare bazate pe kilometraj și vârstă
        if mileage > 80000:
            total_cost += part_costs['distributie'] * 1.4  # +40% manoperă

        if mileage > 100000:
            total_cost += part_costs['ambreiaj'] * 1.5 * 0.7  # +50% manoperă, 70% uzură

        if age > 8:
            total_cost += part_costs['suspensie'] * 1.4 * 0.5  # +40% manoperă, 50% uzură

        return total_cost

    def get_market_demand(self, brand):
        """Obține scorul de cerere pe piață pentru o marcă"""
        brand_lower = brand.lower()
        return self.market_demand.get(brand_lower, self.market_demand['default'])

    def train_models(self, df):
        """Antrenează modelele de predicție"""
        categorical_cols = ['brand', 'location', 'seller_type', 'mileage_category']
        for col in categorical_cols:
            if col in df.columns:
                le = LabelEncoder()
                df[col] = le.fit_transform(df[col].astype(str))
                self.encoders[col] = le

        feature_cols = ['year', 'mileage_km', 'brand', 'age', 'price_per_km',
                        'location', 'seller_type', 'mileage_category', 'sentiment_score']
        self.feature_columns = [col for col in feature_cols if col in df.columns]

        X = df[self.feature_columns]
        y_price = df['price']

        X_train, X_test, y_train, y_test = train_test_split(
            X, y_price, test_size=0.2, random_state=42
        )

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        self.price_model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.price_model.fit(X_train_scaled, y_train)

        y_pred = self.price_model.predict(X_test_scaled)
        mae = mean_absolute_error(y_test, y_pred)
        print(f"Precizia modelului de preț: MAE = {mae:.2f}")

        return self

    def predict_profitability(self, car_data):
        """Predictie rentabilitate pentru o mașină"""
        if self.price_model is None:
            raise ValueError("Modelele nu au fost antrenate. Te rog antrenează-le mai întâi.")

        # Extrage brand și model
        title_parts = car_data['title'].split()
        brand = title_parts[0].lower()
        model = ' '.join(title_parts[1:3]).lower() if len(title_parts) > 2 else 'unknown'
        year = car_data['year']

        # Pregătește datele pentru predicție
        car_df = self._prepare_car_data(car_data)
        car_scaled = self.scaler.transform(car_df[self.feature_columns])

        # Prezice prețul de piață
        predicted_price = self.price_model.predict(car_scaled)[0]

        # Obține prețul mediu de la API (web scraping)
        api_price = self.get_average_price_from_api(brand, model, year)

        if api_price:
            final_predicted_price = (predicted_price + api_price) / 2
            price_source = "combinație model propriu + web scraping"
        else:
            final_predicted_price = predicted_price
            price_source = "model propriu"

        # Estimează costurile de întreținere bazate pe prețuri reale
        maintenance_cost = self.estimate_maintenance_costs(
            brand, model, year, car_data['mileage_km'], car_data['age']
        )

        # Analizează sentimentul
        sentiment_score = self._analyze_sentiment(car_data.get('description', ''))
        market_demand_score = self.get_market_demand(brand)

        # Calculează profitabilitatea
        price_difference = car_data['price'] - final_predicted_price
        profit_margin = price_difference - maintenance_cost

        sentiment_adjustment = 0.1 * (sentiment_score - 0.5)
        demand_adjustment = 0.15 * (market_demand_score - 0.5)

        adjusted_profit_margin = profit_margin * (1 + sentiment_adjustment + demand_adjustment)
        profitability_score = adjusted_profit_margin / final_predicted_price if final_predicted_price > 0 else -1

        # Determină ratingul
        if profitability_score > 0.25:
            rating = "Foarte rentabilă"
        elif profitability_score > 0.15:
            rating = "Rentabilă"
        elif profitability_score > 0.05:
            rating = "Ușor rentabilă"
        elif profitability_score > -0.05:
            rating = "Puțin nerentabilă"
        elif profitability_score > -0.15:
            rating = "Nerentabilă"
        else:
            rating = "Foarte nerentabilă"

        return {
            'predicted_market_price': round(final_predicted_price, 2),
            'price_source': price_source,
            'estimated_maintenance_cost': round(maintenance_cost, 2),
            'profit_margin': round(profit_margin, 2),
            'adjusted_profit_margin': round(adjusted_profit_margin, 2),
            'profitability_score': round(profitability_score, 3),
            'rating': rating,
            'sentiment_score': round(sentiment_score, 3),
            'market_demand_score': round(market_demand_score, 3),
            'maintenance_breakdown': self.get_maintenance_breakdown(brand, model, year, car_data['mileage_km'],
                                                                    car_data['age'])
        }

    def get_maintenance_breakdown(self, brand, model, year, mileage, age):
        """Returnează defalcarea costurilor de întreținere"""
        cache_key = f"{brand}_{model}_{year}_breakdown"
        part_costs = self.price_cache.get(cache_key)

        if not part_costs:
            # Dacă nu sunt în cache, estimează-le
            part_costs = {}
            for part_type in ['revizie', 'distributie', 'ambreiaj', 'frane', 'suspensie']:
                api_prices = self.part_api.get_part_prices(brand, model, year, part_type)
                part_costs[part_type] = api_prices['estimated_price']

        breakdown = {}
        for part_type, cost in part_costs.items():
            breakdown[part_type] = {
                'piese': round(cost, 2),
                'manoperă': round(cost * 0.3, 2)  # 30% manoperă estimativ
            }

        return breakdown

    def _prepare_car_data(self, car_data):
        """Pregătește datele unei mașini pentru predicție"""
        car_df = pd.DataFrame([car_data])
        car_df['brand'] = car_df['title'].str.split().str[0].str.lower()
        current_year = pd.Timestamp.now().year
        car_df['age'] = current_year - car_df['year']
        car_df['price_per_km'] = car_df['price'] / (car_df['mileage_km'].replace(0, 1))

        car_df['mileage_category'] = pd.cut(car_df['mileage_km'],
                                            bins=[0, 50000, 100000, 150000, 200000, float('inf')],
                                            labels=['foarte_putini', 'putini', 'mediu', 'multi', 'foarte_multi'])

        car_df['sentiment_score'] = self._analyze_sentiment(car_data.get('description', ''))

        for col, encoder in self.encoders.items():
            if col in car_df.columns:
                car_df[col] = car_df[col].apply(lambda x: x if x in encoder.classes_ else 'unknown')
                if 'unknown' not in encoder.classes_:
                    encoder.classes_ = np.append(encoder.classes_, 'unknown')
                car_df[col] = encoder.transform(car_df[col])

        for col in self.feature_columns:
            if col not in car_df.columns:
                car_df[col] = 0

        return car_df


# Exemplu de utilizare
if __name__ == "__main__":
    # Inițializează analyzer-ul
    analyzer = AdvancedCarProfitabilityAnalyzer()

    # Încarcă și prelucrează datele
    try:
        # Exemplu - în loc de fișier, folosește date simulate
        sample_data = {
            'title': ['Volkswagen Golf 1.6 TDI', 'BMW Series 3 2.0', 'Dacia Logan 1.4'],
            'price': [8500, 15000, 5000],
            'year': [2015, 2016, 2017],
            'mileage_km': [125000, 80000, 60000],
            'location': ['Bucuresti', 'Cluj', 'Iasi'],
            'seller_type': ['profesionist', 'particular', 'profesionist'],
            'description': ['Stare excelenta', 'Foarte bine intretinuta', 'Masina de oras']
        }
        df = pd.DataFrame(sample_data)

        # Feature engineering
        df = analyzer._create_features(df)
        df['sentiment_score'] = df['description'].apply(analyzer._analyze_sentiment)

        print(f"Date prelucrate: {len(df)} mașini")

        # Antrenează modelele
        analyzer.train_models(df)

        # Exemplu de evaluare a unei mașini
        sample_car = {
            'car_id': 'test_123',
            'title': 'Volkswagen Golf 1.6 TDI',
            'seller': 'Autohaus',
            'location': 'Bucuresti',
            'price': 8500,
            'currency': 'RON',
            'description': 'Masina in stare excelenta, intretinuta la reprezentanta, dotari complete, fara accidente',
            'mileage_km': 125000,
            'year': 2015,
            'seller_type': 'profesionist',
            'url': 'https://www.olx.ro/oferta/volkswagen-golf-IDabc123.html',
            'scrape_date': '2023-10-15'
        }

        current_year = pd.Timestamp.now().year
        sample_car['age'] = current_year - sample_car['year']

        # Obține evaluarea rentabilității
        evaluation = analyzer.predict_profitability(sample_car)

        print("\n=== EVALUARE RENTABILITATE ===")
        print(f"Preț cerut: {sample_car['price']} RON")
        print(f"Preț estimat de piață: {evaluation['predicted_market_price']} RON ({evaluation['price_source']})")
        print(f"Cost estimat întreținere: {evaluation['estimated_maintenance_cost']} RON")
        print(f"Marjă de profit: {evaluation['profit_margin']} RON")
        print(f"Marjă de profit ajustată: {evaluation['adjusted_profit_margin']} RON")
        print(f"Scor rentabilitate: {evaluation['profitability_score']}")
        print(f"Rating: {evaluation['rating']}")
        print(f"Scor sentiment: {evaluation['sentiment_score']}")
        print(f"Scor cerere piață: {evaluation['market_demand_score']}")

        print("\n=== DETALII COSTURI ÎNTREȚINERE ===")
        for component, costs in evaluation['maintenance_breakdown'].items():
            print(f"{component.capitalize()}: {costs['piese']} RON (piese) + {costs['manoperă']} RON (manoperă)")

    except Exception as e:
        print(f"Eroare: {e}")
        import traceback

        traceback.print_exc()