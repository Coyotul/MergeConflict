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
  return (
    <div className="app-backdrop flex h-screen max-h-screen h-dvh max-h-dvh w-full min-h-0 overflow-hidden p-3 gap-3 md:gap-4 md:p-4 lg:gap-5 lg:p-5">
      <a href="#main-content" className="sr-only z-50 rounded-lg bg-white p-3 focus:not-sr-only focus:fixed focus:left-5 focus:top-5">Skip to content</a>
      <CustomerSidebar />
      <div className="main-surface flex min-w-0 flex-1 flex-col h-full min-h-0 overflow-hidden rounded-[24px] bg-white lg:rounded-[28px]">
        <header className="flex h-14 lg:h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-100 px-6 lg:px-8">
          <div className="flex items-center gap-2 text-xs">
            <span className="hidden text-slate-500 sm:inline">Customer workspace</span>
            <ChevronRight className="hidden size-3 text-slate-400 sm:block" />
            <span className="font-semibold text-slate-700">{title}</span>
          </div>
          <div className="flex items-center gap-4">
            <Pill tone="slate" className="hidden sm:inline-flex">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Local demo
            </Pill>
            <Notifications />
            <span className="h-7 w-px bg-slate-100" />
            <Link href="/settings" aria-label="Your profile and preferences" className="flex size-9 items-center justify-center rounded-full bg-primary text-xs font-semibold text-ink">
              {snapshot.customer.initials}
            </Link>
            <span className="hidden text-xs font-semibold text-slate-700 xl:block">{snapshot.customer.name}</span>
          </div>
        </header>
        {error && (
          <div role="alert" className="flex shrink-0 items-center justify-between gap-3 bg-red-50 px-6 py-2.5 text-xs text-red-700">
            <span>{error}</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => { void refresh(); }}>Retry</Button>
              <Button variant="ghost" size="sm" onClick={clearError}>Dismiss</Button>
            </div>
          </div>
        )}
        <main
          id="main-content"
          className={cn(
            "min-w-0 flex-1 min-h-0 overflow-hidden flex flex-col",
            path === "/" ? "" : "bg-slate-50 p-6 lg:p-8 overflow-y-auto"
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
