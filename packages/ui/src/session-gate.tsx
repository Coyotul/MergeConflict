"use client";

import { useId, useState } from "react";
import { ArrowRight, Check, Eye, EyeOff, FileCheck2, FlaskConical, LoaderCircle, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { Button } from "./button";
import { Logo, Pill } from "./primitives";
import { cn } from "./utils";

interface SessionGateProps {
  role: "customer" | "reviewer";
  loading: boolean;
  error: string | null;
  demoAccount: { name: string; email: string; password: string };
  /** Optional list of demo customers; when present each one gets a fill-in button. */
  demoAccounts?: { name: string; email: string; password: string; scenario: string }[];
  onLogin: (credentials: { email: string; password: string }) => Promise<void>;
  onClearError: () => void;
}

export function SessionGate({ role, loading, error, demoAccount, demoAccounts, onLogin, onClearError }: SessionGateProps) {
  const id = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const customer = role === "customer";
  const RoleIcon = customer ? UserRound : ShieldCheck;
  const label = customer ? "customer" : "bank agent";

  return <main className="app-backdrop flex min-h-dvh items-center justify-center p-4 sm:p-8">
    <div className="grid w-full max-w-[1100px] overflow-hidden rounded-[28px] bg-white shadow-2xl md:grid-cols-[.95fr_1fr]">
      <section className="relative flex flex-col justify-between overflow-hidden bg-primary p-7 text-ink sm:p-10 lg:p-12" aria-label="About the prototype">
        <div className="pointer-events-none absolute -bottom-32 -right-36 size-[430px] rounded-full border-[70px] border-ink/5" aria-hidden="true" />
        <Logo />
        <div className="relative py-10 lg:py-16">
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-ink/20 px-3 py-1.5 text-[10px] font-semibold tracking-[.14em]"><FlaskConical className="size-3.5" />LOCAL CREDIT PROTOTYPE</span>
          <h1 className="text-[clamp(32px,3.6vw,48px)] font-semibold leading-[1.12] tracking-[-.045em]">{customer ? <>Big plans.<br />Clear steps.<br /><span className="text-ink/55">Your next chapter.</span></> : <>Better evidence.<br />Clear decisions.<br /><span className="text-ink/55">A human in control.</span></>}</h1>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-ink/70">{customer ? "Explore credit with a little guidance. Understand the numbers, prepare your documents and follow every step in one place." : "A dedicated workspace to inspect loan applications, request clarification and record your independent decision."}</p>
          <div className="mt-8 space-y-3 text-xs font-medium">
            {(customer ? ["Guided credit assistant", "Transparent loan simulations", "Application tracking, end to end"] : ["Your assigned application queue", "Customer documents & calculations", "Justified decisions & audit history"]).map((text) => <p key={text} className="flex items-center gap-2.5"><span className="flex size-5 items-center justify-center rounded-full bg-ink text-primary"><Check className="size-3" /></span>{text}</p>)}
          </div>
        </div>
        <div className="relative flex items-start gap-3 border-t border-ink/15 pt-5"><FileCheck2 className="mt-0.5 size-5 shrink-0" /><p className="text-[11px] leading-relaxed text-ink/65">Raiffeisen-inspired colors. Independent fictional product, not affiliated with or endorsed by any bank.</p></div>
      </section>

      <section className="flex min-w-0 flex-col justify-center p-7 sm:p-10 lg:p-12" aria-label={`${customer ? "Customer" : "Bank agent"} sign-in`}>
        <nav aria-label="Sign-in workspace" className="mb-8 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">
          {[{ role: "customer", title: "Customer", icon: UserRound, href: "http://127.0.0.1:3000" }, { role: "reviewer", title: "Bank agent", icon: ShieldCheck, href: "http://127.0.0.1:3001" }].map((item) => <a key={item.role} href={item.role === role ? "/" : item.href} aria-current={item.role === role ? "page" : undefined} className={cn("flex items-center justify-center gap-2 rounded-lg px-3 py-3 text-xs font-semibold transition-colors", item.role === role ? "bg-ink text-primary shadow-sm" : "text-slate-500 hover:bg-white")}><item.icon className="size-4" />{item.title}</a>)}
        </nav>
        <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-soft text-ink"><RoleIcon className="size-6" strokeWidth={1.7} /></span>
        <Pill tone="slate" className="w-fit">{customer ? "Customer workspace" : "Bank agent workspace"}</Pill>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight">{customer ? "Welcome back." : "Sign in to review."}</h2>
        <p className="mb-6 mt-2 text-sm leading-relaxed text-slate-500">{customer ? "Your credit journey, right where you left it." : "Review the evidence. You make the demo decision."}</p>

        <form aria-label={`${customer ? "Customer" : "Bank agent"} login form`} aria-busy={loading} onSubmit={(event) => { event.preventDefault(); if (!loading) void onLogin({ email, password }); }} className="space-y-4">
          <div><label htmlFor={`${id}-email`} className="field-label">Email address</label><input id={`${id}-email`} className="field" type="email" name="email" autoComplete="username" placeholder={demoAccount.email} required maxLength={254} disabled={loading} value={email} onChange={(event) => { setEmail(event.target.value); onClearError(); }} /></div>
          <div><label htmlFor={`${id}-password`} className="field-label">Password</label><div className="relative"><input id={`${id}-password`} className="field pr-12" type={showPassword ? "text" : "password"} name="password" autoComplete="current-password" placeholder="Enter the demo password" required maxLength={128} disabled={loading} value={password} onChange={(event) => { setPassword(event.target.value); onClearError(); }} /><button type="button" disabled={loading} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)} className="absolute right-2 top-1.5 rounded-lg p-2 text-slate-500 hover:bg-slate-100">{showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button></div></div>
          {error && <p role="alert" aria-label="Sign-in error" className="rounded-xl bg-red-50 p-3 text-xs leading-relaxed text-red-700">{error}</p>}
          <Button type="submit" size="lg" className="w-full justify-between" disabled={loading || !email.trim() || !password}>{loading ? <><span role="status">Connecting locally…</span><LoaderCircle className="animate-spin" /></> : <>Sign in as {label}<ArrowRight /></>}</Button>
        </form>

        {demoAccounts && demoAccounts.length > 0 ? <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 flex items-center justify-between gap-2"><p className="text-xs font-semibold">Try a demo customer</p><Pill tone="slate" className="px-2 py-0 text-[9px]">Public demo accounts</Pill></div>
          <p className="mb-3 text-[11px] text-slate-500">All share the password <span className="font-mono font-medium text-ink">{demoAccounts[0].password}</span></p>
          <ul aria-label="Demo customers" className="max-h-56 space-y-1 overflow-y-auto">
            {demoAccounts.map((account) => <li key={account.email}><button type="button" disabled={loading} aria-pressed={email === account.email} onClick={() => { setEmail(account.email); setPassword(account.password); onClearError(); }} className={cn("flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-[11px] transition-colors hover:bg-white disabled:opacity-60", email === account.email && "bg-white shadow-sm")}><span><span className="font-semibold">{account.name}</span><span className="text-slate-500"> — {account.scenario}</span></span><ArrowRight className="size-3.5 shrink-0 text-slate-400" /></button></li>)}
          </ul>
        </div> : <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 flex items-center justify-between gap-2"><p className="text-xs font-semibold">Try it as {demoAccount.name.split(" ")[0]}</p><Pill tone="slate" className="px-2 py-0 text-[9px]">Public demo account</Pill></div>
          <dl className="space-y-1.5 text-[11px]"><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Email</dt><dd className="break-all font-medium">{demoAccount.email}</dd></div><div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Password</dt><dd className="font-mono font-medium">{demoAccount.password}</dd></div></dl>
          <Button type="button" variant="outline" size="sm" className="mt-4 w-full" disabled={loading} onClick={() => { setEmail(demoAccount.email); setPassword(demoAccount.password); onClearError(); }}>Use {label} demo account<ArrowRight /></Button>
        </div>}
        <p className="mt-5 flex items-start gap-2 text-[10px] leading-relaxed text-slate-500"><LockKeyhole className="mt-0.5 size-3.5 shrink-0" />Demo authentication only, not production banking security. Use the public credentials above, never a real banking password or personal data.</p>
      </section>
    </div>
  </main>;
}
