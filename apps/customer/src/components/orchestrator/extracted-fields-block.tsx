"use client";

import { useState } from "react";
import { FileText, Lock } from "lucide-react";
import type { ExtractedFieldsBlock } from "@banking/demo/orchestrator";
import { Button } from "@banking/ui/button";

const DOCUMENT_LABELS: Record<string, string> = {
  id_card: "ID card", payslip: "Payslip", bank_statement: "Bank statement",
};

/** One review of every value read from the documents. Only name and employer can be corrected. */
export function ExtractedFieldsBlockComponent({
  block,
  reviewing,
  onReview,
  disabled,
}: {
  block: ExtractedFieldsBlock;
  reviewing: boolean;
  onReview: (edits: Record<string, string>) => void;
  disabled: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(block.fields.map((f) => [f.field, f.value])),
  );
  const edits = Object.fromEntries(
    block.fields
      .filter((f) => f.editable && values[f.field].trim() !== f.value)
      .map((f) => [f.field, values[f.field].trim()]),
  );
  const blank = block.fields.some((f) => f.editable && !values[f.field].trim());

  return (
    <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4" data-testid="review-form">
      <p className="mb-1 text-sm font-semibold text-ink">
        {reviewing ? "Check the values from your documents" : "Values from your documents"}
      </p>
      {reviewing && (
        <p className="mb-4 text-xs text-slate-500">
          You can correct the name or employer. Amounts come from the documents; if one is wrong, upload a corrected document.
        </p>
      )}
      <div className="space-y-3">
        {block.fields.map((field) => (
          <div key={field.field} className="grid gap-1 sm:grid-cols-[1fr_1.4fr] sm:items-center sm:gap-4">
            <label htmlFor={`field-${field.field}`} className="text-xs font-semibold text-ink">{field.label}</label>
            <div>
              {reviewing && field.editable ? (
                <input
                  id={`field-${field.field}`}
                  className="field"
                  value={values[field.field]}
                  disabled={disabled}
                  onChange={(e) => setValues({ ...values, [field.field]: e.target.value })}
                />
              ) : (
                <p id={`field-${field.field}`} className="flex items-center gap-1.5 text-sm text-slate-700">
                  {reviewing && !field.editable && <Lock className="size-3 text-slate-400" aria-label="Read-only" />}
                  {field.value}
                </p>
              )}
              <p className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-500">
                <FileText className="size-3" />
                {DOCUMENT_LABELS[field.document_type ?? ""] ?? field.source}
                {field.confidence != null && ` · ${Math.round(field.confidence * 100)}% confidence`}
              </p>
            </div>
          </div>
        ))}
      </div>
      {reviewing && (
        <div className="mt-4 flex justify-end">
          <Button disabled={disabled || blank} onClick={() => onReview(edits)}>OK</Button>
        </div>
      )}
    </div>
  );
}
