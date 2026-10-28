"use client";

import Link from "next/link";
import { ArrowRight, Check, ChevronRight, FileCheck2, ShieldCheck, Sparkles } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { calculateLoan, sumMoney } from "@banking/demo/finance";
import { documentLabels, formatDate, formatMoney, statusLabels } from "@banking/demo/format";
import { Panel, Pill, StatusBadge } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";

export function ContextPanel() {
  const { snapshot } = useDemo();
  if (!snapshot) return null;
  const app = snapshot.applications.find((a) => !["APPROVED", "REJECTED", "CANCELLED"].includes(a.status)) ?? snapshot.applications[0];
  const total = sumMoney(snapshot.loans.map((l) => calculateLoan(l.principal, l.annualRate, l.remainingMonths).monthlyPayment));

  return (
    <aside className="hidden w-[290px] shrink-0 flex-col gap-4 border-l border-slate-100 bg-slate-50 px-5 py-5 xl:flex 2xl:w-[315px] h-full overflow-y-auto min-h-0" aria-label="Financial context">
      <div>
        <p className="text-xs font-semibold text-slate-700">At a glance</p>
        <p className="mt-0.5 text-xs text-slate-500">Your synthetic financial picture</p>
      </div>
      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Your next payment</h2>
          <span className="flex size-8 items-center justify-center rounded-xl bg-brand-soft text-brand-ink">
            <FileCheck2 className="size-4" />
          </span>
        </div>
        <p className="text-2xl font-semibold tracking-tight">{formatMoney(total, 0)}</p>
        <p className="mt-1 text-xs text-slate-500">
          {snapshot.loans.length} loans · {formatDate(snapshot.loans[0].nextPaymentDate)}
        </p>
        <div className="mt-3.5 border-t border-slate-100 pt-2.5">
          <Link href="/loans" className="flex items-center justify-between text-xs font-semibold text-brand-ink">
            View your loans<ChevronRight className="size-4" />
          </Link>
        </div>
      </Panel>
      {app && (
        <Panel>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Active application</h2>
            <span className="text-xs text-slate-500">{app.reference}</span>
          </div>
          <p className="mb-1 text-lg font-semibold">{formatMoney(app.amount, 0)}</p>
          <p className="mb-3 text-xs text-slate-500">
            {snapshot.products.find((p) => p.id === app.productId)?.name} · {app.months} months
          </p>
          <StatusBadge status={app.status} label={statusLabels[app.status]} />
          <div className="my-3.5 flex gap-1.5">
            {[0, 1, 2, 3].map((n) => (
              <span
                key={n}
                className={`h-1.5 flex-1 rounded-full ${
                  n < (app.status === "PENDING_HUMAN_REVIEW" ? 3 : app.status === "APPROVED" ? 4 : 2)
                    ? "bg-primary"
                    : "bg-slate-100"
                }`}
              />
            ))}
          </div>
          <div className="space-y-2">
            {app.documents
              .filter((d) => d.kind !== "statement" || app.requestedDocument === "statement" || d.status === "FORMAT_ACCEPTED")
              .map((d) => (
                <div key={d.kind} className="flex items-center justify-between text-xs">
                  <span className="text-slate-600">{documentLabels[d.kind]}</span>
                  {d.status === "FORMAT_ACCEPTED" ? (
                    <Check className="size-3.5 text-emerald-500" />
                  ) : (
                    <Pill tone="amber" className="px-2 py-0 text-xs">Needed</Pill>
                  )}
                </div>
              ))}
          </div>
          <Button asChild variant="secondary" size="sm" className="mt-4 w-full">
            <Link href="/applications">Continue application<ArrowRight /></Link>
          </Button>
        </Panel>
      )}
      <div className="rounded-2xl bg-brand-soft p-4">
        <span className="mb-2.5 flex size-8 items-center justify-center rounded-xl bg-white text-ink">
          <Sparkles className="size-4" />
        </span>
        <p className="text-xs font-semibold">Your choices stay yours.</p>
        <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
          I help you explore. You confirm every submission. An independent reviewer makes the demo decision.
        </p>
      </div>
      <div className="mt-auto flex items-start gap-2 px-1 pt-2">
        <ShieldCheck className="size-4 shrink-0 text-slate-400" />
        <p className="text-xs leading-relaxed text-slate-500">
          Local synthetic data only.<br />
          <Link href="/settings" className="text-brand-ink hover:underline">Privacy & data preferences</Link>
        </p>
      </div>
    </aside>
  );
}
