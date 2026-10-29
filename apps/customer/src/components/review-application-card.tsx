"use client";

import { useState } from "react";
import { CircleCheck, Upload } from "lucide-react";
import { formatDate, formatMoney } from "@banking/demo/format";
import { documentLabels, uploadRequested, type CustomerApplication } from "@banking/demo/review-api";
import { Button } from "@banking/ui/button";
import { InfoNote, Metric, Panel, StatusBadge } from "@banking/ui/primitives";

const money = (value: string | number | null) => (value == null ? "—" : formatMoney(Number(value), 2));

export function ReviewApplicationCard({ application, customerId, onChange }: {
  application: CustomerApplication; customerId: string; onChange: () => void;
}) {
  const request = application.open_request;
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ accepted: boolean; reasons: string[] } | null>(null);

  async function send() {
    if (!request || !file) return;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await uploadRequested(customerId, application.id, request.id, file);
      setFeedback({ accepted: result.accepted, reasons: result.reasons });
      if (result.accepted) setFile(null);
      onChange();
    } catch (e) {
      setFeedback({ accepted: false, reasons: [e instanceof Error ? e.message : "Upload failed."] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid={`application-${application.reference}`} className="grid items-start gap-5 xl:grid-cols-[1.25fr_1fr]">
      <Panel>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-slate-500">{application.reference}</p>
            <h2 className="mt-1 font-semibold">Personal loan application</h2>
          </div>
          <StatusBadge status={application.status} label={application.status_label} />
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Amount" value={money(application.amount)} />
          <Metric label="Term" value={application.term_months ? `${application.term_months} months` : "—"} />
          <Metric label="Monthly installment" value={money(application.monthly_installment)} />
          <Metric label="Total cost" value={money(application.total_cost)} />
        </div>
        {application.offer_updated && <p className="mt-3 text-[11px] text-slate-500">Offer terms updated after review of your new document.</p>}
        {request && (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
            <p className="text-sm font-semibold">{documentLabels[request.doc_type]} requested</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">{request.reason}</p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input aria-label={`Upload ${documentLabels[request.doc_type]}`} type="file" accept="application/pdf,image/png,image/jpeg"
                     className="text-xs" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setFeedback(null); }} />
              <Button size="sm" disabled={!file || busy} onClick={send}><Upload />{busy ? "Checking…" : "Send document"}</Button>
            </div>
          </div>
        )}
        {feedback && (
          <div className="mt-3">
            <InfoNote warning={!feedback.accepted}>
              {feedback.accepted ? "Document accepted. Your application is back with the reviewer." : (
                <><p className="font-semibold">We couldn't accept this document.</p><ul className="mt-1 list-disc pl-4">{feedback.reasons.map((r) => <li key={r}>{r}</li>)}</ul></>
              )}
            </InfoNote>
          </div>
        )}
        <p className="mt-5 text-[10px] text-slate-400">Every credit decision is made by a human reviewer. Synthetic demo: nothing is signed or funded.</p>
      </Panel>
      <Panel>
        <h2 className="mb-5 text-sm font-semibold">Application timeline</h2>
        <ol>
          {application.history.map((entry, index) => (
            <li key={`${entry.at}-${index}`} className="relative flex gap-3 pb-5 last:pb-0">
              {index !== application.history.length - 1 && <span className="absolute left-[9px] top-5 h-[calc(100%-12px)] w-px bg-slate-200" />}
              <CircleCheck className="relative mt-0.5 size-5 shrink-0 text-ink" />
              <div>
                <p className="text-xs font-semibold">{entry.status_label}</p>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">{entry.reason}</p>
                <p className="mt-2 text-[10px] text-slate-400">{formatDate(entry.at, true)}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}
