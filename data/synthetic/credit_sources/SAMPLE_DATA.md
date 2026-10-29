# Fictional credit-source scenarios

Seed: `20261028`. Default reference date: `2026-10-28`.

82 guaranteed labelled cases plus 250 seeded-random people.
No real records are used. CNPs deliberately fail the checksum; names/addresses/employers are fictional and phones are NULL.

## Find a scenario

```sql
SELECT p.persona_tag, p.cnp, d.* FROM persons p JOIN v_dsti_inputs d USING(cnp)
WHERE p.persona_tag = 'DSTI_39';
SELECT p.persona_tag, b.* FROM persons p JOIN v_bureau_summary b USING(cnp)
WHERE p.persona_tag NOT LIKE 'RANDOM_%';
```

For year rollover use D = 2027-01-05; for leap-month CRC use D = 2024-03-01.
Restore D = 2026-10-28 after exploring. Future fixture rows are intentional, not real predictions.

Missing-history scenarios are intentional completeness gaps, not zero-debt evidence.
The dataset covers valid states only: bad CNP syntax, invalid scores, duplicate keys, orphan rows,
invalid dates, deletes/cascades and rollback behavior remain in automated tests rather than corrupting fixtures.
No universal monotonic-balance or exact accounting-ledger claim is made. Monthly and annual salaries reconcile;
selected fixed-rate RON amortizer scenarios have nonincreasing balances except event-explained increases.

## Guaranteed cases

| persona_tag | CNP (synthetic) | Scenario |
| --- | --- | --- |
| NO_HISTORY | 1831107000012 | No income, loans, inquiries, scores or insolvency; zero debt and NULL DSTI. |
| INCOME_NO_DEBT | 2820327000020 | Positive salary, no credit products: DSTI 0.0%. |
| DSTI_39 | 1790420000031 | 2025 net income 71,955 RON; instalment 2,340 RON; DSTI exactly 39.0%. |
| ZERO_INCOME | 1830107000044 | Active debt and declared zero 2025 income: NULL DSTI. |
| MISSING_INCOME | 2761122000052 | Active debt without ANAF income: NULL DSTI. |
| OLD_INCOME_ONLY | 1790220000069 | Income only in 2022, outside the default window: NULL DSTI. |
| OLDER_ELIGIBLE_YEAR | 1860207000077 | Income only in 2024: use that year, not a missing 2025. |
| DSTI_OVER_100 | 1850912000084 | 2025 income 12,000 RON and 1,500 RON instalment: 150.0% DSTI. |
| MULTI_SOURCE_MULTI_LOAN | 1890325000097 | Two employers and rental income; two debts total 300 RON/month; net income 60,000 gives DSTI 6.0%. |
| FRACTIONAL_ROUNDING | 1900416000103 | Fractional annual income and instalments exercise REAL/one-decimal DSTI rounding. |
| SHARED_DEBTOR | 1740721000114 | Debtor on shared mortgage; receives the entire 1,000 RON obligation. |
| SHARED_CODEBTOR | 2870626000125 | Co-debtor receives the full shared mortgage obligation, not a split. |
| GUARANTOR_ONLY | 1750211000135 | Mortgage visible in bureau and CRC; zero debt instalments and one guarantee. |
| MIXED_ROLES | 2880203000146 | Own 200 RON debt plus a guarantee on the 1,000 RON mortgage: count only own debt. |
| CRC_BELOW | 2850302000152 | CRC threshold on granted RON equivalent 19999.99; original currency RON, low outstanding balance. |
| CRC_EXACT | 2700912000169 | CRC threshold on granted RON equivalent 20000; original currency RON, low outstanding balance. |
| CRC_ABOVE | 2650209000170 | CRC threshold on granted RON equivalent 20000.01; original currency RON, low outstanding balance. |
| CRC_EUR | 2900628000189 | CRC threshold on granted RON equivalent 25000; original currency EUR, low outstanding balance. |
| SMALL_CARD | 2840412000194 | CRC threshold on granted RON equivalent 8000; original currency RON, low outstanding balance. |
| USD_PRODUCT | 1760313000204 | CRC threshold on granted RON equivalent 30000; original currency USD, low outstanding balance. |
| CHF_PRODUCT | 1741002000218 | CRC threshold on granted RON equivalent 40000; original currency CHF, low outstanding balance. |
| BUREAU_4Y_EXACT | 1820207000226 | Closure 2022-10-28; checks inclusive retention and closure visibility relative to D. |
| BUREAU_4Y_OLDER | 1761127000239 | Closure 2022-10-27; checks inclusive retention and closure visibility relative to D. |
| CRC_7Y_EXACT | 2730819000249 | Closure 2019-10-28; checks inclusive retention and closure visibility relative to D. |
| CRC_7Y_OLDER | 1820708000251 | Closure 2019-10-27; checks inclusive retention and closure visibility relative to D. |
| CLOSED_2018 | 1720604000269 | Closure 2018-01-01; checks inclusive retention and closure visibility relative to D. |
| RECENT_CLOSED | 2680505000272 | Closure 2026-09-30; checks inclusive retention and closure visibility relative to D. |
| FUTURE_CLOSURE | 1730823000289 | Closure 2026-12-01; checks inclusive retention and closure visibility relative to D. |
| OPENED_ON_D | 1901217000290 | Opened 2026-10-28; never visible before opening; CRC excludes openings after its snapshot. |
| OPENED_AFTER_D | 1680522000302 | Opened 2026-10-29; never visible before opening; CRC excludes openings after its snapshot. |
| FUTURE_PRODUCT | 2791010000317 | Opened 2027-01-05; never visible before opening; CRC excludes openings after its snapshot. |
| DELAY_000 | 1670318000322 | Current days past due 0; positive overdue money whenever delinquent. |
| DELAY_001 | 2790401000334 | Current days past due 1; positive overdue money whenever delinquent. |
| DELAY_030 | 1760823000347 | Current days past due 30; positive overdue money whenever delinquent. |
| DELAY_031 | 1880806000355 | Current days past due 31; positive overdue money whenever delinquent. |
| DELAY_060 | 2660817000364 | Current days past due 60; positive overdue money whenever delinquent. |
| DELAY_061 | 1810111000372 | Current days past due 61; positive overdue money whenever delinquent. |
| DELAY_090 | 2800114000382 | Current days past due 90; positive overdue money whenever delinquent. |
| DELAY_091 | 2730803000394 | Current days past due 91; positive overdue money whenever delinquent. |
| DELAY_180 | 1741203000402 | Current days past due 180; positive overdue money whenever delinquent. |
| DELAY_181 | 1690228000419 | Current days past due 181; positive overdue money whenever delinquent. |
| WORST_24M | 2770513000422 | DPD 181 in Oct 2024 excluded, 90 in Nov 2024 included; current DPD 0; future DPD ignored. |
| INQUIRY_BOUNDARIES | 1660617000437 | HARD at Apr 28 and Oct 28 included; Apr 27, old/future HARD, and all SOFT hidden. Count 2. |
| SCORE_TIME_TRAVEL | 1850511000440 | Scores 300/700/850 on Jul 1/Oct 28/Oct 29; sorted ranks 1-5; future score ignored. |
| EXPLICIT_NO_SCORE | 2881004000450 | Latest score is explicitly NO_SCORE rather than missing. |
| SCORE_NO_REASONS | 2900718000460 | Valid minimum score 300 with no explanations. |
| NO_PAYMENT_HISTORY | 1821006000472 | Active exposure with no monthly history: product NULLs, summary zero (unknown, not proof of no debt). |
| FUTURE_ONLY_HISTORY | 2791025000480 | Only Nov 2026 history: bureau/CRC payment figures NULL at default D. |
| PARTIAL_HISTORY | 2710710000498 | Two active debts, only one has history: total 500 RON is incomplete. |
| CRC_MISSING_MONTH | 1810602000501 | August history but no September: bureau falls back, CRC does not. |
| CALENDAR_TIME_TRAVEL | 2730519000512 | Full 2024-Jan 2027 history; leap-Feb snapshot, latest-history selection and January rollover. |
| INSOLVENCY_OPEN | 1791222000524 | Insolvency opened 2025-01-01, closed None; retained cases determine has_insolvency. |
| INSOLVENCY_4Y_EXACT | 2691106000534 | Insolvency opened 2020-01-01, closed 2022-10-28; retained cases determine has_insolvency. |
| INSOLVENCY_4Y_OLDER | 2771201000542 | Insolvency opened 2020-01-01, closed 2022-10-27; retained cases determine has_insolvency. |
| INSOLVENCY_FUTURE | 2880422000555 | Insolvency opened 2026-10-29, closed None; retained cases determine has_insolvency. |
| FRAUD_7Y_BOUNDARIES | 2681219000568 | Fraud at Oct 28 2019 and Oct 28 2026 included; older/future records hidden; nullable lender. |
| ACTIVITY_ACTIVE | 1800410000573 | PFA activity started 2022-01-15, ended None; ANAF three-year retention. |
| ACTIVITY_3Y_EXACT | 2901022000587 | II activity started 2020-01-01, ended 2023-10-28; ANAF three-year retention. |
| ACTIVITY_3Y_OLDER | 1891215000592 | IF activity started 2020-01-01, ended 2023-10-27; ANAF three-year retention. |
| ACTIVITY_FUTURE | 2650510000606 | LIBERAL_PROFESSION activity started 2026-10-29, ended None; ANAF three-year retention. |
| ALL_INCOME_TYPES | 2901028000612 | All seven ANAF income types, including two distinct salary employers. |
| PARTIAL_EMPLOYMENT | 1741219000623 | Jan 15-Mar 15 fixed-term job plus later part-time job; salary months overlap employment. |
| STATUS_ASSIGNED | 2780211000633 | ASSIGNED product not closed; remains an obligation under the documented policy. |
| STATUS_WRITTEN_OFF | 1790904000646 | WRITTEN_OFF product not closed; remains an obligation under the documented policy. |
| EVENT_4Y_BOUNDARIES | 2700202000651 | Events exactly four years ago and on D retained; day older and future excluded. |
| EVENT_RESTRUCTURING | 2740325000665 | Fictional restructuring event; explained balance increase for refinancing/restructuring only. |
| EVENT_REFINANCING | 1811225000672 | Fictional refinancing event; explained balance increase for refinancing/restructuring only. |
| EVENT_DATION_IN_PAYMENT | 1730610000683 | Fictional dation_in_payment event; explained balance increase for refinancing/restructuring only. |
| EVENT_CONTRACT_ASSIGNMENT | 2851206000693 | Fictional contract_assignment event; explained balance increase for refinancing/restructuring only. |
| EVENT_DEBT_ASSIGNMENT | 2760127000707 | Fictional debt_assignment event; explained balance increase for refinancing/restructuring only. |
| EVENT_PAYMENT_SUSPENSION | 1740327000714 | Fictional payment_suspension event; explained balance increase for refinancing/restructuring only. |
| REVOLVING_DRAWDOWN | 2760627000721 | Revolving balance rises from new drawdowns without restructuring; this is allowed. |
| YOUNG_ADULT | 6040229000737 | Post-2000 CNP century prefix and leap-day birth; credit opens after adulthood. |
| DEMO_ALEX_MORGAN | 1880412003246 | Demo customer Alex Morgan: salary 8,500 RON/month, no credit history. |
| DEMO_ELENA_POPA | 2910903003252 | Demo customer Elena Popa: salary 4,500 RON/month, no credit history. |
| DEMO_RADU_MIHAI | 1850220003262 | Demo customer Radu Mihai: two employers (3,000 + 2,000 RON/month), two consumer loans with 150 RON instalments. |
| DEMO_DAN_IONESCU | 1831107003278 | Demo customer Dan Ionescu: salary 5,996.25 RON/month, consumer loan 80,000 RON with 2,340 RON instalment (DSTI 39%). |
| DEMO_ANDREI_STAN | 1960625003280 | Demo customer Andrei Stan: salary 2,300 RON/month (below minimum income). |
| DEMO_LATE_91 | 2870314003292 | Demo customer Ioana Marin: salary 6,000 RON/month, consumer loan 91 days past due in 2026-10. |
| DEMO_INSOLVENCY | 1790830003301 | Demo customer Victor Dobre: salary 5,500 RON/month, open debt repayment plan insolvency since 2025-01-01. |
| DEMO_RESTRUCTURED | 2901201003316 | Demo customer Maria Stoica: salary 6,500 RON/month, consumer loan restructured on 2026-08-28. |
| DEMO_SELF_EMPLOYED | 1860518003320 | Demo customer Mihai Ilie: self-employed (active PFA since 2022-01-15), 84,000 RON independent-activity income in 2025. |

## Table counts

| Table | Rows |
| --- | ---: |
| report_params | 1 |
| persons | 332 |
| employers | 6 |
| lenders | 5 |
| employments | 180 |
| income_activity_forms | 6 |
| income_records | 616 |
| monthly_salary_declarations | 6082 |
| credit_products | 427 |
| product_participants | 496 |
| payment_history | 10660 |
| credit_events | 13 |
| bureau_inquiries | 378 |
| fico_scores | 263 |
| fico_reason_codes | 905 |
| insolvency_records | 5 |
| card_fraud_records | 4 |
