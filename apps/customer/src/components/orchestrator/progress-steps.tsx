"use client";

import { Check } from "lucide-react";
import type { Progress } from "@banking/demo/orchestrator";
import { stepLabel, stepStatusText } from "@banking/demo/orchestrator-labels";
import { Pill } from "@banking/ui/primitives";

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
      <section aria-label="Application progress" className="mb-6">
        <Pill tone={sideStage === "not_eligible" ? "red" : "amber"}>
          {SIDE_STAGE_LABELS[sideStage]}
        </Pill>
      </section>
    );
  }

  return (
    <section aria-label="Application progress" className="mb-6">
      <ol className="flex flex-wrap items-center gap-2">
        {progress.steps.map((step, index) => {
          const label = stepLabel(step.stage);
          const isDone = step.status === "done";
          const isCurrent = step.status === "current";
          const isLast = index === progress.steps.length - 1;

          return (
            <li
              key={step.stage}
              className="flex items-center gap-2"
              aria-current={isCurrent ? "step" : undefined}
            >
              <div className="flex items-center gap-2">
                {isDone ? (
                  <span aria-hidden="true" className="flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
                    <Check className="size-3.5" strokeWidth={3} />
                  </span>
                ) : (
                  <span
                    aria-hidden="true"
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
                  <span className="sr-only"> ({stepStatusText(step.status)})</span>
                </span>
              </div>
              {!isLast && (
                <div
                  aria-hidden="true"
                  className={`h-px w-4 ${
                    isDone ? "bg-emerald-500" : "bg-slate-200"
                  }`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
