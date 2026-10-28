"use client";

import { Check } from "lucide-react";
import type { Progress } from "@banking/demo/orchestrator";
import { Pill } from "@banking/ui/primitives";

const STEP_LABELS: Record<string, string> = {
  discovery: "Discovery",
  details: "Your details",
  eligibility: "Eligibility",
  documents: "Documents",
  offers: "Offers",
  confirm: "Confirm",
  submitted: "Submitted",
};

const SIDE_STAGE_LABELS: Record<string, string> = {
  not_eligible: "Not eligible (preliminary)",
  manual_review: "Manual review",
  escalated: "With a human",
};

export function ProgressSteps({ progress }: { progress: Progress }) {
  if (progress.flow === "none") {
    return null;
  }

  const sideStage =
    progress.stage === "not_eligible" ||
    progress.stage === "manual_review" ||
    progress.stage === "escalated"
      ? progress.stage
      : null;

  if (sideStage) {
    return (
      <div aria-label="Application progress" className="mb-6">
        <Pill tone={sideStage === "not_eligible" ? "red" : "amber"}>
          {SIDE_STAGE_LABELS[sideStage]}
        </Pill>
      </div>
    );
  }

  return (
    <div aria-label="Application progress" className="mb-6">
      <div className="flex items-center gap-2">
        {progress.steps.map((step, index) => {
          const label = STEP_LABELS[step.stage] || step.stage;
          const isDone = step.status === "done";
          const isCurrent = step.status === "current";
          const isLast = index === progress.steps.length - 1;

          return (
            <div key={step.stage} className="flex items-center gap-2">
              <div className="flex items-center gap-2">
                {isDone ? (
                  <span className="flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
                    <Check className="size-3.5" strokeWidth={3} />
                  </span>
                ) : (
                  <span
                    className={`flex size-6 items-center justify-center rounded-full ${
                      isCurrent
                        ? "bg-ink text-white"
                        : "bg-slate-100 text-slate-400"
                    }`}
                  >
                    <span
                      className={`size-2 rounded-full ${
                        isCurrent ? "bg-white" : "bg-slate-300"
                      }`}
                    />
                  </span>
                )}
                <span
                  className={`text-xs font-medium ${
                    isDone || isCurrent ? "text-ink" : "text-slate-400"
                  }`}
                >
                  {label}
                </span>
              </div>
              {!isLast && (
                <div
                  className={`h-px w-4 ${
                    isDone ? "bg-emerald-500" : "bg-slate-200"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
