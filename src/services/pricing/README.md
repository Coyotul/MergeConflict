# Loan Pricing & Simulation

Deterministic, LLM-free loan pricing for the AI orchestrator's tools. All results are
**indicative**: they list their assumptions and never replace the bank's authoritative
pricing or settlement amounts. Design and sources:
[docs/decisions/008-loan-pricing-engine.md](../../../docs/decisions/008-loan-pricing-engine.md).

| Layer | Location | Responsibility |
|---|---|---|
| Product data | `config/products/*.json`, `config/rules/*.json` | Versioned synthetic products, IRCC values, debt-ratio limits |
| Pricing rules | `src/rules/pricing/rules.py` | Rate (base − discounts, or fixed then IRCC + margin), fees, insurance, early repayment fee |
| Financial engine | `src/services/financial_calculations/calculations.py` | Schedules, DAE, prepayment rescheduling; `Decimal` only |
| Use cases | `src/services/pricing/service.py` | The three tools below; typed errors instead of exceptions |

## Tools

```python
from datetime import date
from decimal import Decimal
from src.services.pricing import calculate_loan_offer, simulate_early_repayment, compare_refinancing_options
from src.services.pricing.models import LoanOfferRequest, EarlyRepaymentRequest, RefinancingRequest, ExistingLoan

offer = calculate_loan_offer(LoanOfferRequest(
    product_id="personal_loan_fixed", amount=Decimal("50000"), term_months=60,
    salary_account="standard", with_insurance=True, simulation_date=date(2026, 10, 28),
    net_monthly_income=Decimal("5557")))
offer.first_monthly_payment   # 961.21
offer.dae                     # 9.49
offer.affordability           # debt-service ratio vs the 40% BNR limit

simulate_early_repayment(EarlyRepaymentRequest(loan=..., after_month=12, amount=Decimal("10000"),
                                               option="reduce_term"))
compare_refinancing_options(RefinancingRequest(existing_loans=[ExistingLoan(...)], term_months=60))
```

- `status` is `"ok"` or `"invalid"`; on `"invalid"`, `errors` holds codes such as
  `AMOUNT_OUT_OF_RANGE`, `TERM_OUT_OF_RANGE`, `RATE_OUT_OF_RANGE`, `INDEX_UNAVAILABLE`,
  `INSURANCE_NOT_OFFERED`, `AMOUNT_ABOVE_BALANCE`.
- Pass `simulation_date` explicitly: it selects the IRCC value, and identical inputs then
  always give identical results.
- `amount` is the total credit amount; financed fees and insurance are deducted from what is
  paid out (`net_amount_paid_out`), as in the bank's representative example.
- `base_annual_rate` is the risk-based rate before discounts. It should come from credit
  scoring; when omitted, the product minimum is used and stated in `assumptions`.
- The orchestrator must present `assumptions`, `warnings` and `disclaimer` with the numbers,
  and must not compute or alter any figure itself.

## Known results

Tests reproduce Raiffeisen Bank Romania's published examples (cost sheet effective 15.10.2026,
"Casa Ta" page 28.10.2026): instalments and DAE exactly; totals within 5 bani, because the bank's
representative totals use unrounded instalments while a payable schedule rounds each one.

## Not modelled yet

- Mortgage valuation and property insurance (mortgage DAE is flagged `DAE_INCOMPLETE`).
- Day-count interest between instalment dates (prepayment happens right after an instalment).
- Insurance refunds on early repayment; currencies other than RON.
- The lender's allowance to exceed the 40% debt ratio for part of its portfolio.

## Tests

```bash
pytest tests/unit/services tests/unit/rules
```
