"use client";

import { FileText } from "lucide-react";
import type { ApplicationSummaryBlock } from "@banking/demo/orchestrator";
import { formatMoneyString } from "@banking/demo/orchestrator-format";
import { documentStatusLabel } from "@banking/demo/orchestrator-labels";
import { Button } from "@banking/ui/button";
import { Pill } from "@banking/ui/primitives";

export function SummaryBlockComponent({
  block,
  canConfirm,
  onConfirm,
  disabled,
}: {
  block: ApplicationSummaryBlock;
  canConfirm: boolean;
  onConfirm: (summaryVersion: string, decision: "confirm" | "decline") => void;
  disabled: boolean;
}) {
  const { summary } = block;

  return (
    <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">
      <div className="mb-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {summary.application_id} · {summary.product_name}
        </p>
        <h3 className="mt-1.5 text-xl font-semibold tracking-tight text-ink">
          {formatMoneyString(summary.amount.amount, summary.amount.currency)}
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          {summary.term_months} months ·{" "}
          {formatMoneyString(
            summary.offer.monthly_installment.amount,
            summary.offer.monthly_installment.currency
          )}{" "}
          / month
        </p>
      </div>

      <div className="mb-4 space-y-2 border-t border-slate-100 pt-4">
        <p className="text-xs font-semibold text-ink">Your details</p>
        {summary.fields.map((field, index) => (
          <div
            key={index}
            className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 p-3"
          >
            <div className="flex-1">
              <p className="text-xs text-slate-500">{field.label}</p>
              <p className="mt-0.5 text-sm font-medium text-slate-700">
                {field.value}
              </p>
            </div>
            <span className="text-[10px] text-slate-400">{field.source}</span>
          </div>
        ))}
      </div>

      <div className="mb-4 border-t border-slate-100 pt-4">
        <p className="mb-2 text-xs font-semibold text-ink">Documents</p>
        <div className="space-y-2">
          {summary.documents.map((doc, index) => (
            <div
              key={index}
              className="flex items-center gap-2 rounded-lg bg-slate-50 p-2"
            >
              <FileText className="size-4 text-slate-400" />
              <span className="text-xs text-slate-600">{doc.label}</span>
              <Pill
                tone={doc.status === "accepted" ? "green" : "slate"}
                className="ml-auto px-2 py-0 text-[9px]"
              >
                {documentStatusLabel(doc.status)}
              </Pill>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-4 border-t border-slate-100 pt-4">
        <p className="mb-2 text-xs font-semibold text-ink">Selected offer</p>
        <div className="grid grid-cols-2 gap-4 rounded-lg bg-slate-50 p-3">
          <div>
            <p className="text-xs text-slate-500">Term</p>
            <p className="mt-0.5 text-sm font-semibold text-slate-700">
              {summary.offer.term_months} months
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Interest</p>
            <p className="mt-0.5 text-sm font-semibold text-slate-700">
              {summary.offer.annual_interest_rate_percent}%
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Monthly</p>
            <p className="mt-0.5 text-sm font-semibold text-slate-700">
              {formatMoneyString(
                summary.offer.monthly_installment.amount,
                summary.offer.monthly_installment.currency
              )}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Total cost</p>
            <p className="mt-0.5 text-sm font-semibold text-slate-700">
              {formatMoneyString(
                summary.offer.total_cost.amount,
                summary.offer.total_cost.currency
              )}
            </p>
          </div>
        </div>
      </div>

      {canConfirm && (
        <div className="flex gap-2 border-t border-slate-100 pt-4">
          <Button
            className="flex-1"
            disabled={disabled}
            onClick={() => onConfirm(summary.summary_version, "confirm")}
            aria-label="Confirm & submit for human review"
          >
            Confirm & submit for human review
          </Button>
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => onConfirm(summary.summary_version, "decline")}
            aria-label="Not yet"
          >
            Not yet
          </Button>
        </div>
      )}
    </div>
  );
}
