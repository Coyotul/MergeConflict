import Decimal from "decimal.js";
import type { LoanQuote } from "@banking/demo/types";
import { formatMoney } from "@banking/demo/format";
import { sumMoney } from "@banking/demo/finance";
import { Metric } from "@banking/ui/primitives";

export function QuoteSummary({ quote }: { quote: LoanQuote }) {
  const insurance = new Decimal(quote.monthlyInsurance).mul(quote.months).toFixed(2);
  return <div className="rounded-2xl bg-brand-soft/70 p-5"><p className="text-xs text-slate-500">Your estimated monthly payment</p><p className="mt-1 text-3xl font-semibold tracking-tight text-brand-ink">{formatMoney(quote.monthlyPayment)}</p><div className="mt-5 grid grid-cols-2 gap-4"><Metric label="Fixed nominal annual rate" value={`${quote.annualRate}%`} /><Metric label="Total repayment" value={formatMoney(quote.totalCost)} /><Metric label="Interest cost" value={formatMoney(quote.interestCost)} /><Metric label="Fees & insurance" value={formatMoney(sumMoney([quote.fee, insurance]))} hint={`${formatMoney(quote.fee)} upfront · ${formatMoney(quote.monthlyInsurance)}/mo`} /></div></div>;
}
