# 🚀 ROADMAP: Implementări pentru Randament Economic Maxim

> **Proiect:** ScraperAnalistAutomobile  
> **Data Analizei:** 29 Octombrie 2026  
> **Scop:** Lista completă de funcționalități care transformă proiectul dintr-un tool tehnic într-un **motor de profit real** pe piața auto din România.

---

## 📊 STAREA CURENTĂ A PROIECTULUI

| Componentă | Status | Observații |
|---|---|---|
| Scrapere (7 surse) | ✅ Funcțional | AutoUncle, Autovit, OLX, CautiMasina, BestAuto, PlusAuto, CarZZ |
| Baza de date SQLite | ✅ Funcțional | ~71MB, tracking prețuri, istoric complet |
| Pipeline zilnic (GitHub Actions) | ✅ Funcțional | 4x/zi arbitraj rapid + 1x/noapte deep scrape |
| Model ML (RandomForest) | ✅ Funcțional | Estimare preț + detecție chilipiruri |
| Dashboard Streamlit | ✅ Funcțional | 3 tab-uri + 2 pagini extra (Laborator ML + Analiză Ofertă) |
| Alerte Discord/Telegram | ✅ Funcțional | Push automat la scăderi de preț și oportunități de arbitraj |

### Ce lipsește pentru randament economic real:

---

## 🔴 PRIORITATE CRITICĂ (Impact Financiar Direct)

### 1. Scraper pentru Fotografii Auto + Detecție Stare Vizuală (Computer Vision)

**De ce contează economic:** Un dealer care face flipping câștigă sau pierde bani în funcție de starea reală a mașinii. 90% din capcane (vopsite, lovite, rugină) se văd din poze, nu din text.

**Ce trebuie implementat:**
- Descărcare automată a primelor 3-5 poze din fiecare anunț (URL-urile sunt deja accesibile pe paginile scraped)
- Integrare cu un model de Computer Vision (ex: model fine-tuned pe baza CLIP sau un CNN dedicat) care clasifică:
  - ✅ Stare excelentă / ⚠️ Posibil avariată / ❌ Recondiționată suspect
  - Detectare vopsea refăcută (diferențe de ton între panouri)
  - Detectare numere de înmatriculare temporare (mașini din import proaspăt)
- Scor de „Risc Vizual" (0-100) adăugat în baza de date și afișat în dashboard

**Estimare efort:** ~3-5 zile dezvoltare  
**ROI:** Evitarea chiar și a unei singure achiziții greșite de 1.000-3.000 EUR recuperează complet investiția.

---

### 2. Estimator Costuri de Reparație și Recondiționare per Model

**De ce contează economic:** Marja reală de profit NU este `preț_estimat_ML - preț_cerut`. Este `preț_vânzare_realist - preț_achiziție - costuri_recondiționare - taxe`.

**Ce trebuie implementat:**
- Tabel/bază de date cu costuri medii de recondiționare pe `(Brand, Model, An)`:
  - Revizie completă (ulei, filtre, bujii)
  - Kit distribuție
  - Set ambreiaj
  - Frâne complete (discuri + plăcuțe)
  - Suspensie (articulații, bielete, amortizoare)
  - Cosmetică (polish, detailing interior, mici reparații tapițerie)
- Algoritmul de arbitraj din `run_daily_pipeline.py` trebuie să scadă automat costul mediu de recondiționare din marja de profit
- Dashboard: coloană nouă „Profit Net Estimat (după recondiționare)" în tabelul de chilipiruri

**NOTĂ IMPORTANTĂ:** Fișierul `results/evaluation_test_123.json` arată că ai început deja o schiță a acestui sistem (cu breakdown pe revizie, distribuție, ambreiaj, frâne, suspensie). Trebuie industrializat și integrat în pipeline.

**Estimare efort:** ~2-3 zile  
**ROI:** Elimină complet tranzacțiile care par profitabile dar nu sunt (cel mai frecvent motiv de pierdere în flipping auto).

---

### 3. Sistem de Scoring Compozit al Oportunității (Deal Score)

**De ce contează economic:** Acum primești o listă de chilipiruri sortate doar după marja brută. Un dealer trebuie să vadă INSTANT care ofertă merită timp, bani și deplasare.

**Ce trebuie implementat:**
- **Deal Score (0-100)** calculat din:
  - `marja_profit_net` (după recondiționare) - 30% din scor
  - `lichiditate_model` (cât de repede se vând mașinile de acel model în baza de date) - 20% din scor
  - `zile_pe_piață` (cu cât stă mai mult, cu atât vânzătorul e mai flexibil la negociere) - 15% din scor
  - `discount_procentual` față de media pieței - 15% din scor
  - `scor_vânzător` (privat vs dealer - privații sunt mai ușor de negociat) - 10% din scor
  - `scor_risc_vizual` (din fotografii, punctul 1) - 10% din scor
- Afișare în dashboard cu badge-uri colorate:
  - 🟢 80-100: „Cumpără ACUM"
  - 🟡 60-79: „Merită investigat"
  - 🔴 sub 60: „Risc ridicat"

**Estimare efort:** ~2 zile  
**ROI:** Economisești 2-3 ore/zi de analiză manuală, iar deciziile sunt bazate pe date, nu pe intuiție.

---

### 4. Tracker Lichiditate pe Model (Viteza de Vânzare / Days-to-Sell)

**De ce contează economic:** Un VW Golf se vinde în 14 zile, un Citroen C5 stă 90 de zile. Marja de 2.000 EUR pe un Golf bate marja de 3.000 EUR pe un C5 (capital blocat = bani pierduți).

**Ce trebuie implementat:**
- Calcul automat `days_to_sell` = media de zile între `first_seen` și momentul când `is_active` devine 0, per `(Brand, Model, An_interval)`
- Tabel nou în SQLite: `model_liquidity` cu coloanele:
  - `brand`, `model`, `year_range`, `avg_days_to_sell`, `median_days_to_sell`, `total_sold_30d`, `avg_sell_price`
- Dashboard: filtrare „Arată doar modele cu lichiditate sub 30 zile"
- Integrare în Deal Score (punctul 3)

**Estimare efort:** ~1-2 zile  
**ROI:** Previne blocarea capitalului în mașini greu vandabile. Optimizează rotația stocului.

---

## 🟡 PRIORITATE RIDICATĂ (Avantaj Competitiv)

### 5. Scraper pentru Mobile.de / AutoScout24 (Piața Germană)

**De ce contează economic:** 50-60% din mașinile second-hand din România vin din Germania. Dacă poți vedea prețurile de pe Mobile.de în timp real, poți identifica:
- Mașini care pot fi aduse din Germania cu marjă (import apoi vânzare RO)
- Mașini deja în România care sunt subevaluate vs prețul german (arbitraj cross-border)

**Ce trebuie implementat:**
- Scraper nou pentru Mobile.de (API sau HTML parsing)
- Coloană nouă în dashboard: „Preț Mediu Germania" și „Delta RO vs DE"
- Alertă automată: „Mașină listată în RO cu 20%+ sub prețul din Germania"

**Estimare efort:** ~3-4 zile  
**ROI:** Deschide un canal complet nou de profit (arbitraj internațional).

---

### 6. Verificare Automată Istoric (RAR / Carvertical / VIN)

**De ce contează economic:** O mașină cu daune majore în istoric sau km dați înapoi poate fi o pierdere de 3.000-10.000 EUR.

**Ce trebuie implementat:**
- Extragere VIN din paginile de detaliu ale anunțurilor (unele platforme îl afișează)
- Integrare API Carvertical sau echivalent gratuit (verificare km, daune, furturi)
- Stocarea rezultatului în DB ca flag: `vin_check_status` (clean / alert / unknown)
- Dashboard: indicator vizual instant în lista de chilipiruri

**Estimare efort:** ~2-3 zile  
**ROI:** Previne singura categorie de pierdere catastrofală (mașini cu probleme ascunse).

---

### 7. Predicție Trend de Preț pe Model (Creștere/Scădere)

**De ce contează economic:** Dacă știi că BMW Seria 3 din 2018 scade cu 2% pe lună, iar Dacia Duster din 2020 este stabilă, poți lua decizii mai bune de timing.

**Ce trebuie implementat:**
- Analiză time-series pe `price_history` groupby `(Brand, Model, year_range)`:
  - Trend liniar pe ultimele 30/60/90 zile
  - Indicator: „Preț în creștere", „Preț în scădere", „Stabil"
- Predicție simplă: „Estimare preț peste 30 zile" (regresie liniară pe istoric)
- Dashboard: coloană nouă „Trend Preț 30 zile"

**Estimare efort:** ~2 zile  
**ROI:** Timing-ul perfect de cumpărare/vânzare adaugă 3-5% la marja de profit.

---

### 8. Model ML Upgrade: Gradient Boosting (XGBoost / LightGBM)

**De ce contează economic:** RandomForest cu 150 arbori este decent (~85% R2), dar XGBoost/LightGBM atinge frecvent 90-93% pe date tabulare auto.

**Ce trebuie implementat:**
- Înlocuirea `RandomForestRegressor` cu `LightGBMRegressor` sau `XGBRegressor`
- Feature engineering adițional:
  - `car_age` = 2026 - year
  - `km_per_year` = mileage_km / car_age
  - `is_premium_brand` (BMW, Mercedes, Audi, Porsche = 1)
  - `body_type` (sedan, SUV, break - extras din titlu)
  - `transmission` (automat / manual - extras din titlu/descriere)
  - `euro_norm` (Euro 5/6 - extras din titlu/descriere)
- Hyperparameter tuning automat cu Optuna (10 min pe GitHub Actions)
- Comparare automată: dacă noul model are R2 mai mare, salvează-l; altfel, păstrează-l pe cel vechi

**Estimare efort:** ~2-3 zile  
**ROI:** Fiecare 1% R2 în plus = estimări mai precise = mai puține achiziții greșite.

---

### 9. Dashboard Mobil (PWA sau Telegram Bot Interactiv)

**De ce contează economic:** Când ești la un târg auto sau vizionezi o mașină, nu ai laptop. Ai nevoie de acces INSTANT de pe telefon.

**Ce trebuie implementat:**
- **Opțiunea A (recomandată):** Bot Telegram interactiv care:
  - Răspunde la `/check BMW Seria 3 2019 150000km diesel 2.0` cu estimarea ML instantanee
  - Trimite alertele de arbitraj ca mesaje formatate cu butoane inline
  - Permite `/top10` pentru cele mai bune chilipiruri de astăzi
  - Permite `/drops` pentru scăderile de preț recente
- **Opțiunea B:** Transformare Streamlit în PWA (Progressive Web App) cu manifest.json

**Estimare efort:** ~3-4 zile (Telegram Bot) / ~1 zi (PWA)  
**ROI:** Elimină latența decizională. Poți acționa în 30 secunde, nu în 30 minute.

---

### 10. Raport Zilnic Automat de Piață (Market Intelligence Report)

**De ce contează economic:** Un dealer profesionist trebuie să înțeleagă piața, nu doar să primească alerte punctuale.

**Ce trebuie implementat:**
- Raport generat automat zilnic (PDF / Markdown trimis pe Discord/Telegram/Email):
  - Top 10 modele cu cerere crescută (bazat pe volumul de anunțuri noi)
  - Top 10 modele cu prețuri în scădere
  - Top 5 oportunități de arbitraj ale zilei
  - Statistici: anunțuri noi azi, anunțuri expirate, preț mediu piață
  - Grafic trend preț mediu pe ultimele 30 zile
- Posibilitate de personalizare: „Vreau raport doar pentru BMW, Audi, Mercedes, cu buget 5.000-20.000 EUR"

**Estimare efort:** ~2-3 zile  
**ROI:** Profesionalizarea totală a workflow-ului. Poți vinde acest raport ca serviciu de subscription.

---

## 🟢 PRIORITATE MEDIE (Scalare si Monetizare)

### 11. Sistem de Watchlist / Alerte Personalizate per Utilizator

**Ce trebuie implementat:**
- Utilizatorul poate seta: „Alertează-mă când apare un BMW X3 2018-2021, diesel, sub 18.000 EUR, sub 150.000km"
- Sistem de matching automat la fiecare rulare de pipeline
- Notificare instantanee pe Telegram/Discord/Email

**ROI:** Funcționalitate esențială pentru orice client/dealer care ar plăti un abonament lunar.

---

### 12. Monetizare SaaS: Abonamente pentru Dealeri

**Ce trebuie implementat:**
- Landing page profesional
- 3 niveluri de abonament:
  - **Free:** Dashboard public cu date agregate (fără link-uri directe)
  - **Pro (49 EUR/lună):** Alerte în timp real + link-uri directe + watchlist (5 căutări)
  - **Business (149 EUR/lună):** API access + watchlist nelimitat + raport zilnic personalizat + estimator cost recondiționare
- Sistem de autentificare (Streamlit Authenticator sau un frontend dedicat)
- Stripe/PayPal integration pentru plăți recurente

**ROI:** 10 clienți Pro = 490 EUR/lună venit recurent. 5 clienți Business = 745 EUR/lună extra.

---

### 13. API REST pentru Integrare Externă

**Ce trebuie implementat:**
- FastAPI backend cu endpoint-uri:
  - `POST /api/v1/estimate` - Estimare preț ML
  - `GET /api/v1/deals` - Chilipiruri live
  - `GET /api/v1/price-drops` - Scăderi recente
  - `GET /api/v1/market-stats` - Statistici piață
- Rate limiting pe plan (Free: 10 req/zi, Pro: 1000 req/zi)
- API key management

**ROI:** Permite integrarea de către alte aplicații/dealeri. Potențial de venit recurent prin API.

---

### 14. Extragere și Analiză Seller Intelligence

**Ce trebuie implementat:**
- Tracking per vânzător (dealer sau privat):
  - Câte mașini are listate simultan
  - Istoria de pricing (scade des prețurile? ridică prețurile?)
  - Timpii medii de vânzare
  - „Seller Reputation Score" bazat pe pattern-uri
- Detectarea dealer-ilor deghizați în „privați" (semne: mai mult de 3 anunțuri simultane, fotografii profesionale, template de descriere)
- Dashboard: „Profil Vânzător" cu istoricul lui complet

**ROI:** Negocierea informată cu un vânzător cunoscut poate aduce 500-2.000 EUR extra per tranzacție.

---

### 15. Sistem de Comparare Cross-Platform (Same Car, Different Price)

**Ce trebuie implementat:**
- Algoritm de matching fuzzy care detectează aceeași mașină listată pe platforme diferite
  - Match pe: `(Brand, Model, Year, Mileage +/-500km, Engine_size, Location_city)`
  - Sau matching pe VIN dacă este disponibil
- Afișare: „Aceeași mașină pe Autovit la 12.000 EUR, pe OLX la 11.500 EUR, pe AutoUncle la 12.200 EUR"
- Alertă automată dacă prețul diferă cu peste 5% între platforme

**ROI:** Identifică prețul cel mai mic fără efort manual. Economisește 500-1.500 EUR per achiziție.

---

## 🔵 PRIORITATE NORMALĂ (Robustețe si Calitate)

### 16. Monitoring și Self-Healing pentru Scrapere

**Ce trebuie implementat:**
- Dashboard de sănătate per scraper:
  - Ultima rulare reușită + timestamp
  - Număr anunțuri extrase vs media ultimelor 7 zile
  - Alertă dacă un scraper returnează 0 rezultate de 2 ori consecutiv
- Rotire automată proxy-uri (listă de proxy-uri gratuite sau Bright Data/ScraperAPI)
- Rotire automată User-Agent din pool actualizat
- Retry exponențial cu jitter pe erori de rețea
- Alertă Discord dacă un scraper eșuează complet

**ROI:** Elimină timpul pierdut cu debugging manual. Asigură continuitatea datelor.

---

### 17. Optimizare Performanță DB (Migrare PostgreSQL sau DuckDB)

**Ce trebuie implementat:**
- SQLite crește (~71MB acum). La 200.000+ anunțuri cu istoric complet, se va încetini
- Migrare la PostgreSQL (pe un VPS ieftin) sau DuckDB (pentru analiză locală rapidă)
- Indexuri optimizate pentru query-urile frecvente din dashboard
- Backup automat zilnic al bazei de date

**ROI:** Previne degradarea performanței pe termen lung. Asigură scalabilitate.

---

### 18. Logging Structurat și Observabilitate

**Ce trebuie implementat:**
- Înlocuirea `print()` cu `logging` configurabil (DEBUG/INFO/WARNING/ERROR)
- Log files rotationale cu timestamp-uri
- Dashboard de monitorizare (Grafana/Prometheus opțional sau simplu JSON stats)
- Metrici de business logate automat: ROI pe alerte trimise (câte s-au transformat în achiziții)

**ROI:** Profesionalizare + debugging rapid + dovadă de performanță pentru clienți.

---

### 19. Test Suite Automatizat

**Ce trebuie implementat:**
- Unit tests pentru:
  - `parse_car_title()` - acoperire 100% pe branduri și modele canonice
  - `infer_fuel_type()` / `infer_engine_size()` - teste pe cazuri edge
  - `normalize_price_eur()` - teste pentru RON/EUR/edge cases
  - `save_scraped_data()` - teste de integrare cu DB temporar
- Integration tests pentru fiecare scraper (mock HTML, verificare output)
- GitHub Actions: rulare teste înainte de deploy

**ROI:** Previne regresiile. Fiecare bug în producție = date incorecte = decizii greșite = bani pierduți.

---

### 20. Curățare Cod și Reducerea Duplicării

**Ce trebuie implementat:**
- Toate cele 6 scrapere (Autovit, OLX, BestAuto, CautiMasina, PlusAuto, CarZZ) au structură aproape identică. Trebuie extrasă o clasă abstractă `BaseScraper` cu:
  - Metodele comune: `random_sleep`, `normalize_number`, `early_stopping_logic`, `save_results`
  - Fiecare scraper moștenește și implementează doar `parse_card()` și `get_url(page_num)`
- Reduce ~4.000 linii de cod la ~1.500 linii, mai ușor de întreținut

**ROI:** Orice modificare viitoare (ex: adăugare proxy, schimbare early_stopping) se face O SINGURĂ DATĂ, nu în 6 fișiere.

---

## 💡 IDEI BONUS DE MONETIZARE

### 21. Serviciu de Evaluare Instant pentru Vânzători
- Landing page: „Cât valorează mașina ta?" cu formularul ML
- Captare email si newsletter cu oferte de cumpărare
- Potențial: achiziție directă de la vânzători „disperați" la preț sub piață

### 22. Parteneriat cu Service-uri Auto
- Recomandare service partener la fiecare achiziție
- Comision de referral (50-100 EUR per mașină trimisă la inspecție)

### 23. Widget Embed pentru Site-uri de Dealeri
- iFrame cu estimarea ML care poate fi integrat pe site-ul oricărui dealer
- Plată lunară per embed: 29 EUR/lună

### 24. Export Date Piață pentru Asigurări/Leasing
- Rapoarte de piață structurate pentru companiile de asigurări (valoare mașină la momentul accidentului)
- Rapoarte pentru firme de leasing (valoare reziduală estimată ML)

---

## 📅 PLAN DE EXECUȚIE RECOMANDAT

### Faza 1 — Săptămâna 1-2 (Fundament Economic)
1. Estimator costuri recondiționare (nr. 2)
2. Tracker lichiditate / Days-to-Sell (nr. 4)
3. Deal Score compozit (nr. 3)

### Faza 2 — Săptămâna 3-4 (Avantaj Competitiv)
4. Upgrade ML la XGBoost/LightGBM (nr. 8)
5. Predicție trend preț (nr. 7)
6. Bot Telegram interactiv (nr. 9)

### Faza 3 — Săptămâna 5-6 (Calitate si Scale)
7. Cross-platform matching (nr. 15)
8. Raport zilnic automat (nr. 10)
9. Refactorizare scrapere cu clasă abstractă (nr. 20)

### Faza 4 — Luna 2+ (Monetizare si Extindere)
10. Scraper Mobile.de (nr. 5)
11. Verificare VIN/Istoric (nr. 6)
12. Sistem watchlist + abonamente SaaS (nr. 11, 12)
13. API REST (nr. 13)

---

**Recomandare:** Începe cu **punctele 2, 4 și 3** (estimator costuri + lichiditate + Deal Score). Sunt cele mai rapide de implementat și cele care transformă imediat lista de „chilipiruri" dintr-o listă brută într-un instrument de decizie financiară reală.

---

*Document generat automat prin analiza completă a proiectului ScraperAnalistAutomobile.*
