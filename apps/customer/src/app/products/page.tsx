"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { formatMoney } from "@banking/demo/format";
import { Illustration } from "@banking/ui/illustrations";
import { InfoNote, PageHeading, Pill } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";
import { LoanSimulator } from "@/components/loan-simulator";
import { Sources } from "@/components/sources";

export default function ProductsPage() {
  const { snapshot } = useDemo();
  const [selected, setSelected] = useState("personal");
  if (!snapshot) return null;
  const product = snapshot.products.find((p) => p.id === selected)!;
  return <div className="mx-auto max-w-6xl"><PageHeading eyebrow="Explore your possibilities" title="Big plans. Clear numbers." description="Choose a product and adjust its assumptions. These fictional demo terms are not bank offers." action={<Button variant="outline" asChild><Link href="/?topic=loan">Ask the assistant<ArrowRight /></Link></Button>} /><div className="mb-7 grid gap-4 md:grid-cols-3">{snapshot.products.map((p) => <button key={p.id} onClick={() => setSelected(p.id)} aria-pressed={selected === p.id} className={`rounded-2xl border-2 p-5 text-left transition-colors ${selected === p.id ? "border-ink bg-brand-soft/50" : "border-slate-200 bg-white hover:border-brand-border/60"}`}><div className="flex items-start justify-between"><Illustration kind={p.id === "mortgage" ? "home" : p.id === "car" ? "car" : "loan"} className="size-20" /><Pill tone={selected === p.id ? "brand" : "slate"}>{p.annualRate}% nominal</Pill></div><h2 className="mt-3 font-semibold">{p.name}</h2><p className="mt-2 text-xs leading-relaxed text-slate-500">{p.description}</p><p className="mt-4 text-[10px] text-slate-400">Up to {formatMoney(p.maxAmount, 0)} · {p.maxMonths} months</p></button>)}</div><div className="grid items-start gap-6 xl:grid-cols-[1.5fr_1fr]"><LoanSimulator key={product.id} product={product} /><section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="text-sm font-semibold">Before you choose</h2><InfoNote>Compare total repayment, not just the monthly amount. Check whether the scenario remains affordable if your income or expenses change.</InfoNote><ol className="space-y-4 text-xs leading-relaxed text-slate-500"><li><strong className="text-slate-700">1. Explore.</strong> Adjust amount and term. The calculator uses explicit synthetic rates, fees and insurance.</li><li><strong className="text-slate-700">2. Prepare.</strong> Save a draft and add fabricated document metadata.</li><li><strong className="text-slate-700">3. Confirm.</strong> Review the summary and explicitly submit for independent human review.</li><li><strong className="text-slate-700">4. Track.</strong> Follow information requests and the recorded demo outcome. Approval never implies signing or funding.</li></ol><Sources sources={snapshot.policies.filter((s) => s.id === product.policyId)} /></section></div></div>;
}
