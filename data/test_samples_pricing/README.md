# Scenarii de Testare pentru Simulatorul de Preț și Credite (Loan Pricing & Simulation)

Acest director conține fișiere JSON standardizate și scenarii demonstrative pentru testarea completă a motorului financiar determinist de calcul al creditelor (`src/services/pricing/` și `src/services/financial_calculations/`).

---

## Scenarii Disponibile

### 1. `01_personal_loan_standard_offer.json`
* **Produs**: Credit de Nevoi Personale cu Dobândă Fixă (`personal_loan_fixed`).
* **Parametri**: 50.000 RON, 60 luni, cont salariu standard (-1.00 pp), asigurare de viață/șomaj (-2.00 pp).
* **Rezultate calculate**:
  - Rată dobândă: **5,55%** (bază 8,55% minus discounturi).
  - Rată lunară: **961,21 RON**.
  - DAE (OUG 50/2010): **9,49%**.
  - Cost total credit: **11.472,72 RON**.
  - Grad de îndatorare: **11,31%** (eligibil conform BNR 17/2012 <= 40%).

### 2. `02_mortgage_casa_ta_simulation.json`
* **Produs**: Credit Imobiliar Casa Ta (`mortgage_fixed_then_ircc`).
* **Parametri**: 350.900 RON, 300 luni (25 ani), primii 3 ani dobândă fixă 5,05%, apoi variabilă IRCC (5,57% trim. T4 2026) + marjă fixă 2,30% = 7,87%.
* **Rezultate calculate**:
  - Rată lunară în perioada fixă: **2.155,79 RON**.
  - Rată lunară după perioada fixă: **2.713,05 RON**.
  - LTV (Loan-to-Value): **83,55%** (încadrat în limita de 85% pentru prima casă).
  - Grad de îndatorare: **21,56%** (încadrat în limita de 45% pentru prima casă).

### 3. `03_early_repayment_prepayment.json`
* **Simulare**: Rambursare anticipată parțială de 15.000 RON după 12 luni pe creditul de consum de 50.000 RON.
* **Comparație opțiuni**:
  - **Opțiunea 1 (Reducerea perioadei - `reduce_term`)**: Păstrează rata la 961,21 RON, dar scurtează durata creditului cu **18 luni** (se termină în luna 42 în loc de 60), economisind **2.851,49 RON** net în dobânzi și comisioane după plata comisionului de 1% (150 RON).
  - **Opțiunea 2 (Reducerea ratei - `reduce_instalment`)**: Păstrează scadența la 60 de luni, dar reduce rata lunară de la 961,21 RON la **612,02 RON** (o eliberare de buget de **349,19 RON/lună**), cu o economie netă de **1.611,03 RON**.

### 4. `04_refinancing_consolidation.json`
* **Simulare**: Consolidarea a două credite scumpe (Card de Credit 10.000 RON la 24% dobândă + Credit de Nevoi 25.000 RON la 14,5%) într-un singur credit fix pe 5 ani, plus 5.000 RON lichidități suplimentare.
* **Rezultate calculate**:
  - Rata lunară combinată veche: **1.389,23 RON**.
  - Noua rată lunară consolidată: **838,59 RON**.
  - Reducere imediată a efortului lunar: **550,64 RON / lună**.

### 5. `05_rejected_boundary_limits.json`
* **Simulări invalide**: Testează validările stricte de integritate:
  - `AMOUNT_OUT_OF_RANGE`: Sumă sub limita minimă (1.000 RON < 2.500 RON) sau peste maxim (300.000 RON > 250.000 RON).
  - `TERM_OUT_OF_RANGE`: Perioadă peste limita de 60 de luni pentru credit de consum.
  - `AMOUNT_ABOVE_BALANCE`: Rambursare anticipată care depășește soldul rămas.
  - `MONTH_OUT_OF_RANGE`: Rambursare anticipată dincolo de durata creditului.

---

## Rulare Teste și Demo

### Testare rapidă în consolă:
```powershell
.\.venv\Scripts\python.exe -m scripts.test_pricing_simulator
```

### Rulare teste unitare (pytest / unittest):
```powershell
.\.venv\Scripts\pytest.exe tests/unit/services/pricing/
```
sau
```powershell
.\.venv\Scripts\python.exe -m unittest tests/unit/services/pricing/test_pricing_scenarios.py -v
```
