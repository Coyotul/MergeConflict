"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, ClipboardList, Clock3, FileQuestion, Search, ShieldCheck } from "lucide-react";
import { formatDate, formatMoney } from "@banking/demo/format";
import { useReviewQueue } from "@banking/demo/review-react";
import { EmptyState, InfoNote, PageHeading, Panel, StatusBadge } from "@banking/ui/primitives";

const STATUSES = [
  ["PENDING_HUMAN_REVIEW", "Waiting for review"], ["MORE_INFORMATION_REQUIRED", "More information needed"],
  ["APPROVED", "Accepted"], ["REJECTED", "Rejected"],
] as const;

export default function QueuePage() {
  const { queue, error } = useReviewQueue();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const apps = queue ?? [];
  const filtered = apps.filter((app) => (status === "all" || app.status === status)
    && `${app.reference} ${app.customer_name ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  const metrics = [
    { label: "Submitted applications", value: apps.length, icon: ClipboardList, color: "text-brand-ink bg-brand-soft" },
    { label: "Waiting for review", value: apps.filter((a) => a.status === "PENDING_HUMAN_REVIEW").length, icon: Clock3, color: "text-brand-ink bg-brand-soft" },
    { label: "More information needed", value: apps.filter((a) => a.status === "MORE_INFORMATION_REQUIRED").length, icon: FileQuestion, color: "text-amber-600 bg-amber-50" },
    { label: "Decided", value: apps.filter((a) => ["APPROVED", "REJECTED"].includes(a.status)).length, icon: ShieldCheck, color: "text-emerald-600 bg-emerald-50" },
  ];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeading eyebrow="Independent human review" title="Your application queue."
        description="Every application submitted through the assistant waits here for a human decision. All cases are synthetic." />
      <div className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map(({ label, value, icon: Icon, color }) => (
          <Panel key={label}>
            <div className="flex items-center justify-between"><p className="text-xs text-slate-500">{label}</p><span className={`rounded-xl p-2 ${color}`}><Icon className="size-4" /></span></div>
            <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
          </Panel>
        ))}
      </div>
      {error && <div className="mb-6"><InfoNote warning>{error}</InfoNote></div>}
      <div className="mb-4 flex flex-wrap justify-between gap-4">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-3.5 size-4 text-slate-400" />
          <input aria-label="Search application queue" className="field pl-10" placeholder="Search customer or reference…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select aria-label="Filter application status" className="field w-auto min-w-48" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All statuses</option>
          {STATUSES.map(([key, label]) => <option value={key} key={key}>{label}</option>)}
        </select>
      </div>
      {filtered.length ? (
        <div className="table-wrap bg-white">
          <table className="data-table">
            <thead><tr><th>Application / customer</th><th>Amount</th><th>Status</th><th>Updated</th><th aria-label="Open application" /></tr></thead>
            <tbody>
              {filtered.map((app) => (
                <tr key={app.id}>
                  <td><Link href={`/applications/${app.id}`} className="font-semibold text-brand-ink hover:underline">{app.reference}</Link><p className="mt-1 text-xs text-slate-500">{app.customer_name}</p></td>
                  <td className="font-semibold">{app.amount != null ? formatMoney(Number(app.amount), 0) : "—"}</td>
                  <td><StatusBadge status={app.status} label={app.status_label} /></td>
                  <td className="text-xs text-slate-400">{formatDate(app.updated_at)}</td>
                  <td><Link href={`/applications/${app.id}`} aria-label={`Review ${app.reference}`} className="inline-flex items-center gap-1 text-xs font-semibold text-brand-ink">Review<ArrowUpRight className="size-3.5" /></Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState title="No matching applications.">Applications appear here once a customer submits through the assistant.</EmptyState>}
    </div>
  );
}
