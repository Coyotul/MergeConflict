"use client";

import { AlertCircle, CircleCheck, ShieldCheck } from "lucide-react";
import type {
  EligibilityResultBlock,
  ApplicationSubmittedBlock,
  EscalationBlock,
} from "@banking/demo/orchestrator";
import { humaniseStatus } from "@banking/demo/orchestrator-labels";
import { InfoNote, Pill } from "@banking/ui/primitives";

export function EligibilityResultBlock({
  block,
}: {
  block: EligibilityResultBlock;
}) {
  const { result } = block;
  const isSatisfied = result.status === "satisfied";
  const isNotSatisfied = result.status === "not_satisfied";

  return (
    <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-ink">Eligibility</p>
          <p className="mt-1 text-[10px] text-slate-400">
            Preliminary · simulated, based on public conditions
          </p>
        </div>
        <Pill tone={isSatisfied ? "green" : isNotSatisfied ? "red" : "amber"}>
          {result.status === "satisfied"
            ? "Satisfied"
            : result.status === "not_satisfied"
              ? "Not satisfied"
              : result.status === "manual_review"
                ? "Manual review"
                : "More information"}
        </Pill>
      </div>
      {result.reasons.length > 0 && (
        <div className="space-y-2">
          {result.reasons.map((reason, index) => (
            <div
              key={index}
              className="flex items-start gap-2 rounded-xl bg-slate-50 p-3"
            >
              {isSatisfied ? (
                <CircleCheck className="size-4 shrink-0 text-emerald-600" />
              ) : (
                <AlertCircle className="size-4 shrink-0 text-slate-500" />
              )}
              <p className="text-xs leading-relaxed text-slate-600">
                {reason.message}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ApplicationSubmittedBlock({
  block,
}: {
  block: ApplicationSubmittedBlock;
}) {
  return (
    <div className="mt-4">
      <InfoNote>
        <ShieldCheck className="mr-1 inline size-3.5" />
        <strong>
          Application {block.application_id} · {humaniseStatus(block.status)}
        </strong>
        <br />
        Submitted for human review — no decision yet.
      </InfoNote>
    </div>
  );
}

export function EscalationBlock({ block }: { block: EscalationBlock }) {
  return (
    <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-5">
      <div className="mb-2 flex items-center gap-2">
        <AlertCircle className="size-5 text-amber-800" />
        <p className="text-xs font-semibold text-amber-900">
          Please contact a bank representative
        </p>
      </div>
      <p className="text-xs leading-relaxed text-amber-800">{block.message}</p>
    </div>
  );
}
