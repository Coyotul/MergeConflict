"use client";

import { useId, useRef, useState } from "react";
import { ArrowRight, ChartNoAxesColumnIncreasing } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { assessAffordability, calculateLoan, sumMoney } from "@banking/demo/finance";
import type { LoanApplication, Product } from "@banking/demo/types";
import type { CreateApplicationInput } from "@banking/demo/schemas";
import { formatMoney } from "@banking/demo/format";
import { Button } from "@banking/ui/button";
import { InfoNote, Pill } from "@banking/ui/primitives";
import { ApplicationCard } from "./application-card";
import { QuoteSummary } from "./quote-summary";
import { ScheduleTable } from "./schedule-table";

export function LoanSimulator({ product, initialAmount, initialMonths }: { product: Product; initialAmount?: string; initialMonths?: number }) {
  const { snapshot, command, busy } = useDemo();
  const id = useId();
  const [amount, setAmount] = useState(initialAmount ?? (product.id === "mortgage" ? "300000" : product.id === "car" ? "50000" : "30000"));
  const [months, setMonths] = useState(initialMonths ?? (product.id === "mortgage" ? 240 : product.id === "car" ? 60 : 36));
  const [preparedId, setPreparedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ fingerprint: string; key: string } | null>(null);
  let calculation;
  try {
    if (Number(amount) < Number(product.minAmount) || Number(amount) > Number(product.maxAmount) || months < product.minMonths || months > product.maxMonths) throw new Error("Choose an amount and duration within the demo product limits.");
    calculation = calculateLoan(amount, product.annualRate, months, product.fee, product.monthlyInsurance);
  } catch (e) { calculation = e instanceof Error ? e.message : "Invalid amount."; }
  const quote = typeof calculation === "string" ? null : calculation;
  const obligations = sumMoney((snapshot?.loans ?? []).map((loan) => calculateLoan(loan.principal, loan.annualRate, loan.remainingMonths).monthlyPayment));
  const assessment = quote && snapshot ? assessAffordability(snapshot.customer.monthlyIncome, obligations, quote) : null;
  const prepared = snapshot?.applications.find((app) => app.id === preparedId);
  async function prepare() {
    const fingerprint = `${product.id}:${amount}:${months}`;
    if (key.current?.fingerprint !== fingerprint) key.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const app = await command<LoanApplication>("/applications", { amount, months, productId: product.id as CreateApplicationInput["productId"], idempotencyKey: key.current.key });
      setPreparedId(app.id); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not prepare the application."); }
  }
  if (prepared) return <ApplicationCard application={prepared} />;
  return <div className="space-y-4 rounded-2xl border border-brand-border/35 bg-white p-5"><div className="flex items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-sm font-semibold"><ChartNoAxesColumnIncreasing className="size-4 text-ink" />{product.name} simulator</h3><Pill tone="brand">Indicative only</Pill></div><div className="grid grid-cols-1 gap-4 sm:grid-cols-2"><div><label htmlFor={`${id}-amount`} className="field-label">How much do you need? · RON</label><input id={`${id}-amount`} className="field" type="number" min={product.minAmount} max={product.maxAmount} step="100" value={amount} onChange={(e) => setAmount(e.target.value)} /><p className="mt-2 text-[10px] text-slate-400">{formatMoney(product.minAmount, 0)} – {formatMoney(product.maxAmount, 0)}</p></div><div><label htmlFor={`${id}-months`} className="field-label">Repayment period · months</label><input id={`${id}-months`} className="field" type="number" min={product.minMonths} max={product.maxMonths} value={months} onChange={(e) => setMonths(Number(e.target.value))} /><input aria-label="Repayment period slider" type="range" className="mt-3 w-full" min={product.minMonths} max={product.maxMonths} step={1} value={months} onChange={(e) => setMonths(Number(e.target.value))} /></div></div>
    {quote ? <><QuoteSummary quote={quote} />{assessment && <InfoNote warning={assessment.status === "MANUAL_REVIEW_REQUIRED"}>Synthetic debt-to-income ratio: <strong>{assessment.debtRatio}%</strong> (demo threshold {assessment.threshold}%). {assessment.reasons[0]} This is preliminary screening, not approval.</InfoNote>}<ScheduleTable quote={quote} /><Button className="w-full" disabled={busy} onClick={() => { void prepare(); }}>Choose scenario & prepare application<ArrowRight /></Button></> : <p role="alert" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{calculation as string}</p>}
    {product.id === "mortgage" && <InfoNote warning>Mortgage figures are illustrative. Property valuation, down payment, collateral checks and bank-specific mortgage conditions are not connected.</InfoNote>}{error && <p role="alert" className="text-xs text-red-600">{error}</p>}<p className="text-[10px] leading-relaxed text-slate-400">Fixed synthetic rate, monthly annuity, RON cents rounded half-up; final installment adjusts rounding. Includes the fees and insurance above. Not a bank quotation or an APR disclosure. Preparing saves a draft only.</p></div>;
}
