"use client";

import { useDemo } from "@banking/demo/react";
import { calculateLoan } from "@banking/demo/finance";
import { formatDate, formatMoney } from "@banking/demo/format";
import { Metric, Pill } from "@banking/ui/primitives";
import { ScheduleTable } from "./schedule-table";

export function LoanDetails() {
  const { snapshot } = useDemo();
  return <div className="space-y-3">{snapshot?.loans.map((loan) => {
    const quote = calculateLoan(loan.principal, loan.annualRate, loan.remainingMonths);
    return <section key={loan.id} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">{loan.name}</h3><Pill tone="slate">Synthetic account</Pill></div><div className="grid grid-cols-2 gap-5"><Metric label="Outstanding principal" value={formatMoney(loan.principal)} /><Metric label="Indicative monthly payment" value={formatMoney(quote.monthlyPayment)} /><Metric label="Next payment" value={formatDate(loan.nextPaymentDate)} /><Metric label="Remaining duration" value={`${loan.remainingMonths} months`} /></div><p className="text-[10px] text-slate-400">Fixed nominal rate {loan.annualRate}%. Not a full-settlement quote.</p><ScheduleTable quote={quote} /></section>;
  })}</div>;
}
