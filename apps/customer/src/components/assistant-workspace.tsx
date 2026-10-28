"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, LoaderCircle, MessageCircle, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { AssistantAvatar, PilotNotice } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { StartingCards } from "./guided-options";
import { RichResponse } from "./rich-response";
import { Composer } from "./composer";
import { ContextPanel } from "./context-panel";

export function AssistantWorkspace() {
  const { snapshot, command, busy } = useDemo();
  const [ending, setEnding] = useState(false);
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const lock = useRef(false);
  const topicHandled = useRef(false);
  const count = snapshot?.messages.length ?? 0;
  const send = async (text: string) => {
    if (lock.current) return false;
    lock.current = true; setSending(true);
    try { await command("/chat", { text }); return true; }
    catch { return false; }
    finally { lock.current = false; setSending(false); }
  };
  useEffect(() => { if (count > 0) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [count]);
  useEffect(() => {
    if (topicHandled.current || !snapshot) return;
    topicHandled.current = true;
    const topic = new URLSearchParams(window.location.search).get("topic");
    if (topic) {
      const queries: Record<string, string> = { support: "I need human support", repayment: "I want to simulate early repayment", refinance: "I want to explore refinancing", loan: "I want a loan", modify: "Change my current loan", details: "My current loan details" };
      const text = queries[topic] ?? (topic === "personal" || topic === "mortgage" || topic === "car" ? `I want a ${topic === "mortgage" ? "mortgage" : `${topic} loan`}` : undefined);
      if (text) void command("/chat", { text }).catch(() => {});
      window.history.replaceState({}, "", "/");
    }
  }, [snapshot, command]);
  if (!snapshot) return null;
  const welcome = count === 0;
  const disabled = busy || sending;
  return <div className="flex min-h-0 flex-1"><div className="flex min-w-0 flex-1 flex-col"><div className="flex items-center justify-between px-7 pb-3 pt-6 lg:px-9"><div className="flex items-center gap-3"><AssistantAvatar small /><div><p className="text-sm font-semibold">Luma assistant</p><p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400"><span className="size-1 rounded-full bg-emerald-400" />Your financial companion · guided demo</p></div></div><Button variant="link" size="sm" disabled={disabled || welcome} onClick={() => setEnding(true)}>End chat</Button></div>
    <div className="conversation-scroll min-h-0 flex-1 overflow-y-auto px-7 py-5 lg:px-9">
      {welcome ? <div className="mx-auto flex max-w-[830px] flex-col pb-2"><div className="mb-8 mt-3"><p className="mb-3 text-xs font-medium text-slate-400">A little help. A lot more clarity.</p><h1 className="text-[clamp(32px,3.4vw,52px)] font-semibold leading-[1.18] tracking-[-0.045em] text-ink">Hey {snapshot.customer.name.split(" ")[0]},<br />how can I help you<br /><span className="greeting-highlight">today?</span><span className="blink-cursor" aria-hidden="true" /></h1><p className="mt-4 text-sm text-slate-500">Pick a starting point, or simply ask me.</p></div><StartingCards disabled={disabled} onSelect={(text) => { void send(text); }} /><div className="mt-6 flex items-center gap-2 text-[11px] text-slate-400"><MessageCircle className="size-3.5" />One conversation. Every step of your credit journey.</div></div> : <div className="mx-auto max-w-[780px] space-y-6"><p className="text-center text-[10px] font-medium text-slate-400">YOUR CONVERSATION · SAVED LOCALLY</p>{snapshot.messages.map((message) => message.role === "user" ? <div key={message.id} className="flex justify-end"><div className="max-w-[85%] rounded-[20px] rounded-br-md bg-ink px-5 py-3 text-sm leading-relaxed text-white shadow-sm">{message.text}</div></div> : <div key={message.id} className="flex gap-3"><AssistantAvatar small /><div className="min-w-0 flex-1 rounded-[20px] rounded-tl-md bg-slate-50 p-5"><p className="mb-2 text-[10px] font-semibold text-brand-ink">LUMA · DEMO ASSISTANT</p><p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{message.text}</p><RichResponse message={message} onSelect={(text) => { void send(text); }} /></div></div>)}</div>}
      {sending && <div role="status" className="mx-auto mt-6 flex max-w-[780px] items-center gap-2 text-xs text-slate-400"><LoaderCircle className="size-4 animate-spin" />Preparing a demo response…</div>}<div ref={bottom} />
    </div>
    <div className="shrink-0 bg-white px-7 pb-5 pt-3 lg:px-9"><div className="mx-auto max-w-[830px]">{welcome ? <div className="mb-5"><PilotNotice /></div> : <div className="mb-3 flex items-center justify-between gap-3"><Button variant="ghost" size="sm" disabled={disabled} onClick={() => { void send("Back to options"); }}><ChevronLeft />Back to options</Button><span className="flex items-center gap-1.5 text-[10px] text-slate-400"><ShieldCheck className="size-3.5" />Synthetic data · indicative results</span></div>}<Composer disabled={disabled} onSend={send} /></div></div>
  </div><ContextPanel /><Dialog open={ending} onOpenChange={setEnding}><DialogContent><DialogHeader><DialogTitle>Start a fresh conversation?</DialogTitle><DialogDescription>This clears only the chat. Your synthetic loan applications, documents and history remain saved locally.</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setEnding(false)}>Keep chatting</Button><Button disabled={busy} onClick={() => { void command("/chat/reset", {}).then(() => setEnding(false)).catch(() => {}); }}>End chat & start fresh</Button></DialogFooter></DialogContent></Dialog></div>;
}
