# Documente Sintetice Fictive pentru Testare Aplicație (Format PDF)

Acest director conține dosarele complete de documente fictive în **format PDF** (A4) generate automat pentru clienții existenți.
Toate documentele (buletin, adeverință de venit, extras de cont) sunt fișiere `.pdf` gata de încărcat direct în formularul de credit din aplicație (**Document Checklist**).

## Clienți Disponibili & Documente PDF

| Client | Scenariu / Tag | CNP Sintetic | Venit Net Lunar | Documente PDF |
| :--- | :--- | :--- | :--- | :--- |
| **Alex Morgan** | `DEMO_CUSTOMER` | `1920515410012` | 8,500.00 RON | 📄 [Copie Buletin (PDF)](alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf)<br>📄 [Adeverință Venit (PDF)](alex_morgan_demo_customer/adeverinta_venit_alex_morgan_demo_customer.pdf)<br>📄 [Extras Cont (PDF)](alex_morgan_demo_customer/extras_cont_alex_morgan_demo_customer.pdf) |
| **Dan Ionescu** | `DSTI_39` | `1790420000031` | 5,996.25 RON | 📄 [Copie Buletin (PDF)](dan_ionescu_dsti_39/buletin_dan_ionescu_dsti_39.pdf)<br>📄 [Adeverință Venit (PDF)](dan_ionescu_dsti_39/adeverinta_venit_dan_ionescu_dsti_39.pdf)<br>📄 [Extras Cont (PDF)](dan_ionescu_dsti_39/extras_cont_dan_ionescu_dsti_39.pdf) |
| **Elena Popa** | `INCOME_NO_DEBT` | `2820327000020` | 4,500.00 RON | 📄 [Copie Buletin (PDF)](elena_popa_income_no_debt/buletin_elena_popa_income_no_debt.pdf)<br>📄 [Adeverință Venit (PDF)](elena_popa_income_no_debt/adeverinta_venit_elena_popa_income_no_debt.pdf)<br>📄 [Extras Cont (PDF)](elena_popa_income_no_debt/extras_cont_elena_popa_income_no_debt.pdf) |
| **Radu Mihai** | `MULTI_SOURCE_MULTI_LOAN` | `1890325000097` | 5,000.00 RON | 📄 [Copie Buletin (PDF)](radu_mihai_multi_source_multi_loan/buletin_radu_mihai_multi_source_multi_loan.pdf)<br>📄 [Adeverință Venit (PDF)](radu_mihai_multi_source_multi_loan/adeverinta_venit_radu_mihai_multi_source_multi_loan.pdf)<br>📄 [Extras Cont (PDF)](radu_mihai_multi_source_multi_loan/extras_cont_radu_mihai_multi_source_multi_loan.pdf) |
| **Andrei Stan** | `NO_HISTORY` | `1831107000012` | 3,500.00 RON | 📄 [Copie Buletin (PDF)](andrei_stan_no_history/buletin_andrei_stan_no_history.pdf)<br>📄 [Adeverință Venit (PDF)](andrei_stan_no_history/adeverinta_venit_andrei_stan_no_history.pdf)<br>📄 [Extras Cont (PDF)](andrei_stan_no_history/extras_cont_andrei_stan_no_history.pdf) |

## Cum se folosesc în aplicație:
1. Deschide aplicația client la `http://localhost:3000` (autentificare cu `alex@example.test` / `ClientDemo123!`).
2. Mergi la secțiunea de solicitare credit sau aplicație existentă.
3. În fereastra **Document Checklist**, apasă pe **Add Identity document**, **Add Proof of income** sau **Add Account statement**.
4. Alege fișierul `.pdf` corespunzător din acest folder (ex: `alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf`).
5. Salvează metadatele documentului.

> [!NOTE]
> Toate documentele sunt generate pe bază de date sintetice pentru testare și conțin marcaje explicite `SPECIMEN TEST DEMO`.