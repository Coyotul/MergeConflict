"use client";

import Link from "next/link";
import { Bell, CheckCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { formatDate } from "@banking/demo/format";
import { Popover, PopoverContent, PopoverTrigger } from "@banking/ui/popover";
import { Button } from "@banking/ui/button";

export function Notifications() {
  const { snapshot, command, busy } = useDemo();
  const unread = snapshot?.notifications.filter((n) => !n.read).length ?? 0;
  return <Popover><PopoverTrigger asChild><button className="relative rounded-xl p-2 text-slate-500 hover:bg-slate-100" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}><Bell className="size-5" strokeWidth={1.7} />{unread > 0 && <span className="absolute right-1 top-1 size-2 rounded-full bg-primary text-ink ring-2 ring-white" />}</button></PopoverTrigger><PopoverContent><div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold">Notifications</h2><Button variant="ghost" size="sm" disabled={busy || !unread} onClick={() => { void command("/notifications/read", {}).catch(() => {}); }}><CheckCheck />Mark read</Button></div><div className="max-h-96 space-y-3 overflow-y-auto">{snapshot?.notifications.length ? snapshot.notifications.map((n) => <Link href="/applications" key={n.id} className={`block rounded-xl border p-3 ${n.read ? "border-slate-100" : "border-brand-border/35 bg-brand-soft/40"}`}><p className="text-xs font-semibold">{n.title}</p><p className="mt-1 text-xs leading-relaxed text-slate-500">{n.text}</p><p className="mt-2 text-[10px] text-slate-400">{formatDate(n.at, true)}</p></Link>) : <p className="py-5 text-center text-xs text-slate-400">You’re all caught up.</p>}</div></PopoverContent></Popover>;
}
