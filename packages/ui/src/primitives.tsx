import type { ReactNode } from "react";
import { ArrowUpRight, CircleCheck, FlaskConical, Info, Sparkles } from "lucide-react";
import { cn } from "./utils";

export function Logo({ compact = false, light = false }: { compact?: boolean; light?: boolean }) {
  return <div className={cn("flex items-center gap-3", light ? "text-white" : "text-ink")}><span className={cn("flex size-10 items-center justify-center rounded-xl", light ? "bg-primary text-ink" : "bg-ink text-primary")}><Sparkles className="size-6" strokeWidth={1.7} /></span>{!compact && <span className="text-2xl font-semibold tracking-[-0.07em]">luma<span className={light ? "text-primary" : "text-ink"}>.</span></span>}</div>;
}
export function AssistantAvatar({ small = false }: { small?: boolean }) {
  return <span className={cn("inline-flex shrink-0 items-center justify-center rounded-full bg-primary text-ink ring-1 ring-ink/5", small ? "size-9" : "size-14")}><Sparkles className={small ? "size-4" : "size-6"} strokeWidth={1.7} /></span>;
}
export function Panel({ children, className }: { children: ReactNode; className?: string }) { return <section className={cn("rounded-2xl border border-slate-200/80 bg-white p-5", className)}>{children}</section>; }
export function Pill({ children, tone = "brand", className }: { children: ReactNode; tone?: "brand" | "green" | "amber" | "red" | "slate"; className?: string }) {
  const colors = { brand: "bg-brand-soft text-brand-ink", green: "bg-emerald-50 text-emerald-700", amber: "bg-amber-50 text-amber-800", red: "bg-red-50 text-red-700", slate: "bg-slate-100 text-slate-600" };
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold leading-4", colors[tone], className)}>{children}</span>;
}
export function StatusBadge({ status, label }: { status: string; label: string }) {
  const tone = status === "APPROVED" ? "green" : status === "REJECTED" ? "red" : status === "MORE_INFORMATION_REQUIRED" || status === "AWAITING_DOCUMENTS" ? "amber" : status === "PENDING_HUMAN_REVIEW" ? "brand" : "slate";
  return <Pill tone={tone}><span className="size-1.5 rounded-full bg-current" />{label}</Pill>;
}
export function PilotNotice({ compact = false }: { compact?: boolean }) {
  return <div className={cn("rounded-2xl border border-brand-border/50 bg-brand-soft/50", compact ? "p-3" : "p-4")}><div className="mb-1.5 flex items-center justify-between gap-3"><p className="flex items-center gap-2 text-sm font-semibold text-ink"><FlaskConical className="size-4" />This is a pilot</p><span className="rounded-full bg-ink px-2.5 py-1 text-[10px] font-semibold text-primary">Guided demo</span></div><p className="text-xs leading-relaxed text-slate-500">Synthetic data. Guided demo responses, not a live AI. Calculations are indicative; human review is required. No real banking operations.</p></div>;
}
export function InfoNote({ children, warning = false }: { children: ReactNode; warning?: boolean }) { return <div className={cn("flex gap-2.5 rounded-xl p-3 text-xs leading-relaxed", warning ? "bg-amber-50 text-amber-800" : "bg-slate-50 text-slate-500")}><Info className="mt-0.5 size-4 shrink-0" /><div>{children}</div></div>; }
export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="mb-8 flex flex-wrap items-start justify-between gap-4"><div><p className="mb-3 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500"><span className="h-1 w-5 rounded-full bg-primary" />{eyebrow}</p><h1 className="text-3xl font-semibold tracking-tight text-ink">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500">{description}</p></div>{action}</div>;
}
export function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) { return <div><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold tracking-tight text-ink">{value}</p>{hint && <p className="mt-1 text-[11px] text-slate-400">{hint}</p>}</div>; }
export function EmptyState({ title, children }: { title: string; children: ReactNode }) { return <div className="rounded-2xl border border-dashed border-slate-200 p-8 text-center"><CircleCheck className="mx-auto mb-3 size-8 text-brand-ink" /><h3 className="font-semibold text-ink">{title}</h3><div className="mt-2 text-sm text-slate-500">{children}</div></div>; }
export function TinyArrow() { return <ArrowUpRight className="size-4" />; }
