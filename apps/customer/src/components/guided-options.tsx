"use client";

import { ArrowUpRight, Banknote, ChevronRight, CreditCard, FileText, House, RefreshCw, TrendingDown, Car } from "lucide-react";
import { Illustration } from "@banking/ui/illustrations";
import { cn } from "@banking/ui/utils";
import { Button } from "@banking/ui/button";
import type { MessageKind, Product } from "@banking/demo/types";

export const startingPoints = [
  { title: "I want a loan", subtitle: "Find the right fit for your next chapter", kind: "loan" as const, color: "bg-primary text-ink border-primary", query: "I want a loan" },
  { title: "Change my current loan", subtitle: "Explore repayment and refinancing", kind: "modify" as const, color: "bg-ink text-white border-ink", query: "Change my current loan" },
  { title: "My current loan details", subtitle: "Get a clearer picture of your credit", kind: "details" as const, color: "bg-brand-soft text-ink border-brand-border/35", query: "My current loan details" },
];

export function StartingCards({ onSelect, disabled, compact = false }: { onSelect: (text: string) => void; disabled: boolean; compact?: boolean }) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-3", compact ? "gap-2.5" : "gap-3 lg:gap-4")}>
      {startingPoints.map((card, index) => (
        <button
          key={card.title}
          disabled={disabled}
          onClick={() => onSelect(card.query)}
          className={cn(
            "guided-card flex flex-col rounded-[20px] border p-4 text-left transition-all disabled:opacity-60",
            card.color,
            compact ? "min-h-[135px]" : "min-h-[150px] lg:min-h-[175px] xl:min-h-[190px]"
          )}
        >
          <span className="mb-2 flex w-full items-start justify-between">
            <span
              className={cn(
                "flex items-center justify-center rounded-full",
                index === 1 ? "bg-white/10" : "bg-black/5",
                compact ? "size-11" : "size-12 lg:size-14"
              )}
            >
              <Illustration kind={card.kind} className={cn("illustration-float", compact ? "size-10" : "size-10 lg:size-12")} />
            </span>
            <ArrowUpRight className={cn("size-4 lg:size-5", index === 1 ? "text-primary" : "text-ink/70")} />
          </span>
          <span className={cn("mt-auto font-semibold leading-snug tracking-tight", index === 1 ? "text-white" : "text-ink", compact ? "text-sm" : "text-sm lg:text-base xl:text-lg")}>
            {card.title}
          </span>
          <span className={cn("mt-1 text-xs leading-relaxed", index === 1 ? "text-white/75" : "text-slate-600")}>
            {card.subtitle}
          </span>
          <span className="sr-only">Option {index + 1}</span>
        </button>
      ))}
    </div>
  );
}

export function GuidedOptions({ kind, products, onSelect, disabled }: { kind: MessageKind; products: Product[]; onSelect: (text: string) => void; disabled: boolean }) {
  if (kind === "options") return <StartingCards compact onSelect={onSelect} disabled={disabled} />;
  const options = kind === "products" ? products.map((p) => ({ title: p.name, description: p.description, icon: p.id === "mortgage" ? House : p.id === "car" ? Car : Banknote, query: `I want a ${p.name.toLowerCase()}` })) : kind === "modify" ? [
    { title: "Early repayment", description: "Pay a little extra. Compare the impact.", icon: TrendingDown, query: "I want to simulate early repayment" },
    { title: "Refinancing", description: "Compare one new loan with your current credit.", icon: RefreshCw, query: "I want to explore refinancing" },
    { title: "Lower my monthly payment", description: "See the trade-off between monthly and total cost.", icon: CreditCard, query: "I want to lower my monthly payment" },
  ] : [];
  return (
    <div className="space-y-2">
      {options.map(({ title, description, icon: Icon, query }) => (
        <button
          disabled={disabled}
          key={title}
          onClick={() => onSelect(query)}
          className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition-colors hover:border-brand-border hover:bg-brand-soft/50 disabled:opacity-50"
        >
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-ink">
            <Icon className="size-5" strokeWidth={1.6} />
          </span>
          <span className="flex-1">
            <span className="block text-sm font-semibold">{title}</span>
            <span className="mt-0.5 block text-xs text-slate-500">{description}</span>
          </span>
          <ChevronRight className="size-4 text-slate-400" />
        </button>
      ))}
      {kind === "loan-details" && (
        <Button variant="secondary" onClick={() => onSelect("Explain my loan contract")} disabled={disabled}>
          <FileText />Understand my contract
        </Button>
      )}
    </div>
  );
}
