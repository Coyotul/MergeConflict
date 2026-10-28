# Eligibility research: Raiffeisen Bank Romania reference

Researched on **2026-10-28**. This is an independent, bank-agnostic prototype,
not a Raiffeisen application, internal credit policy or legal compliance opinion.
Only synthetic applicant records and verification providers are implemented.

## Scope and source hierarchy

First release: a new unsecured personal loan in RON. Regulatory text takes
precedence over public product prose; product pages take precedence over generic
educational articles. Every configured rule identifies its supporting sources.
Public minimum criteria are not a complete underwriting policy and confer no
right to a loan. Preliminary screening never records approval or rejection.

| ID | Classification | Source and applicable passage |
| --- | --- | --- |
| RF_PRODUCT | Public bank reference | [Flexicredit product page](https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credit-de-nevoi-personale-fara-ipoteca.html): eligibility, employment contract conditions, simulator and general information. |
| RF_CONDITIONS | Public bank reference | [Personal-loan conditions](https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/conditii-credit-nevoi-personale.html): income, employment, age at maturity, supporting documents and non-salary income. |
| RF_BUREAU | Public bank reference | [Biroul de Credit explanation](https://www.raiffeisen.ro/ro/persoane-fizice/produsele-noastre/credite/credite-de-nevoi-personale/biroul-de-credit.html): bureau membership is not automatic disqualification; history requires contextual analysis. |
| RF_NOTICE | Public bank reference | [Credit information notice](https://www.raiffeisen.ro/ro/aplica/nota-de-informare-credit.html), sections 4.3/4.4, 5.4, 8.2, 10 and IMPORTANT: lawful bases, score, retention, rights and inquiry purposes. |
| BNR_17 | Regulatory | [BNR Regulation 17/2012, consolidated text](https://legislatie.just.ro/Public/DetaliiDocument/143876), articles 12, 13, 17, 19 and 20. The portal displayed consolidated history through 2022-10-25 when retrieved. |
| HG_146 | Regulatory | [HG 146/2026](https://legislatie.just.ro/Public/DetaliiDocument/308231), article 1: **gross** minimum salary of 4,325 RON effective 2026-07-01. Not a net salary threshold. |
| DEMO_POLICY | Synthetic assumption | Local versioned demo configuration; no bank endorsement or statutory status. |

## Rule catalogue

| Rule | Verified public finding | Evidence / implementation |
| --- | --- | --- |
| Product | RON; published simulator 2,500-250,000 RON; term 18-60 months. Prose expresses 500-50,000 EUR equivalent. | Use a labelled snapshot of the simulator's RON bounds, not an implicit permanent FX conversion. Check both requested and financed principal. |
| Minimum age | 21 years. | Verified profile birth date and assessment date. Calendar age, not approximate days/365. |
| Maturity age | Maximum 63 for women / 65 for men, at the end of the loan. | Explicit, backend-verified reference-policy category. Never infer a category from name/CNP. An unspecified category requires review. Published sex-based limits need compliance approval before live use. |
| Employment | At least three months at the current employer. | Compare calendar dates; three months is not invariably 90 days. |
| Contract | Indefinite, or fixed term covering the loan, or fixed term with at least two successive renewals. | Require contract end date / renewal evidence. A missing renewal count is not zero. |
| Income | At least minimum net income in the economy; stable and verifiable. | Net threshold is effective-dated configuration. **2,700 RON in this demo is an explicit synthetic assumption**, not an official net minimum or verified Raiffeisen threshold. No inference from HG's gross value. |
| Other income | Public documentation discusses pensions, independent activity, rent, dividends and foreign income, subject to product-specific analysis. | Automatic income checks initially support domestic salary only. Other income routes to review, not categorical refusal. |
| Documents | ID and an ANAF income consultation agreement; additional evidence may be requested. | Require a verified, unexpired synthetic identity document and backend authorization. OCR alone is not verification. Payslips/bank statements are not unconditionally demanded as a real-bank rule. |
| History | No enforced loans or loans repaid with large repeated delays. The numeric severity definition is not public. | Consume explicit synthetic provider classifications. Unclassified, disputed or other adverse history requires review. Never invent a 30/60/90-day underwriting cutoff. |
| Affordability | Art. 19 ordinary total indebtedness ceiling 40%; internal limits can be stricter. | Decimal-safe (existing debt service + proposed debt service) / verified net income. Compare before percentage-display rounding. |
| Revolving debts | Art. 13(2): at least 3% of the granted facility limit. | Include unused cards/overdrafts; take the larger of reported service and configured limit factor. Round the floor upward to cents. |
| Unequal repayments | Art. 13(1^1): largest obligation during the credit duration. | Require maximum payment for decreasing/unequal existing debt; use the first/highest payment for decreasing proposed loans. |
| Exclusions | First-home 45% rule, FX 20%/25% limits and art. 20 portfolio-volume derogations are distinct cases. | Do not apply these exceptions to the new RON personal-loan MVP. No automatic portfolio derogation. Foreign-currency obligations need review rather than guessed conversions. |

Calendar-age boundaries in the demo use completed years (age 65 is within a
65-year limit; age 66 is not). Month addition clamps to the last day of the target
month. These conventions are explicit demo interpretations, not a contractual
bank maturity calculation.

## Bureau inquiry, privacy and score

The detailed notice publishes a FICO range of **300-850**, but no approval cutoff.
Scores are informational in this release, including missing scores/no history.
An unavailable report is **not** equivalent to a clean or empty report.

The IMPORTANT passage distinguishes a pre-offer inquiry that does not affect FICO
from a later credit-application inquiry that can affect it. This branch accepts
only synthetic `PRELIMINARY` inquiries and never performs either inquiry live.

ANAF consent is distinct from bureau-processing legal basis, notice acknowledgement
and backend permission. Sections 4.3/4.4 discuss legitimate-interest processing
and consent-dependent purposes. The demo stores explicit, purpose-scoped records;
their labels do not establish a lawful basis for a real bank. A real provider
requires approved contracts, permission checks and a current legal review.

Section 8.2 describes bureau retention up to four years from update and up to six
months for abandoned/unsuccessful requests. Section 10.3 describes reporting after
30 calendar days from the due date and prior notification. **Reporting criteria
are not underwriting rejection criteria.** No minimum overdue amount or 15-day
notification period was verified here; neither is invented in code. This branch
does not report borrowers or implement a production retention schedule.

Rights include access, rectification and applicable objection/restriction/deletion,
plus human intervention in automated decisions. All prototype applications require
human review regardless of whether public bank processes allow automation.

## Pricing evidence and known-result check

The product page displayed a 2026-10-15 to 2026-11-26 campaign: fixed nominal rates
5.55%-17.95%, 200 RON analysis fee and 5 RON monthly administration fee in its
examples. Optional insurance / recurring inflows affect promotional pricing;
they are not universal eligibility requirements. Never assume every applicant
receives the minimum rate or substitute DAE for the nominal interest rate.

For the published 50,000 RON **financed principal** example, at 5.55% for 60 months,
the annuity plus the monthly 5 RON fee is **961.21 RON**. The financed principal
already includes the analysis fee and, where selected, the single insurance
premium: do not add them twice. Calculations were independently checked with
Python Decimal. Product-specific quotes remain indicative.

## Unverified / intentionally out of scope

- Internal score cutoffs, income adjustment factors, arrears severity thresholds,
  fraud/AML rules, residency/citizenship restrictions and pension-specific policy.
- Live ANAF, bureau, CRC, KYC, sanctions or employment-registry API formats/endpoints.
  Public information is not an integration contract. No real CNPs are necessary.
- Production authentication, reviewer assignment, workflow transitions and
  production database/retention infrastructure. The implementation provides scoped
  synthetic adapters and local assessment persistence, not a complete bank platform.
- Evidence freshness windows and retry settings: explicit demo configuration.

Any future rule change requires versioning, reviewed provenance and tests. Expired,
conflicting or missing policy/evidence cannot silently yield a positive result.