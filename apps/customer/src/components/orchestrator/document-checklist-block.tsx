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

  const canUpload = (docType: string) => {
    return (
      awaiting.kind === "document" &&
      awaiting.document_types?.includes(docType)
    );
  };

  const anyUpload = block.items.some(
    (item) =>
      canUpload(item.doc_type) &&
      (item.status === "requested" || item.status === "rejected")
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
        const uploadEnabled = canUpload(item.doc_type);

        return (
          <div
            key={item.doc_type}
            className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3"
          >
            <span
              className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${
                isAccepted
                  ? "bg-emerald-50 text-emerald-600"
                  : isRejected
                    ? "bg-red-50 text-red-600"
                    : "bg-slate-50 text-slate-400"
              }`}
            >
              <FileText className="size-5" strokeWidth={1.6} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold">{item.label}</p>
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
            </div>
            {isAccepted && <CircleCheck className="size-4 text-emerald-500" />}
            {isRejected && <XCircle className="size-4 text-red-500" />}
            {uploadEnabled && (isRequested || isRejected) && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() =>
                    fileInputRefs.current[item.doc_type]?.click()
                  }
                >
                  <UploadCloud />
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
            {!isAccepted && !uploadEnabled && (
              <Pill tone="slate">Pending</Pill>
            )}
          </div>
        );
      })}
    </div>
  );
}
