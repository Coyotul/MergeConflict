# Selected Project: Agentic AI Banking and Credit Management

Build a bank-agnostic AI assistant covering the customer credit lifecycle and
helping staff review applications with independently inspectable evidence.
The full owner-supplied requirements are preserved in `SPECIFICATION.md`.

## Core capabilities

- Answer credit product and eligibility questions using cited banking policies.
- Collect loan application details and synthetic supporting documents (ID,
  payslip and bank statement).
- Extract and validate information; request missing or inconsistent details.
- Evaluate eligibility using deterministic rules such as debt-to-income ratio,
  age and document validity.
- Simulate loan offers and repayment scenarios using product and pricing rules.
- Require explicit customer submission confirmation and authorized human review
  for every new credit application in the prototype.
- Support refinancing/debt consolidation, partial and full early repayment,
  repayment-period changes and restructuring requests.
- Explain contract clauses with document references and help recover incomplete,
  rejected or blocked applications without promising approval.
- Provide consent-based financial early warnings and life-event simulations,
  clearly separating estimates from verified facts.
- Provide customer, reviewer and administrator experiences, notifications,
  persistent workflows and audit history.
- Keep approval, signature and disbursement separate; simulate financial
  execution in the prototype.

## Demo outcome

A synthetic customer applies for a personal loan, receives grounded answers and
deterministic simulations, confirms submission, responds to a reviewer's request
for a missing document and sees the human-recorded final outcome. The full audit
and status history persists. Also demonstrate at least one refinancing or early
repayment simulation. The AI never independently approves or rejects credit.
