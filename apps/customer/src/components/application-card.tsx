"use client";

import { useRef, useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import type { LoanApplication } from "@banking/demo/types";
import { formatMoney, statusLabels } from "@banking/demo/format";
import { Button } from "@banking/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { InfoNote, Metric, StatusBadge } from "@banking/ui/primitives";
import { DocumentChecklist } from "./document-checklist";

export function ApplicationCard({ application, expanded = false }: { application: LoanApplication; expanded?: boolean }) {
  const { snapshot, command, busy } = useDemo();
  const [confirm, setConfirm] = useState(false);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const product = snapshot?.products.find((p) => p.id === application.productId);
  async function submit() {
    key.current ??= crypto.randomUUID();
    try { await command(`/applications/${application.id}/submit`, { confirmed: checked, idempotencyKey: key.current }); setConfirm(false); key.current = null; }
    catch (e) { setError(e instanceof Error ? e.message : "Submission failed."); }
  }
  return <div className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{application.reference} · {product?.name}</p><h3 className="mt-1.5 text-xl font-semibold tracking-tight">{formatMoney(application.amount, 0)}</h3><p className="mt-1 text-xs text-slate-500">{application.months} months · {formatMoney(application.quote.monthlyPayment)} / month</p></div><StatusBadge status={application.status} label={statusLabels[application.status]} /></div>
    {expanded && <div className="mt-4 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4"><Metric label="Fixed nominal interest" value={`${application.quote.annualRate}%`} /><Metric label="Total repayment" value={formatMoney(application.quote.totalCost)} /></div>}
    <div className="mt-5"><DocumentChecklist application={application} /></div>
    {application.status === "READY_FOR_SUBMISSION" && <Button className="mt-4 w-full" disabled={busy} onClick={() => { setConfirm(true); setChecked(false); setError(null); }}>Review & submit<ArrowRight /></Button>}
    {application.status === "PENDING_HUMAN_REVIEW" && <div className="mt-4"><InfoNote><ShieldCheck className="mr-1 inline size-3.5" />Waiting for an independent demo reviewer. No approval, signature or transfer has occurred.</InfoNote></div>}
    {application.decisionReason && <div className="mt-4"><InfoNote warning={application.status === "REJECTED"}><strong>Recorded human outcome:</strong> {application.decisionReason} This is a demo decision only; nothing has been signed or funded.</InfoNote></div>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>Ready to send for human review?</DialogTitle><DialogDescription>Check your scenario before explicitly submitting this synthetic application.</DialogDescription></DialogHeader><div className="grid grid-cols-2 gap-5 rounded-2xl bg-slate-50 p-5"><Metric label="Amount" value={formatMoney(application.amount, 0)} /><Metric label="Duration" value={`${application.months} months`} /><Metric label="Monthly payment" value={formatMoney(application.quote.monthlyPayment)} /><Metric label="Total repayment" value={formatMoney(application.quote.totalCost)} /></div><InfoNote>Submitting does not approve a loan. An assigned human reviewer must independently assess the synthetic evidence. Contract signing and disbursement are separate and unavailable here.</InfoNote><label className="flex items-start gap-3 text-xs leading-relaxed text-slate-600"><input type="checkbox" aria-label="Confirm demo application submission" className="mt-0.5 size-4" checked={checked} onChange={(e) => setChecked(e.target.checked)} />I have reviewed the information and explicitly confirm submitting this demo application for human review.</label>{error && <p role="alert" className="text-xs text-red-600">{error}</p>}<DialogFooter><Button variant="outline" onClick={() => setConfirm(false)}>Keep as draft</Button><Button disabled={!checked || busy} onClick={() => { void submit(); }}>Confirm submission</Button></DialogFooter></DialogContent></Dialog>
  </div>;
}
