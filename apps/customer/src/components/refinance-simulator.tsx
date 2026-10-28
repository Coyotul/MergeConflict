"use client";

import { useId, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { compareRefinancing } from "@banking/demo/finance";
import { formatMoney } from "@banking/demo/format";
import { InfoNote, Pill } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";

export function RefinanceSimulator() {
  const { snapshot, command, busy } = useDemo();
  const id = useId();
  const [selected, setSelected] = useState<string[]>(snapshot?.loans.map((l) => l.id) ?? []);
  const [months, setMonths] = useState(60);
  const [requested, setRequested] = useState(false);
  let calculation;
  try { calculation = compareRefinancing(snapshot?.loans.filter((l) => selected.includes(l.id)) ?? [], "7.50", months, "250.00"); }
  catch (e) { calculation = e instanceof Error ? e.message : "Cannot compare these inputs."; }
  const quote = typeof calculation === "string" ? null : calculation;
  return <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><h3 className="flex items-center gap-2 text-sm font-semibold"><RefreshCw className="size-4 text-ink" />Refinancing comparison</h3><Pill tone="brand">Indicative</Pill></div><fieldset><legend className="field-label">Which obligations would you like to compare?</legend><div className="space-y-2">{snapshot?.loans.map((loan) => <label key={loan.id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 text-xs"><input type="checkbox" checked={selected.includes(loan.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, loan.id] : selected.filter((s) => s !== loan.id))} className="size-4" /><span className="flex-1 font-semibold">{loan.name}</span><span className="text-slate-500">{formatMoney(loan.principal)}</span></label>)}</div></fieldset><div><label htmlFor={`${id}-term`} className="field-label">New duration: {months} months</label><input id={`${id}-term`} type="range" min="12" max="84" step="6" value={months} onChange={(e) => setMonths(Number(e.target.value))} className="w-full" /></div>
    {quote ? <><div className="table-wrap"><table className="data-table"><thead><tr><th>Comparison</th><th>Current loans</th><th>New scenario</th></tr></thead><tbody><tr><td>Monthly payment</td><td>{formatMoney(quote.currentMonthly)}</td><td className="font-semibold text-brand-ink">{formatMoney(quote.newQuote.monthlyPayment)}</td></tr><tr><td>Remaining total repayment</td><td>{formatMoney(quote.currentTotal)}</td><td className="font-semibold">{formatMoney(quote.newQuote.totalCost)}</td></tr></tbody></table></div><InfoNote warning={Number(quote.totalSavings) < 0}>Monthly difference: <strong>{formatMoney(quote.monthlySavings)}</strong> {Number(quote.monthlySavings) >= 0 ? "less" : "more (negative savings)"}. {Number(quote.totalSavings) < 0 ? <>But the new scenario costs <strong>{formatMoney(Math.abs(Number(quote.totalSavings)))}</strong> more in total. Lower installments do not automatically make refinancing beneficial.</> : <>Indicative total savings: <strong>{formatMoney(quote.totalSavings)}</strong>.</>}</InfoNote><p className="text-[10px] leading-relaxed text-slate-400">Synthetic 7.50% fixed nominal annual rate, 250 RON new-loan fee, no insurance or existing-loan payoff fees. Current balances are principal only. Verified payoff statements, exact settlement amounts and additional fees are required for a real comparison.</p></> : <p role="alert" className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{calculation as string}</p>}
    <Button variant="outline" className="w-full" disabled={busy || requested || !quote} onClick={() => { void command("/support", { message: "Please review my indicative refinancing comparison. I understand this does not submit a real refinancing application." }).then(() => setRequested(true)).catch(() => {}); }}>{requested ? "Demo support request recorded" : "Request help understanding this comparison"}</Button><p className="text-[10px] text-slate-400">No existing loan is settled or closed. No new refinancing application is automatically submitted.</p></div>;
}
