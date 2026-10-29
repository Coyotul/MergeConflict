"use client";

import { useState } from "react";
import { decide, documentLabels, getReview, ReviewApiError, type RequestableDocument, type ReviewDetail } from "@banking/demo/review-api";
import { Button } from "@banking/ui/button";
import { InfoNote, Panel } from "@banking/ui/primitives";

const REQUESTABLE: RequestableDocument[] = ["id_card", "payslip", "bank_statement"];

export function ReviewActions({ detail, onDecided, onStale }: {
  detail: ReviewDetail; onDecided: (detail: ReviewDetail) => void; onStale: () => void;
}) {
  const required = new Set((detail.snapshot.application?.requirements?.documents ?? []).map((d: any) => d.doc_type));
  const types = REQUESTABLE.filter((t) => required.has(t));
  const [reason, setReason] = useState("");
  const [docType, setDocType] = useState<RequestableDocument>(types[0] ?? "payslip");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (detail.status !== "PENDING_HUMAN_REVIEW") {
    return <Panel><h2 className="mb-2 text-sm font-semibold">Decision</h2><p className="text-xs text-slate-500">
      {detail.status === "MORE_INFORMATION_REQUIRED" ? "Waiting for the customer to send the requested document." : `Recorded: ${detail.status_label}.`}
    </p></Panel>;
  }

  async function act(action: "approve" | "reject" | "request_document") {
    setBusy(true);
    setError(null);
    try {
      const body = action === "request_document"
        ? { action, reason, version: detail.version, doc_type: docType }
        : { action, reason, version: detail.version };
      await decide(detail.id, body);
      onDecided(await getReview(detail.id));
      setReason("");
    } catch (e) {
      if (e instanceof ReviewApiError && e.status === 409) { setError("This application changed; reloaded."); onStale(); }
      else setError(e instanceof Error ? e.message : "The decision could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const blank = !reason.trim();
  return (
    <Panel>
      <h2 className="mb-3 text-sm font-semibold">Your decision</h2>
      <label className="text-xs text-slate-500" htmlFor="reason">Reason (shown to the customer)</label>
      <textarea id="reason" className="field mt-1 min-h-24" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button disabled={busy || blank} onClick={() => act("approve")}>Approve</Button>
        <Button disabled={busy || blank} variant="outline" onClick={() => act("reject")}>Reject</Button>
      </div>
      <div className="mt-4 border-t border-slate-100 pt-4">
        <label className="text-xs text-slate-500" htmlFor="doc-type">Request a document</label>
        <select id="doc-type" className="field mt-1" value={docType} onChange={(e) => setDocType(e.target.value as RequestableDocument)}>
          {types.map((t) => <option key={t} value={t}>{documentLabels[t]}</option>)}
        </select>
        <Button className="mt-2 w-full" variant="secondary" disabled={busy || blank || !types.length} onClick={() => act("request_document")}>Request document</Button>
      </div>
      {error && <div className="mt-3"><InfoNote warning>{error}</InfoNote></div>}
    </Panel>
  );
}
