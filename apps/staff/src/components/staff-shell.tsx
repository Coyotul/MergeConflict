"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ArrowUpRight, ChevronRight, ClipboardList, LogOut, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { useReviewQueue } from "@banking/demo/review-react";
import { DEMO_ACCOUNTS } from "@banking/demo/demo-accounts";
import { initials } from "@banking/demo/format";
import { Logo, Pill } from "@banking/ui/primitives";
import { SessionGate } from "@banking/ui/session-gate";
import { Button } from "@banking/ui/button";
import { cn } from "@banking/ui/utils";

export function StaffShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { snapshot, loading, error, login, logout, refresh, clearError } = useDemo();
  const { queue } = useReviewQueue();
  const pending = queue?.filter((a) => a.status === "PENDING_HUMAN_REVIEW").length ?? 0;
  if (!snapshot) return <SessionGate role="reviewer" loading={loading} error={error} demoAccount={DEMO_ACCOUNTS.reviewer} onLogin={login} onClearError={clearError} />;

  return (
    <div className="app-backdrop flex h-dvh max-h-dvh w-full overflow-hidden p-3 gap-3 md:gap-4 md:p-4 lg:gap-5 lg:p-5">
      <a href="#main-content" className="sr-only z-50 rounded-lg bg-white p-3 focus:not-sr-only focus:fixed focus:left-5 focus:top-5">Skip to content</a>
      <aside className="flex w-[76px] shrink-0 flex-col py-3 lg:w-[206px] h-full overflow-y-auto" aria-label="Bank agent navigation">
        <Link href="/" className="mb-7 px-3 lg:px-4" aria-label="Luma bank agent home">
          <span className="hidden lg:block"><Logo light /></span>
          <span className="lg:hidden"><Logo light compact /></span>
        </Link>
        <p className="mb-4 hidden px-4 text-xs font-medium text-white/45 lg:block">Bank agent workspace</p>
        <nav className="space-y-1.5">
          {[
            { href: "/", label: "Application queue", icon: ClipboardList },
          ].map(({ href, label, icon: Icon }) => {
            const active = href === "/";
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-11 items-center justify-center gap-3 rounded-xl px-4 text-sm font-medium transition-colors lg:justify-start",
                  active ? "bg-primary text-ink" : "text-white/65 hover:bg-white/7 hover:text-white"
                )}
              >
                <Icon className="size-[19px] shrink-0" />
                <span className="hidden lg:inline">{label}</span>
                {href === "/" && (
                  <span className={cn("ml-auto hidden rounded-md px-1.5 py-0.5 text-xs font-semibold lg:inline", active ? "bg-ink/10 text-ink" : "bg-white/10 text-white")}>
                    {pending}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="mt-6 hidden rounded-2xl border border-white/10 bg-white/5 p-4 lg:block">
          <ShieldCheck className="mb-2 size-5 text-primary" />
          <p className="text-sm font-medium text-white">Evidence first.<br />Independent judgment.</p>
          <p className="mt-2 text-xs leading-relaxed text-white/55">Automation organizes. You inspect the evidence and record the demo decision.</p>
        </div>
        <div className="mt-auto space-y-1.5 pt-6">
          <a
            href="http://127.0.0.1:3000"
            target="_blank"
            rel="noreferrer"
            aria-label="Open customer workspace"
            className="flex h-10 items-center justify-center gap-3 rounded-xl px-4 text-xs text-white/65 hover:bg-white/7 lg:justify-start"
          >
            <ArrowUpRight className="size-4" />
            <span className="hidden lg:inline">Customer workspace</span>
          </a>
          <button
            onClick={() => { void logout(); }}
            aria-label="Sign out"
            className="flex h-10 w-full items-center justify-center gap-3 rounded-xl px-4 text-xs text-white/65 hover:bg-white/7 lg:justify-start"
          >
            <LogOut className="size-4" />
            <span className="hidden lg:inline">Sign out</span>
          </button>
          <p className="hidden px-4 pt-3 text-xs leading-relaxed text-white/40 lg:block">
            Luma prototype · local demo<br />Independent · synthetic data only
          </p>
        </div>
      </aside>
      <div className="main-surface flex min-w-0 flex-1 flex-col h-full overflow-hidden rounded-[24px] bg-white lg:rounded-[28px]">
        <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-6 lg:px-8">
          <div className="flex items-center gap-2 text-xs">
            <span className="hidden text-slate-400 sm:inline">Bank agent</span>
            <ChevronRight className="size-3 text-slate-300" />
            <span className="font-semibold text-slate-600">
              {path === "/" ? "Application queue" : "Application review"}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Pill tone="brand" className="hidden sm:inline-flex">
              <ShieldCheck className="size-3" />Credit reviewer
            </Pill>
            <span className="flex size-9 items-center justify-center rounded-full bg-primary text-xs font-semibold text-ink">
              {initials(snapshot.actor.name)}
            </span>
            <span className="hidden text-xs font-semibold lg:block">{snapshot.actor.name}</span>
          </div>
        </header>
        {error && (
          <div role="alert" className="flex shrink-0 flex-wrap items-center justify-between gap-3 bg-red-50 px-6 py-2.5 text-xs text-red-700">
            <span>{error}</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => { void refresh(); }}>Retry</Button>
              <Button variant="ghost" size="sm" onClick={clearError}>Dismiss</Button>
            </div>
          </div>
        )}
        <main id="main-content" className="min-w-0 flex-1 min-h-0 bg-slate-50 p-6 lg:p-8 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
