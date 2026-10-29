"use client";

import { useRef, useState } from "react";
import { Check, FileQuestion, X } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import type { DocumentKind, LoanApplication } from "@banking/demo/types";
import type { ReviewInput } from "@banking/demo/schemas";
import { documentLabels } from "@banking/demo/format";
import { reviewSchema } from "@banking/demo/schemas";
import { Button } from "@banking/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { InfoNote, Panel } from "@banking/ui/primitives";

export function ReviewActions({ application, evidenceInspected }: { application: LoanApplication; evidenceInspected: boolean }) {
  const { command, busy } = useDemo();
  const [action, setAction] = useState<ReviewInput["action"] | null>(null);
  const [reason, setReason] = useState("");
  const [document, setDocument] = useState<DocumentKind>("statement");
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ fingerprint: string; key: string } | null>(null);
  const allowed = application.status === "PENDING_HUMAN_REVIEW";
  const labels = { approve: "Approve demo application", reject: "Reject demo application", "request-information": "Request more information" };
  async function record() {
    if (!action) return;
    const payload = { action, reason, evidenceReviewed: confirmed && evidenceInspected, ...(action === "request-information" ? { requestedDocument: document } : {}) };
    const fingerprint = JSON.stringify(payload);
    if (key.current?.fingerprint !== fingerprint) key.current = { fingerprint, key: crypto.randomUUID() };
    const input = reviewSchema.safeParse({ ...payload, idempotencyKey: key.current.key });
    if (!input.success) { setError(input.error.issues[0]?.message ?? "Check the decision details."); return; }
    try { await command(`/applications/${application.id}/review`, input.data); setAction(null); key.current = null; }
    catch (e) { setError(e instanceof Error ? e.message : "Could not record the outcome."); }
  }
  const open = (next: ReviewInput["action"]) => { setAction(next); setReason(""); setConfirmed(false); setError(null); };
  return <><Panel><h2 className="mb-3 text-sm font-semibold">Your independent decision</h2><p className="mb-4 text-xs leading-relaxed text-slate-500">No action is preselected. Inspect the customer data, evidence, configured rules and policy references before choosing an outcome.</p>{!allowed ? <InfoNote>This case is not pending review. The recorded status must permit an action; drafts and completed cases cannot receive a decision.</InfoNote> : <><div className="space-y-2"><Button variant="outline" className="w-full justify-start" disabled={!evidenceInspected || busy} onClick={() => open("request-information")}><FileQuestion className="text-amber-600" />Request more information</Button><Button variant="outline" className="w-full justify-start" disabled={!evidenceInspected || busy} onClick={() => open("approve")}><Check className="text-emerald-600" />Approve demo application</Button><Button variant="outline" className="w-full justify-start" disabled={!evidenceInspected || busy} onClick={() => open("reject")}><X className="text-red-500" />Reject demo application</Button></div>{!evidenceInspected && <p className="mt-3 text-[10px] text-slate-400">Open the evidence tab and confirm independent inspection to enable these actions.</p>}</>}</Panel>
    <Dialog open={Boolean(action)} onOpenChange={(opened) => { if (!opened) setAction(null); }}><DialogContent><DialogHeader><DialogTitle>{action ? labels[action] : "Record decision"}</DialogTitle><DialogDescription>{application.reference} · A justified, assigned human action is required. This records a synthetic outcome only.</DialogDescription></DialogHeader>{action === "request-information" && <div><label className="field-label" htmlFor="requested-document">Document to request</label><select className="field" id="requested-document" value={document} onChange={(e) => setDocument(e.target.value as DocumentKind)}>{Object.entries(documentLabels).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></div>}<div><label htmlFor="review-reason" className="field-label">{action === "request-information" ? "What clarification is needed, and why?" : "Decision justification"}</label><textarea className="field min-h-28" id="review-reason" placeholder="Describe the evidence and reason in your own words…" minLength={10} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /><p className="mt-2 text-[10px] text-slate-400">At least 10 characters. This reason is shared with the synthetic customer and recorded in history.</p></div><label className="flex items-start gap-3 text-xs leading-relaxed text-slate-600"><input type="checkbox" aria-label="Confirm independent evidence review" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5 size-4 shrink-0" />I independently assessed the available synthetic evidence and understand that format acceptance is not authenticity verification.</label><InfoNote warning>Approval is separate from signing and funding. No real loan is approved, no contract is signed, and no money is transferred.</InfoNote>{error && <p role="alert" className="text-xs text-red-600">{error}</p>}<DialogFooter><Button variant="outline" onClick={() => setAction(null)}>Cancel</Button><Button disabled={!confirmed || reason.trim().length < 10 || busy} onClick={() => { void record(); }}>Record demo {action === "request-information" ? "information request" : "decision"}</Button></DialogFooter></DialogContent></Dialog></>;
}
