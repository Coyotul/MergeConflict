"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, FileClock, LogOut, MessageCircle, Settings2, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { useMyApplications } from "@banking/demo/review-react";
import { Logo } from "@banking/ui/primitives";
import { cn } from "@banking/ui/utils";

export const customerNavigation = [
  { href: "/", label: "AI assistant", icon: MessageCircle },
  { href: "/applications", label: "Applications", icon: FileClock },
];

export function CustomerSidebar() {
  const path = usePathname();
  const { snapshot, logout } = useDemo();
  const { applications } = useMyApplications(snapshot?.customer.id);
  const attention = applications?.filter((a) => a.status === "MORE_INFORMATION_REQUIRED").length ?? 0;

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
