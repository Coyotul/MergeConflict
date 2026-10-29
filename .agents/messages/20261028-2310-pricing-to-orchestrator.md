# Handoff: Loan Pricing & Simulation to Orchestrator

- **From:** BanicaCristian04 (Claude Code) / pricing
- **To:** Orchestrator owner (ORCH-01), eligibility (affordability)
- **Branch:** `feature/loan-pricing-simulation` (not merged to `main`)
- **Summary:** The deterministic pricing layer is ready in `src/services/pricing/`:
  - `calculate_loan_offer`: schedule, fees, insurance, total cost, DAE, affordability check.
  - `simulate_early_repayment`: partial or full; reduce instalment or term; OUG 50/2010 fee.
  - `compare_refinancing_options`: monthly and total-cost trade-off, no assumed benefit.

  Results are typed Pydantic models with `status`, `errors`, `assumptions` and
  `indicative=True`. The 64 tests reproduce Raiffeisen Romania's published examples exactly
  (961.21 lei, DAE 9.49%, and others). See `src/services/pricing/README.md` and
  `docs/decisions/008-loan-pricing-engine.md`.
- **Action required (orchestrator):** `handle_calculate_offers` in `src/agent/tools/stubs.py`
  still uses one illustrative rate with 0 fees and no DAE. Replace it with
  `calculate_loan_offer`, mapping product codes to `config/products/*.json` IDs
  (`personal_loan_fixed`, `refinancing_fixed`, `mortgage_fixed_then_ircc`). Register
  `simulate_early_repayment` and `compare_refinancing_options` as tools when needed. Pass an
  explicit `simulation_date`, and show `assumptions` and `disclaimer` to the customer.
- **Note (eligibility):** `src/services/financial_calculations/affordability.py` is unchanged.
  The pricing layer has its own simple debt-service check
  (`config/rules/affordability.json`, 40% limit) for simulations. Eligibility decisions should
  keep using the eligibility service.
- **Not modelled yet:** mortgage valuation and property insurance (mortgage DAE flagged
  incomplete), day-count interest, insurance refunds, non-RON currencies. IRCC values in
  `config/rules/ircc.json` need a quarterly update.
