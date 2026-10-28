"use client";

import { useState } from "react";
import { CalendarDays, CircleCheck, FileText, UploadCloud } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import type { ApplicationDocument, DocumentKind, LoanApplication } from "@banking/demo/types";
import { documentLabels, formatDate } from "@banking/demo/format";
import { uploadSchema } from "@banking/demo/schemas";
import { Button } from "@banking/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { InfoNote, Pill } from "@banking/ui/primitives";

function DocumentRow({ document, canUpload, onUpload }: { document: ApplicationDocument; canUpload: boolean; onUpload: (kind: DocumentKind) => void }) {
  const present = document.status === "FORMAT_ACCEPTED";
  return <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3"><span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${present ? "bg-emerald-50 text-emerald-600" : "bg-slate-50 text-slate-400"}`}><FileText className="size-5" strokeWidth={1.6} /></span><div className="min-w-0 flex-1"><p className="text-xs font-semibold">{documentLabels[document.kind]}</p><p className="mt-1 truncate text-[10px] text-slate-400">{present ? document.name : "Synthetic PDF, JPG or PNG · max 10 MB"}</p>{present && <Pill tone="green" className="mt-1.5 px-2 py-0 text-[9px]">Format accepted · not verified</Pill>}</div>{present ? <CircleCheck className="size-4 text-emerald-500" /> : canUpload ? <Button variant="secondary" size="sm" onClick={() => onUpload(document.kind)}><UploadCloud />Add file</Button> : <Pill tone="amber">Missing</Pill>}</div>;
}
export function DocumentChecklist({ application }: { application: LoanApplication }) {
  const { command, busy } = useDemo();
  const [kind, setKind] = useState<DocumentKind | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canUpload = ["AWAITING_DOCUMENTS", "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION"].includes(application.status);
  const documents = application.documents.filter((d) => d.kind !== "statement" || application.requestedDocument === "statement" || d.status === "FORMAT_ACCEPTED");
  async function save() {
    if (!kind || !file) return;
    const input = { kind, name: file.name, mimeType: file.type, size: file.size, syntheticConfirmed: confirmed };
    const parsed = uploadSchema.safeParse(input);
    if (!parsed.success) { setError(parsed.error.issues[0]?.message ?? "Invalid file metadata."); return; }
    try { await command(`/applications/${application.id}/documents`, parsed.data); setKind(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not add metadata."); }
  }
  return <><div className="space-y-2">{application.requestReason && <InfoNote warning><strong>Reviewer request:</strong> {application.requestReason}</InfoNote>}{documents.map((d) => <DocumentRow key={d.kind} document={d} canUpload={canUpload} onUpload={(selected) => { setKind(selected); setFile(null); setConfirmed(false); setError(null); }} />)}</div><p className="mt-3 flex items-center gap-1.5 text-[10px] text-slate-400"><CalendarDays className="size-3" />Last updated {formatDate(application.updatedAt, true)}</p>
    <Dialog open={Boolean(kind)} onOpenChange={(open) => { if (!open) setKind(null); }}><DialogContent><DialogHeader><DialogTitle>Add {kind ? documentLabels[kind].toLowerCase() : "document"}</DialogTitle><DialogDescription>Choose a fabricated demo file. Only its filename, size and type are saved locally; the file contents are never uploaded.</DialogDescription></DialogHeader><label className="flex cursor-pointer flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-brand-border/60 bg-brand-soft/40 p-7 text-center"><UploadCloud className="size-8 text-ink" /><span className="text-sm font-semibold">{file?.name ?? "Choose a synthetic file"}</span><span className="text-xs text-slate-500">PDF, JPG or PNG · up to 10 MB</span><input aria-label="Synthetic document file" type="file" accept=".pdf,.jpg,.jpeg,.png" className="max-w-full text-xs" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }} /></label><label className="flex items-start gap-3 text-xs leading-relaxed text-slate-600"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5 size-4 shrink-0" />I confirm this is a synthetic document containing no real personal or financial data.</label><InfoNote>Format acceptance is not identity, income or authenticity verification. OCR and document processing are not connected.</InfoNote>{error && <p role="alert" className="text-xs text-red-600">{error}</p>}<DialogFooter><Button variant="outline" onClick={() => setKind(null)}>Cancel</Button><Button disabled={!file || !confirmed || busy} onClick={() => { void save(); }}>Save document metadata</Button></DialogFooter></DialogContent></Dialog></>;
}
