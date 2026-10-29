"use client";

import { useRef } from "react";
import { CircleCheck, FileText, UploadCloud, XCircle } from "lucide-react";
import type {
  DocumentChecklistBlock,
  Awaiting,
} from "@banking/demo/orchestrator";
import { Button } from "@banking/ui/button";
import { Pill } from "@banking/ui/primitives";

export function DocumentChecklistBlockComponent({
  block,
  awaiting,
  onUpload,
  disabled,
}: {
  block: DocumentChecklistBlock;
  awaiting: Awaiting;
  onUpload: (docType: string, file: File) => void;
  disabled: boolean;
}) {
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Uploads open only when the assistant is waiting for documents, never while it asks something else.
  const anyUpload = awaiting.kind === "document" && block.items.some(
    (item) => item.status === "requested" || item.status === "rejected"
  );

  return (
    <div className="mt-4 space-y-2">
      {anyUpload && (
        <p className="text-[11px] text-slate-500">
          Use synthetic documents only — files are sent to the local assistant service.
        </p>
      )}
      {block.items.map((item) => {
        const isAccepted = item.status === "accepted";
        const isRejected = item.status === "rejected";
        const isRequested = item.status === "requested";
        const isAwaitingNow =
          awaiting.kind === "document" &&
          (awaiting.document_types?.includes(item.doc_type) ?? false);
        const canUploadNow = (isRequested || isRejected) && isAwaitingNow;

        return (
          <div
            key={item.doc_type}
            className={`flex flex-wrap items-center gap-3 rounded-xl border p-3 transition-colors ${
              isAwaitingNow
                ? "border-primary/60 bg-brand-soft/20 ring-1 ring-primary/40"
                : "border-slate-200 bg-white"
            }`}
          >
            <span
              className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${
                isAccepted
                  ? "bg-emerald-50 text-emerald-600"
                  : isRejected
                    ? "bg-red-50 text-red-600"
                    : isAwaitingNow
                      ? "bg-primary/20 text-ink"
                      : "bg-slate-50 text-slate-400"
              }`}
            >
              <FileText className="size-5" strokeWidth={1.6} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold">{item.label}</p>
                {isAwaitingNow && (
                  <Pill tone="amber" className="px-1.5 py-0 text-[9px]">
                    Required now
                  </Pill>
                )}
              </div>
              {isRejected && item.rejection_reason && (
                <p className="mt-1 text-[10px] text-red-600">
                  {item.rejection_reason}
                </p>
              )}
              {isAccepted && (
                <Pill tone="green" className="mt-1.5 px-2 py-0 text-[9px]">
                  Accepted
                </Pill>
              )}
              {isRequested && !isAwaitingNow && (
                <p className="mt-0.5 text-[10px] text-slate-400">
                  Needed later in the application
                </p>
              )}
            </div>
            {isAccepted && <CircleCheck className="size-4 text-emerald-500" />}
            {isRejected && <XCircle className="size-4 text-red-500" />}
            {canUploadNow && (
              <>
                <Button
                  variant={isAwaitingNow ? "default" : "secondary"}
                  size="sm"
                  disabled={disabled}
                  onClick={() =>
                    fileInputRefs.current[item.doc_type]?.click()
                  }
                >
                  <UploadCloud className="size-3.5" />
                  Upload {item.label}
                </Button>
                <input
                  ref={(el) => {
                    fileInputRefs.current[item.doc_type] = el;
                  }}
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      onUpload(item.doc_type, file);
                      if (e.target) {
                        e.target.value = "";
                      }
                    }
                  }}
                />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
