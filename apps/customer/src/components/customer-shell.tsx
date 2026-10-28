"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { DEMO_ACCOUNTS } from "@banking/demo/demo-accounts";
import { Pill } from "@banking/ui/primitives";
import { SessionGate } from "@banking/ui/session-gate";
import { Button } from "@banking/ui/button";
import { cn } from "@banking/ui/utils";
import { Notifications } from "./notifications";
import { CustomerSidebar, customerNavigation } from "./customer-sidebar";

export function CustomerShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { snapshot, loading, error, login, refresh, clearError } = useDemo();
  if (!snapshot) return <SessionGate role="customer" loading={loading} error={error} demoAccount={DEMO_ACCOUNTS.customer} onLogin={login} onClearError={clearError} />;
  const title = customerNavigation.find((n) => n.href === path)?.label ?? "Privacy & preferences";
  return <div className="app-backdrop flex min-h-dvh gap-5 p-4 lg:gap-6 lg:p-5">
    <a href="#main-content" className="sr-only z-50 rounded-lg bg-white p-3 focus:not-sr-only focus:fixed focus:left-5 focus:top-5">Skip to content</a>
    <CustomerSidebar />
    <div className="main-surface flex min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] bg-white lg:rounded-[32px]">
      <header className="flex min-h-20 items-center justify-between gap-4 border-b border-slate-100 px-6 lg:px-8"><div className="flex items-center gap-2 text-xs"><span className="hidden text-slate-400 sm:inline">Customer workspace</span><ChevronRight className="hidden size-3 text-slate-300 sm:block" /><span className="font-medium text-slate-600">{title}</span></div><div className="flex items-center gap-4"><Pill tone="slate" className="hidden sm:inline-flex"><span className="size-1.5 rounded-full bg-emerald-500" />Local demo</Pill><Notifications /><span className="h-7 w-px bg-slate-100" /><Link href="/settings" aria-label="Your profile and preferences" className="flex size-9 items-center justify-center rounded-full bg-primary text-xs font-semibold text-ink">{snapshot.customer.initials}</Link><span className="hidden text-xs font-semibold text-slate-700 xl:block">{snapshot.customer.name}</span></div></header>
      {error && <div role="alert" className="flex items-center justify-between gap-3 bg-red-50 px-6 py-3 text-xs text-red-700"><span>{error}</span><div className="flex gap-2"><Button variant="ghost" size="sm" onClick={() => { void refresh(); }}>Retry</Button><Button variant="ghost" size="sm" onClick={clearError}>Dismiss</Button></div></div>}
      <main id="main-content" className={cn("min-w-0 flex-1", path === "/" ? "flex min-h-[650px] flex-col lg:h-[calc(100dvh-120px)]" : "bg-slate-50 p-6 lg:p-8")}>{children}</main>
    </div>
  </div>;
}
