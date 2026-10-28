"use client";

import { useState } from "react";
import { useDemo } from "@banking/demo/react";
import { formatDate } from "@banking/demo/format";
import { EmptyState, InfoNote, PageHeading, Pill } from "@banking/ui/primitives";

export default function AuditPage() {
  const { snapshot } = useDemo();
  const [search, setSearch] = useState("");
  if (!snapshot) return null;
  const events = [...snapshot.audit].reverse().filter((e) => `${e.actor} ${e.action} ${e.result}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="mx-auto max-w-7xl"><PageHeading eyebrow="Traceable human actions" title="Audit history." description="Actor, action, application, timestamp and result for cases assigned to this synthetic reviewer." /><div className="mb-6"><InfoNote>This local JSON audit is for demonstration, not tamper-proof production logging. Failed HTTP operations include a correlation ID; secure retention, monitoring and external log storage are deferred.</InfoNote></div><input aria-label="Search audit events" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search actor, action or result…" className="field mb-5 max-w-sm" />{events.length ? <div className="table-wrap bg-white"><table className="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Application</th><th>Result</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td className="text-xs text-slate-400">{formatDate(event.at, true)}</td><td>{event.actor}</td><td><Pill tone="slate">{event.action.replaceAll("_", " ")}</Pill></td><td className="text-xs">{snapshot.applications.find((a) => a.id === event.objectId)?.reference ?? event.objectId}</td><td className="max-w-sm whitespace-normal text-xs leading-relaxed text-slate-500">{event.result}</td></tr>)}</tbody></table></div> : <EmptyState title="No matching events yet.">Application commands and human review actions create recorded audit entries.</EmptyState>}</div>;
}
