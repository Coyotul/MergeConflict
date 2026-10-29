# Seturi de Documente Sintetice pentru Testarea Eligibilității (Eligibility Check)

Acest director conține fișiere document (.pdf și .png) compatibile cu pipeline-ul de **Document Processing & OCR** și motorul de **Eligibility Check** al aplicației bancare.

---

## Structura Seturilor de Testare

### 1. `01_RESPINS_Venit_Zero` (Candidat fără venituri / Respins)
* **Profil**: Victor Nistor (CNP: `1830107000044`, Vârstă: 43 ani, București)
* **Scenariu**: Candidatul nu realizează venituri (contract suspendat / fără venituri înregistrate la ANAF).
* **Documente disponibile**:
  - `adeverinta_anaf_zero_venit.pdf`: Adeverință fiscală eliberată de ANAF cu venit net 0,00 RON.
  - `adeverinta_venit_zero_venituri.pdf`: Adeverință de venit de la angajator cu salariu net 0,00 RON (concediu fără plată / contract suspendat).
  - `buletin_victor_nistor.pdf`: Carte de identitate românească (seria DP nr. 830107).
  - `extras_cont_zero_incasari.pdf`: Extras de cont Raiffeisen cu sold minim și fără viramente de salariu.
* **Rezultat așteptat la Eligibility Check**:
  - **Status**: `REJECTED` (la nivel de document) / `NOT_SATISFIED` (la nivel de credit engine).
  - **Regulă eșuată**: `INC_MIN_INCOME` / `BELOW_CONFIGURED_MINIMUM_INCOME` ("Declared net income: 0.00 RON").
  - **Motiv**: Fără venituri dovedite, clientul nu are capacitate de rambursare și nu este eligibil pentru credit.

---

### 2. `02_ELIGIBIL_Venit_Optim` (Candidat cu venituri optime / Eligibil)
* **Profil**: Alex Morgan (CNP: `1920515410012`, Vârstă: 34 ani, București)
* **Scenariu**: Angajat cu contract pe perioadă nedeterminată, vechime > 3 ani, venit net 8.500 RON/lună.
* **Documente disponibile**:
  - `adeverinta_anaf_venit_ok.pdf`: Adeverință ANAF cu venit anual 102.000 RON (8.500 RON/lună).
  - `adeverinta_venit_ok_8500_ron.pdf`: Adeverință de salariu de la angajator (Northstar Studio S.R.L.).
  - `buletin_alex_morgan.pdf`: Carte de identitate românească (seria RX nr. 781920).
  - `extras_cont_alex_morgan.pdf`: Extras de cont Raiffeisen cu încasare recurentă a salariului de 8.500 RON pe data de 5 a lunii.
* **Rezultat așteptat la Eligibility Check**:
  - **Status**: `VALIDATED` (la nivel de document) / `PRELIMINARY_REQUIREMENTS_SATISFIED` (la nivel de credit engine).
  - **Grad de îndatorare (DTI)**: Calculat în limitele prudente BNR (< 40%).

---

### 3. `03_RESPINS_Venit_Sub_Minim` (Candidat sub salariul minim pe economie / Respins)
* **Profil**: Maria Popescu (CNP: `2850912000084`, Vârstă: 41 ani, București)
* **Scenariu**: Candidatul lucrează, dar venitul net este de 1.500 RON/lună, sub salariul minim legal (2.363 RON net).
* **Documente disponibile**:
  - `adeverinta_venit_sub_minim_1500_ron.pdf`: Adeverință de salariu cu 1.500,00 RON net.
  - `buletin_maria_popescu.pdf`: Carte de identitate seria RR nr. 850912.
* **Rezultat așteptat la Eligibility Check**:
  - **Status**: `REJECTED`.
  - **Regulă eșuată**: `INC_MIN_INCOME` ("Declared net income: 1,500.00 RON < 2,363.00 RON").

---

## Cum se testează

### 1. Test automat în consolă:
```powershell
.\.venv\Scripts\python.exe -m scripts.test_eligibility_files
```

### 2. Rulare teste unitare:
```powershell
.\.venv\Scripts\python.exe -m unittest tests/unit/test_eligibility_document_samples.py -v
```

### 3. În interfața web (Frontend):
1. Deschide aplicația client (`http://localhost:3000`).
2. În secțiunea **Document Checklist**, încărcați documentele din folderul corespunzător (`01_RESPINS_Venit_Zero` sau `02_ELIGIBIL_Venit_Optim`).
3. Sistemul va extrage automat datele prin OCR și va valida eligibilitatea conform regulilor reglementare.
