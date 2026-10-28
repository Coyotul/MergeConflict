"use client";

import { FileText } from "lucide-react";
import type { ExtractedFieldsBlock } from "@banking/demo/orchestrator";
import { Button } from "@banking/ui/button";

export function ExtractedFieldsBlockComponent({
  block,
  onSend,
  disabled,
}: {
  block: ExtractedFieldsBlock;
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="mt-4 space-y-3">
      {block.fields.map((field, index) => {
        const hasConflict = Boolean(field.conflict_with);
        const needsConfirmation = field.needs_confirmation;

        return (
          <div
            key={index}
            className={`rounded-xl border ${
              hasConflict || needsConfirmation
                ? "border-amber-200 bg-amber-50"
                : "border-slate-200 bg-white"
            } p-4`}
          >
            <div className="mb-2 flex items-start justify-between gap-3">
              <div className="flex-1">
                <p className="text-xs font-semibold text-ink">{field.label}</p>
                <p className="mt-1 text-sm text-slate-700">{field.value}</p>
              </div>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
              <FileText className="size-3" />
              <span>
                {field.source}
                {field.confidence !== null &&
                  field.confidence !== undefined &&
                  ` · ${Math.round(field.confidence * 100)}% confidence`}
              </span>
            </div>
            {hasConflict && (
              <div className="mt-3 flex flex-wrap gap-2">
                <p className="w-full text-xs text-amber-800">
                  Conflict with {field.conflict_with}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() => onSend("Yes, use the document value")}
                >
                  Use document value
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() => onSend("Use the other value")}
                >
                  Use other
                </Button>
              </div>
            )}
            {needsConfirmation && !hasConflict && (
              <div className="mt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() => onSend("Yes, that's correct")}
                >
                  Confirm
                </Button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
