"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, CreditCard, FileClock, LayoutDashboard, LogOut, MessageCircle, Settings2, ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { Logo } from "@banking/ui/primitives";
import { cn } from "@banking/ui/utils";

export const customerNavigation = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/", label: "AI assistant", icon: MessageCircle },
  { href: "/products", label: "Explore loans", icon: SlidersHorizontal },
  { href: "/loans", label: "My loans", icon: CreditCard },
  { href: "/applications", label: "Applications", icon: FileClock },
];

export function CustomerSidebar() {
  const path = usePathname();
  const { snapshot, logout } = useDemo();
  const attention = snapshot?.applications.filter((a) => a.status === "MORE_INFORMATION_REQUIRED").length ?? 0;

  return (
    <aside className="flex w-[76px] shrink-0 flex-col py-2.5 lg:w-[206px] h-full min-h-0 overflow-y-auto" aria-label="Primary navigation">
      <Link href="/" className="mb-6 px-3 lg:px-4" aria-label="Luma assistant">
        <span className="hidden lg:block"><Logo light /></span>
        <span className="lg:hidden"><Logo light compact /></span>
      </Link>
      <p className="mb-2 hidden px-4 text-xs font-medium text-white/45 lg:block">Customer workspace</p>
      <nav className="space-y-1">
        {customerNavigation.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={path === href ? "page" : undefined}
            aria-label={label}
            className={cn(
              "flex h-10 items-center justify-center gap-3 rounded-xl px-4 text-sm font-medium transition-colors lg:justify-start",
              path === href ? "bg-primary text-ink" : "text-white/65 hover:bg-white/7 hover:text-white"
            )}
          >
            <Icon className="size-[18px] shrink-0" strokeWidth={1.7} />
            <span className="hidden lg:inline">{label}</span>
            {href === "/" && <span className={cn("ml-auto hidden size-1.5 rounded-full lg:block", path === href ? "bg-ink" : "bg-primary")} />}
            {href === "/applications" && attention > 0 && (
              <span className="ml-auto hidden rounded-md bg-primary px-1.5 py-0.5 text-xs font-semibold text-ink lg:block">
                {attention}
              </span>
            )}
          </Link>
        ))}
      </nav>
      <div className="mt-4 hidden rounded-2xl border border-white/10 bg-white/5 p-3.5 2xl:block">
        <Sparkles className="mb-2 size-4 text-primary" />
        <p className="text-xs font-medium text-white">A little clarity goes a long way.</p>
        <p className="mt-1 text-[11px] leading-relaxed text-white/55">Let’s find the next step that works for you.</p>
        <Link href="/?topic=support" className="mt-2.5 inline-flex items-center gap-1.5 text-xs font-semibold text-primary">
          Talk to someone<ArrowUpRight className="size-3" />
        </Link>
      </div>
      <div className="mt-auto space-y-1 pt-4">
        <Link
          href="/settings"
          aria-label="Privacy and preferences"
          className="flex h-9 items-center justify-center gap-3 rounded-xl px-4 text-xs text-white/60 hover:bg-white/7 lg:justify-start"
        >
          <Settings2 className="size-4" />
          <span className="hidden lg:inline">Preferences</span>
        </Link>
        <a
          href="http://127.0.0.1:3001"
          target="_blank"
          rel="noreferrer"
          aria-label="Open bank agent workspace"
          className="flex h-9 items-center justify-center gap-3 rounded-xl px-4 text-xs text-white/60 hover:bg-white/7 lg:justify-start"
        >
          <ShieldCheck className="size-4" />
          <span className="hidden lg:inline">Bank agent workspace</span>
          <ArrowUpRight className="ml-auto hidden size-3.5 lg:block" />
        </a>
        <button
          onClick={() => { void logout(); }}
          aria-label="Sign out"
          className="flex h-9 w-full items-center justify-center gap-3 rounded-xl px-4 text-xs text-white/60 hover:bg-white/7 lg:justify-start"
        >
          <LogOut className="size-4" />
          <span className="hidden lg:inline">Sign out</span>
        </button>
        <p className="hidden px-4 pt-2 text-[11px] leading-relaxed text-white/40 lg:block">
          Luma prototype · local demo<br />Independent · synthetic data only
        </p>
      </div>
    </aside>
  );
}
