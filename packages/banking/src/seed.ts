import type { Actor, DemoStore, LoanApplication } from "./types";
import { assessAffordability, calculateLoan, sumMoney } from "./finance";

export const CUSTOMER_ACTOR: Actor = { id: "customer-alex", name: "Alex Morgan", role: "customer" };
export const REVIEWER_ACTOR: Actor = { id: "reviewer-jamie", name: "Jamie Carter", role: "reviewer" };
export function seedStore(): DemoStore {
  const now = new Date().toISOString();
  const customer = { id: CUSTOMER_ACTOR.id, name: "Alex Morgan", email: "alex@example.test", initials: "AM", monthlyIncome: "8500.00", monthlyExpenses: "3200.00", balance: "12480.50", employer: "Northstar Studio · fictional" };
  const products = [
    { id: "personal", name: "Personal loan", description: "A little room for your next big idea.", annualRate: "8.90", fee: "150.00", monthlyInsurance: "0.00", minAmount: "5000.00", maxAmount: "100000.00", minMonths: 6, maxMonths: 60, policyId: "personal-policy" },
    { id: "mortgage", name: "Mortgage", description: "Make yourself at home, one clear step at a time.", annualRate: "6.50", fee: "1000.00", monthlyInsurance: "35.00", minAmount: "100000.00", maxAmount: "1500000.00", minMonths: 60, maxMonths: 360, policyId: "mortgage-policy" },
    { id: "car", name: "Car loan", description: "Find the right numbers for your next set of wheels.", annualRate: "7.90", fee: "300.00", monthlyInsurance: "15.00", minAmount: "10000.00", maxAmount: "200000.00", minMonths: 12, maxMonths: 84, policyId: "car-policy" },
  ];
  const policies = products.map((p) => ({ id: p.policyId, title: `${p.name} · synthetic product guide`, version: "DEMO-2026.1", effectiveDate: "2026-10-01", section: "§2 Pricing & §3 application evidence", content: `Fictional demo product: ${p.annualRate}% fixed annual nominal interest, ${p.fee} RON one-off fee, ${p.monthlyInsurance} RON monthly insurance. Amount ${p.minAmount}–${p.maxAmount} RON, duration ${p.minMonths}–${p.maxMonths} months. Identity and income document metadata required. A reviewer may request additional evidence. Every application requires explicit customer submission and an independent human decision. Mortgage property valuation, down payment and real bank-specific conditions are not implemented; mortgage results are illustrative only.` }));
  policies.push({ id: "repayment-policy", title: "Repayment & refinancing · demo assumptions", version: "DEMO-2026.1", effectiveDate: "2026-10-01", section: "§4 Indicative comparisons", content: "Partial early repayment simulations use a fictional 1% fee and a fixed nominal rate. Compare reduced installments with a shorter term. Refinancing uses a fictional 7.5% nominal rate and a 250 RON fee; longer duration may reduce monthly payments while increasing total cost. Outstanding principal is not an authoritative payoff amount. No repayment, settlement or debt closure occurs." });
  const due = new Date(); due.setDate(due.getDate() + 12);
  const loans = [
    { id: "loan-personal", customerId: customer.id, name: "Personal loan", principal: "24750.00", originalAmount: "35000.00", annualRate: "9.90", remainingMonths: 36, nextPaymentDate: due.toISOString() },
    { id: "loan-car", customerId: customer.id, name: "Car loan", principal: "12800.00", originalAmount: "20000.00", annualRate: "8.40", remainingMonths: 24, nextPaymentDate: due.toISOString() },
  ];
  const quote = calculateLoan("30000.00", products[0].annualRate, 36, products[0].fee);
  const obligations = sumMoney(loans.map((loan) => calculateLoan(loan.principal, loan.annualRate, loan.remainingMonths).monthlyPayment));
  const application: LoanApplication = {
    id: "demo-application-001", reference: "LM-1001", customerId: customer.id, customer, reviewerId: REVIEWER_ACTOR.id,
    productId: "personal", policyVersion: "DEMO-2026.1", amount: "30000.00", months: 36, quote,
    assessment: assessAffordability(customer.monthlyIncome, obligations, quote), status: "PENDING_HUMAN_REVIEW", createdAt: now, updatedAt: now,
    documents: [{ kind: "identity", status: "FORMAT_ACCEPTED", name: "synthetic-identity.pdf", mimeType: "application/pdf", size: 14800, uploadedAt: now }, { kind: "income", status: "FORMAT_ACCEPTED", name: "synthetic-income.pdf", mimeType: "application/pdf", size: 22400, uploadedAt: now }, { kind: "statement", status: "MISSING" }],
    history: [{ id: crypto.randomUUID(), status: "DRAFT", at: now, actor: "Demo fixture", description: "Synthetic application created for the reviewer walkthrough." }, { id: crypto.randomUUID(), status: "PENDING_HUMAN_REVIEW", at: now, actor: customer.name, description: "Seeded demo submission. No real application or bank inquiry." }], notes: [],
  };
  return { version: 1, customers: [customer], products, policies, loans, applications: [application], messages: { [customer.id]: [] }, notifications: [{ id: crypto.randomUUID(), customerId: customer.id, title: "Your demo application is in review", text: "An independent reviewer will inspect your synthetic evidence. No real credit decision is being made.", at: now, read: false, applicationId: application.id }], audit: [], consents: { [customer.id]: { financialInsights: false, notifications: true } }, idempotency: [] };
}
