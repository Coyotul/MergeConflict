import Decimal from "decimal.js";
import type { Assessment, Loan, LoanQuote, Money, PaymentRow, RefinanceQuote, RepaymentQuote } from "./types";

const D = Decimal.clone({ precision: 40, rounding: Decimal.ROUND_HALF_UP });
const cents = (n: Decimal) => n.toDecimalPlaces(2, Decimal.ROUND_HALF_UP);
const money = (n: Decimal) => cents(n).toFixed(2);
function value(input: Money, label: string, zero = false) {
  if (!/^\d+(\.\d{1,2})?$/.test(input)) throw new Error(`${label} must be a decimal amount.`);
  const n = new D(input);
  if (!n.isFinite() || (zero ? n.lt(0) : n.lte(0)) || n.gt(10000000)) throw new Error(`${label} is out of range.`);
  return n;
}
function validateMonths(months: number) {
  if (!Number.isInteger(months) || months < 1 || months > 600) throw new Error("Duration must be between 1 and 600 months.");
}
function rateValue(rate: Money) {
  const r = value(rate, "Interest", true);
  if (r.gt(100)) throw new Error("Interest must not exceed 100%.");
  return r.div(1200);
}
function scheduleFor(principal: Decimal, rate: Decimal, payment: Decimal, maxMonths: number, fixedTerm: boolean) {
  const schedule: PaymentRow[] = [];
  let balance = cents(principal);
  for (let month = 1; month <= maxMonths && balance.gt(0); month++) {
    const interest = cents(balance.mul(rate));
    if (payment.lte(interest)) throw new Error("Payment does not cover interest.");
    const due = (fixedTerm && month === maxMonths) ? balance.plus(interest) : D.min(payment, balance.plus(interest));
    const repaid = cents(due.minus(interest));
    balance = cents(balance.minus(repaid));
    schedule.push({ month, payment: money(due), interest: money(interest), principal: money(repaid), balance: money(balance) });
  }
  if (balance.gt(0)) throw new Error("The repayment schedule exceeds the supported duration.");
  return schedule;
}
function assemble(amount: Money, annualRate: Money, schedule: PaymentRow[], installment: Decimal, fee: Decimal, insurance: Decimal): LoanQuote {
  const interest = schedule.reduce((sum, row) => sum.plus(row.interest), new D(0));
  const total = schedule.reduce((sum, row) => sum.plus(row.payment), fee).plus(insurance.mul(schedule.length));
  return { amount: money(new D(amount)), annualRate, months: schedule.length, installment: money(installment), monthlyPayment: money(installment.plus(insurance)), fee: money(fee), monthlyInsurance: money(insurance), interestCost: money(interest), totalCost: money(total), schedule };
}
export function calculateLoan(amount: Money, annualRate: Money, months: number, fee: Money = "0", insurance: Money = "0"): LoanQuote {
  validateMonths(months);
  const principal = value(amount, "Loan amount");
  const rate = rateValue(annualRate);
  const installment = cents(rate.isZero() ? principal.div(months) : principal.mul(rate).div(new D(1).minus(new D(1).plus(rate).pow(-months))));
  if (installment.lte(0)) throw new Error("Amount is too small for this duration.");
  return assemble(amount, annualRate, scheduleFor(principal, rate, installment, months, true), installment, value(fee, "Fee", true), value(insurance, "Insurance", true));
}
export function simulateRepayment(loan: Loan, repayment: Money, feePercent: Money = "1"): RepaymentQuote {
  const paid = value(repayment, "Repayment");
  const principal = value(loan.principal, "Principal");
  if (paid.gte(principal)) throw new Error("For full repayment, request an authoritative settlement quote from your bank.");
  const newPrincipal = money(principal.minus(paid));
  const current = calculateLoan(loan.principal, loan.annualRate, loan.remainingMonths);
  const reducedPayment = calculateLoan(newPrincipal, loan.annualRate, loan.remainingMonths);
  const installment = new D(current.installment);
  const schedule = scheduleFor(new D(newPrincipal), rateValue(loan.annualRate), installment, loan.remainingMonths, false);
  const reducedTerm = assemble(newPrincipal, loan.annualRate, schedule, installment, new D(0), new D(0));
  const earlyFee = cents(paid.mul(value(feePercent, "Repayment fee", true)).div(100));
  return { current, reducedPayment, reducedTerm, repayment: money(paid), newPrincipal, earlyFee: money(earlyFee), paymentSavings: money(new D(current.monthlyPayment).minus(reducedPayment.monthlyPayment)), interestSavings: money(new D(current.interestCost).minus(reducedTerm.interestCost).minus(earlyFee)), monthsSaved: loan.remainingMonths - reducedTerm.months };
}
export function compareRefinancing(loans: Loan[], annualRate: Money, months: number, fee: Money): RefinanceQuote {
  if (!loans.length) throw new Error("Select at least one existing loan.");
  const quotes = loans.map((loan) => calculateLoan(loan.principal, loan.annualRate, loan.remainingMonths));
  const sum = (fn: (q: LoanQuote) => Money) => quotes.reduce((n, q) => n.plus(fn(q)), new D(0));
  const principal = money(sum((q) => q.amount));
  const newQuote = calculateLoan(principal, annualRate, months, fee);
  const currentMonthly = sum((q) => q.monthlyPayment);
  const currentTotal = sum((q) => q.totalCost);
  return { principal, newQuote, currentMonthly: money(currentMonthly), currentTotal: money(currentTotal), monthlySavings: money(currentMonthly.minus(newQuote.monthlyPayment)), totalSavings: money(currentTotal.minus(newQuote.totalCost)) };
}
export function assessAffordability(income: Money, obligations: Money, quote: LoanQuote, threshold: Money = "40"): Assessment {
  const ratio = value(obligations, "Obligations", true).plus(quote.monthlyPayment).div(value(income, "Income")).mul(100);
  const satisfied = ratio.lte(value(threshold, "Threshold"));
  return { status: satisfied ? "PRELIMINARY_REQUIREMENTS_SATISFIED" : "MANUAL_REVIEW_REQUIRED", debtRatio: ratio.toFixed(2), threshold, policyVersion: "DEMO-2026.1", reasons: [satisfied ? "Within the configured demo debt-to-income threshold." : "Exceeds the configured demo debt-to-income threshold; independent manual assessment is needed.", "Income and obligations are synthetic, not externally verified. This is not credit approval."] };
}
export function sumMoney(values: Money[]): Money { return money(values.reduce((sum, n) => sum.plus(n), new D(0))); }
export function subtractMoney(a: Money, b: Money): Money { return money(new D(a).minus(b)); }
