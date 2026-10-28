"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { formatDate, statusLabels } from "@banking/demo/format";
import { Button } from "@banking/ui/button";
import { EmptyState, PageHeading, Panel } from "@banking/ui/primitives";
import { ApplicationCard } from "@/components/application-card";

export default function ApplicationsPage() {
  const { snapshot } = useDemo();
  const [filter, setFilter] = useState("all");
  if (!snapshot) return null;
  const apps = snapshot.applications.filter((a) => filter === "all" || (filter === "active" ? !["APPROVED", "REJECTED", "CANCELLED"].includes(a.status) : ["APPROVED", "REJECTED", "CANCELLED"].includes(a.status)));
  return <div className="mx-auto max-w-6xl"><PageHeading eyebrow="Every step, kept in view" title="Your applications." description="Resume where you left off. The application history survives refreshes and chat resets; each final demo credit decision belongs to a human reviewer." action={<Button asChild><Link href="/?topic=loan">Explore a new loan<ArrowRight /></Link></Button>} /><div className="mb-6 flex gap-2" role="group" aria-label="Filter applications">{["all", "active", "completed"].map((f) => <Button key={f} size="sm" variant={filter === f ? "default" : "outline"} onClick={() => setFilter(f)} aria-pressed={filter === f}>{f.charAt(0).toUpperCase() + f.slice(1)}</Button>)}</div>
    {apps.length ? <div className="space-y-7">{apps.map((app) => <div key={app.id} data-testid={`application-${app.reference}`} className="grid items-start gap-5 xl:grid-cols-[1.25fr_1fr]"><ApplicationCard application={app} expanded /><Panel><h2 className="mb-5 text-sm font-semibold">Application timeline</h2><ol className="space-y-0">{app.history.map((entry, index) => <li key={entry.id} className="relative flex gap-3 pb-5 last:pb-0">{index !== app.history.length - 1 && <span className="absolute left-[9px] top-5 h-[calc(100%-12px)] w-px bg-slate-200" />}<CircleCheck className="relative mt-0.5 size-5 shrink-0 text-ink" /><div><p className="text-xs font-semibold">{statusLabels[entry.status]}</p><p className="mt-1 text-xs leading-relaxed text-slate-500">{entry.description}</p><p className="mt-2 text-[10px] text-slate-400">{entry.actor} · {formatDate(entry.at, true)}</p></div></li>)}</ol>{app.notes.length > 0 && <div className="mt-6 border-t border-slate-100 pt-4"><h3 className="mb-3 text-xs font-semibold">Shared updates</h3>{app.notes.slice(-3).map((note) => <div key={note.id} className="mb-2 rounded-xl bg-slate-50 p-3"><p className="text-xs leading-relaxed text-slate-600">{note.text}</p><p className="mt-2 text-[10px] text-slate-400">{note.author} · {formatDate(note.at, true)}</p></div>)}</div>}</Panel></div>)}</div> : <EmptyState title="No applications in this view.">Choose another filter, or explore a new scenario with the assistant.</EmptyState>}
  </div>;
}
