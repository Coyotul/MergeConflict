"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { formatMoney, statusLabels } from "@banking/demo/format";
import { EmptyState, InfoNote, Panel, Pill, StatusBadge } from "@banking/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@banking/ui/tabs";
import { EvidencePanel } from "./evidence-panel";
import { ReviewActions } from "./review-actions";
import { ApplicationHistory, FinancialOverview, PolicyReferences, ReviewerNotes } from "./review-detail-sections";

export function ReviewDetail({ id }: { id: string }) {
  const { snapshot } = useDemo();
  const [inspected, setInspected] = useState(false);
  if (!snapshot) return null;
  const app = snapshot.applications.find((a) => a.id === id);
  if (!app) return <EmptyState title="Application not found or not assigned to you."><Link href="/" className="text-brand-ink">Return to your assigned queue.</Link></EmptyState>;
  const product = snapshot.products.find((p) => p.id === app.productId);
  return <div className="mx-auto max-w-7xl"><Link href="/" className="mb-6 inline-flex items-center gap-2 text-xs font-semibold text-slate-500 hover:text-brand-ink"><ArrowLeft className="size-4" />Back to application queue</Link><div className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-ink">{app.reference} · assigned to you</p><h1 className="text-3xl font-semibold tracking-tight">{app.customer.name}</h1><p className="mt-2 text-sm text-slate-500">{product?.name} · {formatMoney(app.amount, 0)} · {app.months} months</p></div><StatusBadge status={app.status} label={statusLabels[app.status]} /></div><div className="mb-6"><InfoNote warning>Independent review is mandatory. The generated summary below is an organizational aid, not a recommendation or evidence. All customer values and decisions are synthetic.</InfoNote></div><div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_315px]"><div className="min-w-0"><Tabs defaultValue="overview"><TabsList aria-label="Application evidence tabs"><TabsTrigger value="overview">Profile & calculations</TabsTrigger><TabsTrigger value="evidence">Documents & evidence</TabsTrigger><TabsTrigger value="policies">Policy sources</TabsTrigger><TabsTrigger value="history">History</TabsTrigger></TabsList><TabsContent value="overview"><FinancialOverview application={app} /></TabsContent><TabsContent value="evidence" forceMount className="data-[state=inactive]:hidden"><EvidencePanel application={app} onInspected={setInspected} /></TabsContent><TabsContent value="policies"><PolicyReferences policies={snapshot.policies.filter((p) => p.id === product?.policyId)} /></TabsContent><TabsContent value="history"><ApplicationHistory application={app} /></TabsContent></Tabs></div><aside className="space-y-5"><Panel className="border-brand-border/35 bg-brand-soft/30"><div className="mb-4 flex items-center gap-2"><Sparkles className="size-4 text-ink" /><h2 className="text-sm font-semibold">Generated demo summary</h2></div><Pill tone="brand">Template-generated · not AI evidence</Pill><p className="mt-4 text-xs leading-relaxed text-slate-600">Customer requests {formatMoney(app.amount, 0)} over {app.months} months. The indicative payment is {formatMoney(app.quote.monthlyPayment)}. {app.documents.filter((d) => d.status === "FORMAT_ACCEPTED").length} document metadata records are format-accepted, with no authenticity verification.</p><p className="mt-3 text-[10px] leading-relaxed text-slate-400">Use the profile, document metadata, calculation assumptions and policy references to form your own judgment. No approval recommendation is provided.</p></Panel><ReviewActions application={app} evidenceInspected={inspected} /><ReviewerNotes application={app} /></aside></div></div>;
}
