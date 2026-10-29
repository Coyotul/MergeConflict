"use client";

import { useState } from "react";
import { BookOpen, ChevronDown } from "lucide-react";
import type { PolicySource } from "@banking/demo/types";
import { formatDate } from "@banking/demo/format";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@banking/ui/dialog";

export function Sources({ sources }: { sources: PolicySource[] }) {
  const [selected, setSelected] = useState<PolicySource | null>(null);
  if (!sources.length) return null;
  return <><div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3"><span className="mr-1 text-[10px] text-slate-400">Demo sources</span>{sources.map((source) => <button key={source.id} onClick={() => setSelected(source)} className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-[10px] font-medium text-brand-ink ring-1 ring-slate-200 hover:bg-brand-soft"><BookOpen className="size-3" />{source.title.split(" · ")[0]}<ChevronDown className="size-3" /></button>)}</div><Dialog open={Boolean(selected)} onOpenChange={(open) => { if (!open) setSelected(null); }}><DialogContent><DialogHeader><DialogTitle>{selected?.title}</DialogTitle><DialogDescription>Fictional policy fixture · {selected?.version} · effective {selected ? formatDate(selected.effectiveDate) : ""}</DialogDescription></DialogHeader><p className="text-xs font-semibold text-brand-ink">{selected?.section}</p><p className="text-sm leading-relaxed text-slate-600">{selected?.content}</p><p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">This is not public bank documentation, real RAG retrieval or a legally binding product offer.</p></DialogContent></Dialog></>;
}
