"use client";

import { useState } from "react";
import { ChevronDown, TableProperties } from "lucide-react";
import type { LoanQuote } from "@banking/demo/types";
import { formatMoney } from "@banking/demo/format";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@banking/ui/dialog";

export function ScheduleTable({ quote }: { quote: LoanQuote }) {
  const [open, setOpen] = useState(false);
  return <><button onClick={() => setOpen(true)} className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-xs font-medium text-slate-600 hover:bg-slate-50"><span className="flex items-center gap-2"><TableProperties className="size-4" />View indicative repayment schedule</span><ChevronDown className="size-4" /></button><Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>Indicative repayment schedule</DialogTitle><DialogDescription>Monthly annuity with cent rounding. Final installment adjusts the balance. Upfront fee {formatMoney(quote.fee)} is separate; monthly insurance {formatMoney(quote.monthlyInsurance)} is not included in the installment column.</DialogDescription></DialogHeader><div className="table-wrap max-h-[55dvh]"><table className="data-table"><thead className="sticky top-0"><tr><th>Month</th><th>Installment</th><th>Principal</th><th>Interest</th><th>Balance</th></tr></thead><tbody>{quote.schedule.map((row) => <tr key={row.month}><td>{row.month}</td><td>{formatMoney(row.payment)}</td><td>{formatMoney(row.principal)}</td><td>{formatMoney(row.interest)}</td><td>{formatMoney(row.balance)}</td></tr>)}</tbody></table></div></DialogContent></Dialog></>;
}
