import { test } from "node:test";
import assert from "node:assert/strict";
import Decimal from "decimal.js";
import { assessAffordability, calculateLoan, compareRefinancing, simulateRepayment } from "../src/finance";
import { seedStore } from "../src/seed";

test("known annuity: 12,000 RON, 12% nominal, 12 months", () => {
  const q = calculateLoan("12000", "12", 12);
  assert.equal(q.installment, "1066.19");
  assert.equal(q.schedule.length, 12);
  assert.equal(q.schedule[0].interest, "120.00");
  assert.equal(q.schedule[0].principal, "946.19");
  assert.equal(q.schedule.at(-1)?.balance, "0.00");
  const repaid = q.schedule.reduce((n, row) => n.plus(row.principal), new Decimal(0));
  assert.equal(repaid.toFixed(2), "12000.00");
  assert.equal(new Decimal(q.totalCost).minus(q.amount).toFixed(2), q.interestCost);
});
test("zero interest, fee and monthly insurance are counted, final cents adjusted", () => {
  const q = calculateLoan("1000", "0", 3, "10", "2");
  assert.equal(q.installment, "333.33");
  assert.equal(q.monthlyPayment, "335.33");
  assert.equal(q.schedule.at(-1)?.payment, "333.34");
  assert.equal(q.interestCost, "0.00");
  assert.equal(q.totalCost, "1016.00");
});
test("invalid financial inputs fail explicitly", () => {
  for (const bad of ["0", "-1", "NaN", "Infinity", "1.001", "hello"]) assert.throws(() => calculateLoan(bad, "8", 36));
  for (const bad of [0, -1, 1.2, 601]) assert.throws(() => calculateLoan("10000", "8", bad));
  assert.throws(() => calculateLoan("10000", "101", 36));
});
test("partial repayment lowers installment or term; full payoff is not guessed", () => {
  const loan = seedStore().loans[0];
  const q = simulateRepayment(loan, "5000");
  assert.equal(q.newPrincipal, "19750.00");
  assert.equal(q.earlyFee, "50.00");
  assert.ok(Number(q.reducedPayment.monthlyPayment) < Number(q.current.monthlyPayment));
  assert.ok(q.monthsSaved > 0);
  assert.ok(Number(q.interestSavings) > 0);
  assert.equal(q.reducedTerm.schedule.at(-1)?.balance, "0.00");
  assert.throws(() => simulateRepayment(loan, loan.principal), /authoritative settlement/);
});
test("refinancing warns that lower monthly payment can increase total repayment", () => {
  const q = compareRefinancing(seedStore().loans, "7.50", 60, "250");
  assert.equal(q.principal, "37550.00");
  assert.ok(Number(q.monthlySavings) > 0);
  assert.ok(Number(q.totalSavings) < 0);
});
test("affordability is preliminary, including existing obligations", () => {
  const q = calculateLoan("30000", "8.90", 36);
  assert.equal(assessAffordability("8500", "1000", q).status, "PRELIMINARY_REQUIREMENTS_SATISFIED");
  assert.equal(assessAffordability("2000", "1000", q).status, "MANUAL_REVIEW_REQUIRED");
  assert.throws(() => assessAffordability("0", "1000", q));
});
