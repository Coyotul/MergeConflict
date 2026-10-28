"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, ClipboardList, Clock3, FileQuestion, Search, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { formatDate, formatMoney, statusLabels } from "@banking/demo/format";
import { EmptyState, InfoNote, PageHeading, Panel, StatusBadge } from "@banking/ui/primitives";

export default function QueuePage() {
  const { snapshot } = useDemo();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  if (!snapshot) return null;
  const apps = snapshot.applications;
  const filtered = apps.filter((app) => (status === "all" || app.status === status) && `${app.reference} ${app.customer.name} ${snapshot.products.find((p) => p.id === app.productId)?.name}`.toLowerCase().includes(search.toLowerCase()));
  const metrics = [
    { label: "Assigned applications", value: apps.length, icon: ClipboardList, color: "text-brand-ink bg-brand-soft" },
    { label: "Awaiting your review", value: apps.filter((a) => a.status === "PENDING_HUMAN_REVIEW").length, icon: Clock3, color: "text-brand-ink bg-brand-soft" },
    { label: "Information requested", value: apps.filter((a) => a.status === "MORE_INFORMATION_REQUIRED").length, icon: FileQuestion, color: "text-amber-600 bg-amber-50" },
    { label: "Recorded demo outcomes", value: apps.filter((a) => ["APPROVED", "REJECTED"].includes(a.status)).length, icon: ShieldCheck, color: "text-emerald-600 bg-emerald-50" },
  ];
  return <div className="mx-auto max-w-7xl"><PageHeading eyebrow="Independent human review" title="Your application queue." description="Inspect the underlying evidence, not just the generated summary. All cases, document statuses and decisions in this workspace are synthetic." /><div className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(({ label, value, icon: Icon, color }) => <Panel key={label}><div className="flex items-center justify-between"><p className="text-xs text-slate-500">{label}</p><span className={`rounded-xl p-2 ${color}`}><Icon className="size-4" /></span></div><p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p></Panel>)}</div><div className="mb-6"><InfoNote>Preliminary affordability is not a credit decision. Format-accepted document metadata does not establish authenticity or income verification. Approval never implies a signed contract or disbursement.</InfoNote></div><div className="mb-4 flex flex-wrap justify-between gap-4"><div className="relative w-full max-w-sm"><Search className="absolute left-3 top-3.5 size-4 text-slate-400" /><input aria-label="Search application queue" className="field pl-10" placeholder="Search customer, reference or product…" value={search} onChange={(e) => setSearch(e.target.value)} /></div><select aria-label="Filter application status" className="field w-auto min-w-48" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">All assigned statuses</option>{Object.entries(statusLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></div>{filtered.length ? <div className="table-wrap bg-white"><table className="data-table"><thead><tr><th>Application / customer</th><th>Product</th><th>Amount</th><th>Duration</th><th>Status</th><th>Updated</th><th aria-label="Open application" /></tr></thead><tbody>{filtered.map((app) => <tr key={app.id}><td><Link href={`/applications/${app.id}`} className="font-semibold text-brand-ink hover:underline">{app.reference}</Link><p className="mt-1 text-xs text-slate-500">{app.customer.name}</p></td><td>{snapshot.products.find((p) => p.id === app.productId)?.name}</td><td className="font-semibold">{formatMoney(app.amount, 0)}</td><td>{app.months} months</td><td><StatusBadge status={app.status} label={statusLabels[app.status]} /></td><td className="text-xs text-slate-400">{formatDate(app.updatedAt)}</td><td><Link href={`/applications/${app.id}`} aria-label={`Review ${app.reference}`} className="inline-flex items-center gap-1 text-xs font-semibold text-brand-ink">Review<ArrowUpRight className="size-3.5" /></Link></td></tr>)}</tbody></table></div> : <EmptyState title="No matching assigned applications.">Try a different search or status filter.</EmptyState>}<p className="mt-4 text-[10px] text-slate-400">Only cases assigned to this synthetic reviewer are visible. New customer drafts appear here but cannot receive a decision until explicitly submitted.</p></div>;
}
