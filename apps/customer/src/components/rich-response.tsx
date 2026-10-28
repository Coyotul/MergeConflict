"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, LifeBuoy } from "lucide-react";
import type { ChatMessage } from "@banking/demo/types";
import { useDemo } from "@banking/demo/react";
import { InfoNote } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";
import { GuidedOptions } from "./guided-options";
import { LoanSimulator } from "./loan-simulator";
import { RepaymentSimulator } from "./repayment-simulator";
import { RefinanceSimulator } from "./refinance-simulator";
import { LoanDetails } from "./loan-details";
import { ApplicationCard } from "./application-card";
import { Sources } from "./sources";

export function RichResponse({ message, onSelect }: { message: ChatMessage; onSelect: (text: string) => void }) {
  const { snapshot, busy, command } = useDemo();
  const [supportRequested, setSupportRequested] = useState(false);
  if (!snapshot) return null;
  const product = snapshot.products.find((p) => p.id === message.params?.productId);
  const active = snapshot.applications.find((a) => ["AWAITING_DOCUMENTS", "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION"].includes(a.status));
  return <div className="mt-4 space-y-4">
    {["options", "products", "modify"].includes(message.kind) && <GuidedOptions kind={message.kind} products={snapshot.products} onSelect={onSelect} disabled={busy} />}
    {message.kind === "loan" && product && <LoanSimulator product={product} initialAmount={message.params?.amount} initialMonths={message.params?.months} />}
    {message.kind === "repayment" && <RepaymentSimulator />}
    {message.kind === "refinance" && <RefinanceSimulator />}
    {message.kind === "loan-details" && <><LoanDetails /><GuidedOptions kind="loan-details" products={snapshot.products} onSelect={onSelect} disabled={busy} /></>}
    {message.kind === "documents" && (active ? <ApplicationCard application={active} /> : <InfoNote>There is no application currently awaiting documents. Choose a loan scenario first, or open your existing application.<Link href="/applications" className="ml-1 font-semibold text-brand-ink">View applications</Link></InfoNote>)}
    {message.kind === "applications" && <><div className="space-y-3">{snapshot.applications.slice(0, 2).map((app) => <ApplicationCard key={app.id} application={app} />)}</div><Button variant="outline" asChild><Link href="/applications">See all applications & history<ArrowUpRight /></Link></Button></>}
    {message.kind === "support" && <div className="space-y-3 rounded-2xl border border-brand-border/35 bg-white p-5"><LifeBuoy className="size-7 text-ink" /><h3 className="text-sm font-semibold">A human perspective can help.</h3><p className="text-xs leading-relaxed text-slate-500">Record a simulated handoff with your saved conversation and application context. The local reviewer demo is available, but no real bank employee is online.</p><Button disabled={busy || supportRequested} onClick={() => { void command("/support", { message: "I would like human assistance with my synthetic credit journey. Please retain my conversation context." }).then(() => setSupportRequested(true)).catch(() => {}); }}>{supportRequested ? "Demo handoff recorded" : "Confirm demo support request"}</Button></div>}
    {message.kind === "contract" && <InfoNote>For actual contract questions, the future contract-processing service must cite the uploaded agreement’s specific clauses. Do not upload a real agreement into this demo. A full payoff amount must come from an authorized banking service.</InfoNote>}
    <Sources sources={snapshot.policies.filter((s) => message.sources?.includes(s.id))} />
  </div>;
}
