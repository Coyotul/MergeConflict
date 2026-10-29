# ADR 008: Deterministic loan pricing and simulation engine

- **Status:** Proposed (2026-10-28)
- **Components:** `src/services/financial_calculations/`, `src/rules/pricing/`,
  `src/services/pricing/`, `config/products/`, `config/rules/`

## Context

The specification (§4.3, §4.4, §11) requires loan offers, repayment schedules, total cost,
fees and insurance, early repayment and refinancing comparisons, computed deterministically
with decimal-safe arithmetic and explicit assumptions. An LLM must never produce these numbers.
The challenge is from Raiffeisen Bank Romania; the product must stay bank-agnostic and must not
impersonate the bank.

## Decision

- Pure Python with `decimal.Decimal`; no new dependencies.
- **Synthetic products** whose parameters mirror Raiffeisen Romania's public documents, stored
  as versioned JSON with their sources. Every result records the product version.
- Three layers: product rules (rate, fees, early repayment fee), a product-agnostic financial
  engine (schedules, DAE), and use cases returning typed results with assumptions.
- **Validation against the bank's published representative examples** as known-result tests.

## Research findings used (fetched 2026-10-28)

**Raiffeisen personal loan** ("Credit de nevoi personale fără ipotecă", cost sheet effective
15.10.2026):

- Fixed rate, 18–60 months.
- Base range 8.55–17.95%, minus 1 pp for a salary account (1.2 pp Premium) and minus 2 pp with
  optional insurance. This model reproduces the published grid: 5.55–14.95% for salary clients,
  5.35–14.75% for Premium, 17.95% maximum.
- 200 lei analysis fee financed in the loan; 5 lei/month administration fee.
- Single-premium insurance = amount × 0.12% × months, financed and included in the DAE.
- Early repayment fee 1%, or 0.5% in the last year.

**Raiffeisen "Casa Ta" mortgage:** 3 or 5 years fixed (5.05% / 5.65%), then IRCC + 2.30%.
Charges are 3 lei/month plus life insurance of 0.026% of the loan per month.

**Romanian rules:**

- **DAE:** OUG 50/2010 Annex 1, equal months of 1/12 year.
- **Early repayment compensation:** at most 1% (or 0.5% with one year or less left), only during
  a fixed-rate period, capped at the interest the customer would have paid (art. 66–69).
- **Variable rate:** IRCC + a margin fixed for the contract (art. 37). The IRCC value computed
  for quarter T applies in quarter T+2; 5.57% applies in Q4 2026.
- **Debt-service limit (BNR Regulation 17/2012 art. 19):** 40% of net income for RON loans
  (45% for a first home), 20% for FX loans.

**Verification by recomputation:**

| Published example | Published | Engine |
|---|---|---|
| 50,000 / 60 m / 5.55%, with insurance | 961.21, DAE 9.49%, total 57,672.75 | 961.21, 9.49%, 57,672.72 |
| Premium 5.35% | 956.60, DAE 9.26%, total 57,396.01 | identical |
| 17.95%, no insurance | 1,273.31, DAE 19.94%, total 76,398.71 | identical |
| Casa Ta 350,900 / 300 m, 3 y fixed | 2,155.80 then 2,713.05 | 2,155.79 then 2,713.05 |

The DAE at 17.95% matches only when insurance is *not* financed, which confirms that the bank's
maximum-rate example has no insurance.

## Consequences

- **Rounding:** schedules round every instalment and component to 0.01 (half up), and the last
  instalment absorbs the difference. Totals can differ from the bank's representative figures by
  a few bani; tests allow 5 bani on totals and require exact instalments and DAE.
- **Assumed parameters:**
  - The refinancing product's fee and discount structure is assumed equal to the personal loan.
  - Mortgage amount limits are assumed in RON.
  - Mortgage valuation and property insurance are not modelled, so its DAE is flagged as
    incomplete.
- **Not verified:**
  - Romania's transposition of Directive (EU) 2023/2225.
  - IRCC values before 2025.
  - How the bank's 120-month refinancing term fits the 5-year consumer-credit limit in BNR
    Regulation 17/2012.
  - Raiffeisen's technology stack.
- **Configuration updates:** IRCC values must be added to `config/rules/ircc.json` each quarter;
  a missing quarter returns `INDEX_UNAVAILABLE` instead of guessing.
- **Inputs from other components:**
  - The risk-based base rate should come from credit scoring.
  - Settlement amounts for real full repayments must come from the bank's API.

## Sources

- https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credit-de-nevoi-personale-fara-ipoteca.html
- https://www.raiffeisen.ro/content/dam/rbi/retail/eu/ro/documents/costuri/costuri-complete-flexicredit-standard/20261015-costuri-flexicredit-standard-complete.pdf.coredownload.inline.pdf
- https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credit-imobiliar-casa-ta.html
- https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credit-de-refinantare-fara-ipoteca.html
- https://legislatie.just.ro/Public/DetaliiDocument/119472 (OUG 50/2010)
- https://legislatie.just.ro/Public/DetaliiDocument/143876 (BNR Regulation 17/2012)
- https://www.bursa.ro/ircc-urca-la-5-57-procente-in-t4-2026-85224069
- https://financiarul.ro/finante-personale/ce-ircc-se-foloseste-la-calculul-creditelor-si-cand-se-aplica-valoarea/
