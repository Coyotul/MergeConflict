"use client";
import { Button } from "@banking/ui/button";
export default function ErrorPage({ reset }: { reset: () => void }) { return <div role="alert" className="p-10"><h2 className="text-xl font-semibold">Something interrupted this view.</h2><p className="mt-3 text-sm text-slate-500">Your recorded application state remains on the local demo service. Try loading the view again.</p><Button onClick={reset} className="mt-5">Try again</Button></div>; }
