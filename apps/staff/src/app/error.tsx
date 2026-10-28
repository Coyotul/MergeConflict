"use client";
import { Button } from "@banking/ui/button";
export default function ErrorPage({ reset }: { reset: () => void }) { return <div role="alert" className="p-10"><h2 className="text-xl font-semibold">This view was interrupted.</h2><p className="mt-3 text-sm text-slate-500">No successful decision is assumed from a failed operation. Reload to inspect the recorded application state.</p><Button onClick={reset} className="mt-5">Try again</Button></div>; }
