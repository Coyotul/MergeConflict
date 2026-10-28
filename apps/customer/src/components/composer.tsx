"use client";

import { useState } from "react";
import { CornerDownLeft, Paperclip, SendHorizontal } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { Button } from "@banking/ui/button";
import { ApplicationCard } from "./application-card";
import { useDemo } from "@banking/demo/react";

export function Composer({ onSend, disabled }: { onSend: (text: string) => Promise<boolean>; disabled: boolean }) {
  const [text, setText] = useState("");
  const [documents, setDocuments] = useState(false);
  const { snapshot } = useDemo();
  const active = snapshot?.applications.find((a) => ["AWAITING_DOCUMENTS", "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION"].includes(a.status));
  async function submit() { if (text.trim() && !disabled && await onSend(text.trim())) setText(""); }
  return <>
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }} className="flex items-end gap-3">
      <div className="flex min-w-0 flex-1 items-end rounded-[23px] border border-transparent bg-slate-100 px-3 py-2 focus-within:border-brand-border/60 focus-within:bg-white focus-within:ring-4 focus-within:ring-primary/20">
        <button type="button" disabled={disabled} onClick={() => setDocuments(true)} aria-label="Open document checklist" className="mb-1 rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-brand-ink"><Paperclip className="size-5" strokeWidth={1.7} /></button>
        <textarea aria-label="Message the assistant" placeholder="Tell me what's on your mind…" rows={1} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }} className="max-h-28 min-h-10 w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-slate-700 outline-none placeholder:text-slate-400 focus-visible:outline-none" />
        <span className="mb-3 mr-1 hidden text-slate-300 2xl:inline"><CornerDownLeft className="size-4" /></span>
      </div>
      <button type="submit" disabled={disabled || !text.trim()} aria-label="Send message" className="flex size-14 shrink-0 items-center justify-center rounded-full bg-primary text-ink shadow-lg shadow-black/10 transition-colors hover:bg-primary/80 disabled:opacity-40"><SendHorizontal className="size-6" strokeWidth={1.7} /></button>
    </form>
    <p className="mt-3 text-center text-[10px] text-slate-400">Your own words are always welcome. Enter to send · Shift + Enter for a new line.</p>
    <Dialog open={documents} onOpenChange={setDocuments}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>Your document checklist</DialogTitle><DialogDescription>Only synthetic file metadata is stored. No file contents are uploaded or verified.</DialogDescription></DialogHeader>{active ? <ApplicationCard application={active} /> : <div className="rounded-2xl bg-slate-50 p-5"><p className="text-sm font-semibold">No draft is waiting for documents.</p><p className="mt-2 text-xs leading-relaxed text-slate-500">Choose a loan scenario first. Documents belong to a specific application; never attach real banking files to the conversation.</p><Button variant="secondary" size="sm" className="mt-4" onClick={() => { setDocuments(false); void onSend("I want a loan"); }}>Explore a loan scenario</Button></div>}</DialogContent></Dialog>
  </>;
}
