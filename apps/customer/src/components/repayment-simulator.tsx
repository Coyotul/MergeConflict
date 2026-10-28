"use client";

import { useId, useState } from "react";
import { TrendingDown } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { simulateRepayment } from "@banking/demo/finance";
import { formatMoney } from "@banking/demo/format";
import { InfoNote, Metric, Pill } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";

export function RepaymentSimulator() {
  const { snapshot, command, busy } = useDemo();
  const id = useId();
  const [loanId, setLoanId] = useState(snapshot?.loans[0]?.id ?? "");
  const [amount, setAmount] = useState("5000");
  const [requested, setRequested] = useState(false);
  const loan = snapshot?.loans.find((l) => l.id === loanId);
  if (!loan) return <InfoNote>No synthetic loans are available to simulate.</InfoNote>;
  let calculation;
  try { calculation = simulateRepayment(loan, amount); } catch (e) { calculation = e instanceof Error ? e.message : "Invalid repayment."; }
  const quote = typeof calculation === "string" ? null : calculation;
  return <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><h3 className="flex items-center gap-2 text-sm font-semibold"><TrendingDown className="size-4 text-emerald-600" />Early repayment simulator</h3><Pill tone="green">Indicative</Pill></div><div className="grid gap-4 sm:grid-cols-2"><div><label className="field-label" htmlFor={`${id}-loan`}>Which loan?</label><select className="field" id={`${id}-loan`} value={loanId} onChange={(e) => setLoanId(e.target.value)}>{snapshot?.loans.map((l) => <option key={l.id} value={l.id}>{l.name} · {formatMoney(l.principal, 0)}</option>)}</select></div><div><label className="field-label" htmlFor={`${id}-amount`}>Partial repayment · RON</label><input id={`${id}-amount`} className="field" type="number" min="1" max={Number(loan.principal) - 1} step="100" value={amount} onChange={(e) => setAmount(e.target.value)} /></div></div>
    {quote ? <><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4"><p className="mb-4 text-xs font-semibold text-emerald-700">Option A · Lower payment</p><Metric label="New monthly installment" value={formatMoney(quote.reducedPayment.monthlyPayment)} hint={`${formatMoney(quote.paymentSavings)} less per month`} /><p className="mt-4 text-xs text-slate-500">Same remaining term: {loan.remainingMonths} months</p><p className="mt-1 text-xs text-slate-500">Remaining interest: {formatMoney(quote.reducedPayment.interestCost)}</p></div><div className="rounded-2xl border border-brand-border/60 bg-brand-soft/40 p-4"><p className="mb-4 text-xs font-semibold text-brand-ink">Option B · Shorter term</p><Metric label="New remaining term" value={`${quote.reducedTerm.months} months`} hint={`${quote.monthsSaved} months earlier`} /><p className="mt-4 text-xs text-slate-500">Keep payment: {formatMoney(quote.current.monthlyPayment)}</p><p className="mt-1 text-xs text-slate-500">Net interest saved: {formatMoney(quote.interestSavings)}</p></div></div><InfoNote>New principal {formatMoney(quote.newPrincipal)}. Fictional early repayment fee: {formatMoney(quote.earlyFee)} (1%). Net interest savings include that fee. Fixed synthetic rate and no insurance assumed; final payment can differ.</InfoNote></> : <p role="alert" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{calculation as string}</p>}
    <Button variant="outline" className="w-full" disabled={busy || requested} onClick={() => { void command("/support", { message: "Please explain the indicative early repayment options for my synthetic loan." }).then(() => setRequested(true)).catch(() => {}); }}>{requested ? "Demo support request recorded" : "Discuss these options with a representative"}</Button><p className="text-[10px] leading-relaxed text-slate-400">Simulation only. No payment is authorized or executed. Full repayment requires an authoritative date-specific settlement quote, which is unavailable in this prototype.</p></div>;
}
