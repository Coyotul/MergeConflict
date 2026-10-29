"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileText } from "lucide-react";
import { formatDate, formatMoney } from "@banking/demo/format";
import { documentLabels, getReview, openDocument, type ReviewDetail as Detail } from "@banking/demo/review-api";
import { Button } from "@banking/ui/button";
import { EmptyState, InfoNote, Panel, Pill, StatusBadge } from "@banking/ui/primitives";
import { ReviewActions } from "./review-actions";

type Fields = Record<string, { value: unknown; source?: string; confidence?: number | null; confirmed?: boolean }>;
const show = (v: unknown) => (v == null || v === "" ? "—" : String(v));
const money = (offer: any, key: string) => (offer?.[key]?.amount != null ? formatMoney(Number(offer[key].amount)) : "—");

function selectedOffer(application: any) {
  const offers = application?.offers?.offers ?? [];
  return offers.find((o: any) => o.offer_id === application?.selected_offer_id) ?? null;
}

export function ReviewDetail({ id }: { id: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => getReview(id).then(setDetail).catch((e) => setError(e.message)), [id]);
  useEffect(() => { load(); }, [load]);
  if (error) return <EmptyState title="Application not found.">{error} <Link href="/" className="text-brand-ink">Return to the queue.</Link></EmptyState>;
  if (!detail) return null;

  const original = detail.snapshot.application ?? {};
  const current = detail.current.application ?? original;
  const fields: Fields = current.fields ?? {};
  const changed = new Map(detail.changed_fields.map((c) => [c.field, c]));
  const originalOffer = selectedOffer(original);
  const currentOffer = detail.current.offer ?? null;
  const originalEligibility = original.eligibility?.result ?? null;
  const currentEligibility = detail.current.eligibility ?? null;

  return (
    <div className="mx-auto max-w-7xl">
      <Link href="/" className="mb-6 inline-flex items-center gap-2 text-xs font-semibold text-slate-500 hover:text-brand-ink"><ArrowLeft className="size-4" />Back to application queue</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-ink">{detail.reference}</p>
          <h1 className="text-3xl font-semibold tracking-tight">{show(detail.snapshot.profile?.full_name)}</h1>
          <p className="mt-2 text-sm text-slate-500">Personal loan · {show(fields.amount?.value)} RON · {show(fields.term_months?.value)} months</p>
        </div>
        <StatusBadge status={detail.status} label={detail.status_label} />
      </div>
      <div className="mb-6"><InfoNote warning>Only you decide this application. Every reason you enter is shown to the customer. All data is synthetic.</InfoNote></div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_330px]">
        <div className="min-w-0 space-y-6">
          <Panel>
            <h2 className="mb-4 text-sm font-semibold">Application fields</h2>
            <table className="data-table">
              <thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Confidence</th></tr></thead>
              <tbody>
                {Object.entries(fields).map(([name, f]) => {
                  const change = changed.get(name);
                  return (
                    <tr key={name} className={change ? "bg-amber-50" : undefined}>
                      <td className="text-xs font-semibold">{name}</td>
                      <td className="text-xs">{show(f.value)}{change && <span className="ml-2 text-amber-700">(was {show(change.before)})</span>}</td>
                      <td className="text-xs">{show(f.source)}</td>
                      <td className="text-xs">{f.confidence != null ? `${Math.round(Number(f.confidence) * 100)}%` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel>
              <h2 className="mb-3 text-sm font-semibold">Eligibility</h2>
              <p className="text-xs">Original: <Pill tone="slate">{show(originalEligibility?.status)}</Pill></p>
              {currentEligibility && <p className="mt-2 text-xs">After new documents: <Pill tone={currentEligibility.status === "satisfied" ? "green" : "amber"}>{show(currentEligibility.status)}</Pill></p>}
              <ul className="mt-3 list-disc pl-4 text-xs text-slate-600">{(currentEligibility ?? originalEligibility)?.reasons?.map((r: any, i: number) => <li key={i}>{r.message}</li>)}</ul>
            </Panel>
            <Panel>
              <h2 className="mb-3 text-sm font-semibold">Offer</h2>
              <table className="data-table">
                <thead><tr><th /><th>Original</th>{currentOffer && <th>Current</th>}</tr></thead>
                <tbody>
                  {[["Installment", "monthly_installment"], ["Total cost", "total_cost"], ["Total repayment", "total_repayment"]].map(([label, key]) => (
                    <tr key={key}><td className="text-xs">{label}</td><td className="text-xs">{money(originalOffer, key)}</td>{currentOffer && <td className="text-xs">{money(currentOffer, key)}</td>}</tr>
                  ))}
                </tbody>
              </table>
              {detail.current.pricing_errors?.length > 0 && <p className="mt-2 text-xs text-amber-700">{detail.current.pricing_errors.map((e: any) => e.message).join("; ")}</p>}
            </Panel>
          </div>
          <Panel>
            <h2 className="mb-4 text-sm font-semibold">Documents</h2>
            <div className="space-y-3">
              {detail.documents.map((d) => (
                <div key={d.document_id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3 text-xs">
                  <span><FileText className="mr-2 inline size-4" />{documentLabels[d.doc_type] ?? d.doc_type} · {d.filename} · {d.origin === "information_request" ? "requested" : "from chat"}{d.superseded_by && " · replaced"}</span>
                  <span className="flex items-center gap-2"><Pill tone="green">{d.status}</Pill><Button size="sm" variant="outline" onClick={() => openDocument(detail.id, d.document_id)}>Open</Button></span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <h2 className="mb-4 text-sm font-semibold">History</h2>
            <ol className="space-y-3">{detail.history.map((h, i) => <li key={i} className="text-xs"><span className="font-semibold">{h.to_status}</span> · {h.actor} · {formatDate(h.at, true)}<p className="text-slate-500">{h.reason}</p></li>)}</ol>
          </Panel>
        </div>
        <aside><ReviewActions detail={detail} onDecided={(d) => setDetail(d)} onStale={load} /></aside>
      </div>
    </div>
  );
}
